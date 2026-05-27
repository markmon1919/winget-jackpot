#!/usr/bin/env .venv/bin/python


import json, os, platform, random, redis, shutil, time, threading
from monitor import log_message, play_alert, get_jackpot_bar
from decimal import Decimal
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from dotenv import load_dotenv
from database import db

load_dotenv()

colors = {}
for key, value in os.environ.items():
    if key.isupper() and not key.startswith("DB_") and not key.startswith("PROVIDER_"):
        colors[key] = value.encode("utf-8").decode("unicode_escape")
        
LOG_LEVEL = os.getenv("LOG_LEVEL")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
REQUEST_FROMS = [r.strip() for r in os.getenv("REQUEST_FROMS", "req1,req2").split(",")]


def setup_driver():
    options = Options()
    if platform.system() != "Darwin" or os.getenv("IS_DOCKER") == "1":
        options.binary_location = "/opt/google/chrome/chrome"
        options.add_argument('--disable-dev-shm-usage')

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")

    service = Service(shutil.which("chromedriver"))
    return webdriver.Chrome(service=service, options=options)

# -------------------------
# Fetch HTML via Selenium
# -------------------------
def fetch_html(driver: webdriver.Chrome, url: str, provider: dict):
    driver.get(url)
    time.sleep(1)

    provider_items = driver.find_elements(By.CSS_SELECTOR, ".provider-item")
    
    for item in provider_items:
        try:
            img_elem = item.find_element(By.CSS_SELECTOR, ".provider-icon img")
            img_url = img_elem.get_attribute("src")
            
            if provider.get("hash") in img_url.lower():
                item.click()
                break
        except Exception:
            continue
        
    time.sleep(1)
    scroll_game_list(driver)
    return driver.page_source

def scroll_game_list(driver, pause_time: float = 1.0, max_tries: int = 20):
    """Scroll the .scroll-view.with-provider element until all games are loaded."""
    container = driver.find_element(By.CSS_SELECTOR, ".scroll-view.with-provider")

    last_height = 0
    for _ in range(max_tries):
        driver.execute_script("""
            arguments[0].scrollTo(0, arguments[0].scrollHeight);
        """, container)

        time.sleep(pause_time)
        
        new_height = driver.execute_script("return arguments[0].scrollHeight", container)
        
        if new_height == last_height:
            break
        last_height = new_height

def fetch_hs_data(driver: webdriver.Chrome, provider: dict) -> list:
    while not stop_event.is_set():
        # now_time = Decimal(str(time.time()))
        filtered_games = []
        # all_games = []
        game_blocks = driver.find_elements(By.CSS_SELECTOR, ".game-block")
        
        for block in game_blocks:
            try:
                name = block.find_element(By.CSS_SELECTOR, ".game-title").text.strip()
                # if name:
                #     all_games.append(name)
                if "PG" in provider.get("initial"):
                    if name in ("Wild Ape#3258", "Heist Stakes"):
                        continue
                    
                value_text = block.find_element(By.CSS_SELECTOR, ".progress-value").text.strip()
                value = float(value_text.replace("%", ""))
                
                # if value < 50: continue
                    
                progress_bar_elem = block.find_element(By.CSS_SELECTOR, ".progress-bar")
                bg = progress_bar_elem.value_of_css_property("background-color").lower()
                up = "red" if "255, 0, 0" in bg else "green"
                
                # if up == "red": continue
                # if all([value < 50, up == "red"]): continue

                history = {}
                history_tags = block.find_elements(By.CSS_SELECTOR, ".game-info-list .game-info-item")
                
                for item in history_tags:
                    label = item.find_element(By.CSS_SELECTOR, ".game-info-label").text.strip().rstrip(":").replace(" ", "").lower()
                    period_elem = item.find_element(By.CSS_SELECTOR, ".game-info-value")
                    period_text = period_elem.text.strip()
                    period = float(period_text.replace("%", ""))
                    history[label] = period
                    
                filtered_games.append({
                    "name": name, 
                    "jackpot_value": value, 
                    "meter_color": up, 
                    **history
                })
            except Exception as e:
                log_message("error", f"🤖❌  {e}")
                
        if filtered_games:
            filtered_games.sort(key=lambda g: g["name"], reverse=False)
            
            # print(f"\n\tAll Games: \n\t{providers.get("name").color}{'\n\t'.join(g for g in all_games)}{colors['RES']}")
                
            r.set("filtered_games", json.dumps(filtered_games))
            
def fetch_api_data():
    game_state = {}  
              
    while not stop_event.is_set():
        try:
            trend_data_raw = r.get("trend_data")
            if not trend_data_raw:
                time.sleep(0.5)
                continue
                
            trending_games = json.loads(trend_data_raw)

            api_games = [
                game_data
                for game in trending_games[provider.get("initial")].values()
                for game_data in game.values()
                if game_data.get('value') >= 90 and game_data.get('up')
            ]
            
            unique_games = { g['name']: g for g in api_games }.values()

            filtered_games_raw = r.get("filtered_games")
            if not filtered_games_raw:
                time.sleep(0.5)
                continue
            
            filtered_games = json.loads(filtered_games_raw)
            
            merged = {}
            
            for game in unique_games:
                merged[game['name']] = game.copy()
                
            # Second list (merge / overwrite)
            for game in filtered_games:
                name = game['name']
                if name in merged:
                    merged[name].update(game)
                    
            merged_games = sorted(
                merged.values(),
                # key=lambda x: x['value'],
                # reverse=True
                key=lambda x: x['name'],
                reverse=False
            )

            now = time.time()
            today = time.localtime(now)
            messages = []
            
            # tag = "💥💥💥 " if game.get('trending') else "🔥🔥🔥 "
            # signal = f"{LRED}⬇{RES}" if api['meter'] == "red" else f"{LGRE}⬆{RES}"
            # bet_str = f"{BLNK if game.get('bet_lvl') != 'Low' else ''}💰 {BLU if game.get('bet_lvl') in [ 'Mid', 'Low' ] else BLYEL if game.get('bet_lvl') == 'Bonus' else BGRE}{game.get('bet_lvl').upper()}{RES} "
            
            for game_data in merged_games:                
                game_name, hs, api = make_object(game_data)
                hs_jackpot_bar = get_jackpot_bar(hs['jackpot'], hs['meter'])
                api_jackpot_bar = get_jackpot_bar(api['jackpot'], api['meter'])
                
                # --- initialize or retrieve game state ---
                state = game_state.setdefault(game_name, {
                    "prev_jackpot": 0.0,
                    "prev_10m": 0.0,
                    "prev_delta": 0.0,
                    "prev_delta_10m": 0.0,
                    "last_jackpot_value": 0.0,
                    "last_10m_value": 0.0,
                    "last_delta_value": 0.0,
                    "last_delta_10m_value": 0.0,
                    # "delta_history": [],
                    # "delta_10m_history": []
                })
                
                prev_jackpot = state['last_jackpot_value'] if (api['jackpot'] != state['last_jackpot_value']) else state["prev_jackpot"]
                prev_10m = state['last_10m_value'] if (api['10m'] != state['last_10m_value']) else state["prev_10m"]
                
                delta = round(api['jackpot'] - prev_jackpot, 2)
                delta_10m = round(api['10m'] - prev_10m, 2)
                
                prev_delta = state['last_delta_value'] if (delta != state['last_delta_value']) else state["prev_delta"]
                prev_delta_10m = state['last_delta_10m_value'] if (delta_10m != state['last_delta_10m_value']) else state["prev_delta_10m"]
                
                # if delta != 0:
                #     state["prev_jackpot"] = api['jackpot']
                #     state["prev_delta"] = delta
                #     state["delta_history"].append({
                #         "value": api['jackpot'],
                #         "delta": delta,
                #         "time": time.time()
                #     })

                # if delta_10m != 0:
                #     state["prev_10m"] = api['10m']
                #     state["prev_delta_10m"] = delta_10m
                #     state["delta_10m_history"].append({
                #         "value": api['10m'],
                #         "delta": delta_10m,
                #         "time": time.time()
                #     })
                    
                delta_shift_10m = round(delta_10m - prev_delta_10m, 2)
                predicted_delta_10m = delta_10m + delta_shift_10m * 0.5 - delta_10m * 0.2
                
                abs_prev = abs(prev_delta_10m)
                abs_curr = abs(delta_10m)
                polarity_flip = (prev_delta_10m > 0 > delta_10m) or (prev_delta_10m < 0 < delta_10m)
                compression = abs_prev < 15 and abs_curr < 15
                explosion = abs(delta_shift_10m) >= 100
                
                volatility_score = (
                    abs(delta_10m) * 0.6
                    + abs(delta_shift_10m) * 0.3
                    + (50 if polarity_flip else 0)
                )
                
                # if api['jackpot'] != state['last_jackpot_value']:
                #     if ema_volatility is None:
                #         ema_volatility = volatility_score
                #     else:
                #         ema_volatility = (
                #             EMA_ALPHA * volatility_score
                #             + (1 - EMA_ALPHA) * ema_volatility
                #         )
                
                api_vol = abs(delta_10m) + abs(delta_shift_10m)
                jackpot_pressure = abs(delta)
                
                if jackpot_pressure < 1 and api_vol < 30:
                    session_mode = "COLD"
                elif jackpot_pressure < 2 and api_vol < 80:
                    session_mode = "WARM"
                elif jackpot_pressure >= 2 or api_vol >= 120:
                    session_mode = "HOT"
                else:
                    session_mode = "DRAIN"
                    
                if compression:
                    shock_state = "LOADED"
                elif polarity_flip and explosion:
                    shock_state = "SNAP"
                elif abs_curr < abs_prev and 5 <= abs_curr <= 15 and abs(predicted_delta_10m) < 20:
                    shock_state = "RELIEF"
                else:
                    shock_state = "CALM"
                    
                tag = "🔥🔥🔥 " if session_mode == "HOT" else "💥💥💥 "
                colored_hs_jackpot = f"{colors['RED'] if hs['meter'] == 'red' else colors['GRE']}{hs['jackpot']:.2f}{colors['RES']}"
                colored_api_jackpot = f"{colors['RED'] if api['meter'] == 'red' else colors['GRE']}{api['jackpot']:.2f}{colors['RES']}"
                colored_delta_10m = f"{colors['BMAG'] if abs(delta_10m) > 60 else colors['MAG']}{delta_10m:+.2f}{colors['RES']}"
                colored_session = f"{colors['ORA'] if session_mode == "HOT" else colors['YEL'] if session_mode == "WARM" else colors['LCYN'] if session_mode == "COLD" else colors['GRE']}{session_mode}{colors['RES']}"
                colored_shocked = f"{colors['ORA'] if shock_state == "SNAP" else colors['YEL'] if shock_state == "RELIEF" else colors['LCYN'] if shock_state == "CALM" else colors['GRE']}{shock_state}{colors['RES']}"
                colored_volume = f"{colors['WHTE']}Volume{colors['RES']}: {colors['BLBLU'] if api_vol >= 120 else colors['LBLU']}{round(api_vol, 2)}{colors['RES']}"
                colored_volatility = f"{colors['WHTE']}Volatility{colors['RES']}: {colors['LRED'] if volatility_score >= 50 else colors['LYEL']}{round(volatility_score, 2)}{colors['RES']}"

                api_signal = f"{colors['LRED']}▼{colors['RES']}" if delta < prev_delta else f"{colors['LGRE']}▲{colors['RES']}" if delta > prev_delta else f"{colors['LCYN']}◆{colors['RES']}"
                
                tag = "🔥🔥🔥 " if session_mode == "HOT" else "💥💥💥 "
                
                message = (
                    # f"\n\t{tag} {colors['BMAG']}{clean_name} {bet_str}{colors['RES']}{colors['DGRY']}→ {signal} "
                    # f"\n\t{tag} {colors['BMAG']}{game[data].get('name')} {colors['RES']}{colors['DGRY']}→  "
                    # f"\n\t{game[data].get('name')} | Value: {game[data].get('value')} | Up: {game[data].get('up')}"
                    
                    f"\n\t{tag} {colors[provider['color']]}{game_name}{colors['YEL']}: {colors['RES']}\n"
                    f"\n\t{hs_jackpot_bar} {colored_hs_jackpot}"
                    f"\n\t{api_jackpot_bar} {colored_api_jackpot} {api_signal} "
                    f"{colored_session} {f"{colors['BLNK']}🔥🔥🔥{colors['RES']} " if session_mode == "HOT" else ''}"
                    f"{colored_shocked} "
                    f"{f'{colors['BLNK']}🌀{colors['RES']} ' if any(x in colored_shocked for x in ['SNAP', 'RELIEF']) else ''} "
                    f"{colored_delta_10m} {colored_volume} {colored_volatility}"
                    
                    # f"\n\tTrending Game: {provider_data.get('name', 'Unknown')} | Value: {provider_data.get('value', 0)} | Up: {provider_data.get('up', False)}"
                    # f"\n\t10min: {provider_data.get('min10', 0)} | 1hr: {provider_data.get('hr1', 0)} | 3hr: {provider_data.get('hr3', 0)} | 6hr: {provider_data.get('hr6', 0)}"
                )

                messages.append(message)
                # log_message("info", message, overwrite=True, _overlay_key="hs_data")
                state["last_delta_value"] = delta
                state["last_delta_10m_value"] = delta_10m
                state["last_jackpot_value"] = api['jackpot']
                state["last_10m_value"] = api['10m']
                
            banner = (
                f"\n\t⏰  {colors['BYEL']}{time.strftime('%I', today)}{colors['BWHTE']}:{colors['BYEL']}{time.strftime('%M', today)}"
                f"{colors['BWHTE']}:{colors['BLYEL']}{time.strftime('%S', today)} {colors['LBLU']}{time.strftime('%p', today)} "
                f"{colors['MAG']}{time.strftime('%a', today)}{colors['RES']}"
            )
            
            full_message = "\n".join(messages)
            log_message("info", banner, overwrite=True, _overlay_key="banner")
            log_message("info", full_message, overwrite=True, _overlay_key="hs_data")
            
            # tag = "💥💥💥 " if game.get('trending') else "🔥🔥🔥 "
            # game_name = trending_games.get(provider["initial"])
            
            # message = (
            #     f"\n\t⏰  {colors['BYEL']}{time.strftime('%I', today)}{colors['BWHTE']}:{colors['BYEL']}{time.strftime('%M', today)}"
            #     f"{colors['BWHTE']}:{colors['BLYEL']}{time.strftime('%S', today)} {colors['LBLU']}{time.strftime('%p', today)} "
            #     f"{colors['MAG']}{time.strftime('%a', today)}{colors['RES']}"
            #     f"\n\tTrending Games: {trending_games.get(provider["initial"])}"
                
            #     # f"\n\t{tag} {colors['BMAG']}{clean_name} {bet_str}{colors['RES']}{colors['DGRY']}→ {signal} "
            # )
            
            # log_message("info", message, overwrite=True, _overlay_key="hs_data")
            stop_event.wait(0.5)
        except Exception as e:
            log_message("error", f"[trend_data] {e}", overwrite=True, _overlay_key="hs_data")
            time.sleep(0.5)
        
def make_object(obj: dict):
    game_name = obj.get("name")
    
    hs = {
        "jackpot": obj.get("jackpot_value", 0),
        "meter": obj.get("meter_color"),
        "10m": obj.get("min10", 0),
        "1h": obj.get("hr1", 0),
        "3h": obj.get("hr3", 0),
        "6h": obj.get("hr6", 0)
    }

    api = {
        "jackpot": obj.get("value", 0),
        "meter": "green" if obj.get("up") is True else "red" if obj.get("up") is False else None,
        "10m": obj.get("10min", 0),
        "1h": obj.get("1hr", 0),
        "3h": obj.get("3hrs", 0),
        "6h": obj.get("6hrs", 0)
    }
    
    return game_name, hs, api
        
def render_providers(providers):
    log_message("info", f"\n\n\t📘 {colors.get('ORA')}SCATTER TREND CHECKER{colors.get('RES')}\n\n")

    half = (len(providers) + 1) // 2
    lines = []

    for idx, left in enumerate(providers[:half], start=1):
        left_color_key = left.get("color")
        left_color = colors.get(left_color_key, colors.get("RES"))
        left_str = f"[{colors.get('WHTE')}{idx}{colors.get('RES')}] - {left_color}{left['name']}{colors.get('RES')}\t"

        right_index = idx - 1 + half
        if right_index < len(providers):
            right = providers[right_index]
            right_color_key = right.get("color")
            right_color = colors.get(right_color_key, colors.get("RES"))
            right_str = f"[{colors.get('WHTE')}{right_index + 1}{colors.get('RES')}] - {right_color}{right['name']}{colors.get('RES')}"
        else:
            right_str = ""

        lines.append(f"\t{left_str:<50}\t{right_str}")

    return "\n".join(lines)

def providers_list(providers: dict):
    providers_col = db["PROVIDER"]
    providers = list(providers_col.find({}, {"name": 1, "initial": 1, "color": 1, "hash": 1, "_id": 0}))

    while True:
        try:
            choice = int(input("\n\t🔔 Choose Provider: "))
            if 1 <= choice <= len(providers):
                provider = providers[choice - 1]
                provider_initial = provider["initial"]
                provider_name = provider["name"]
                provider_color_key = provider.get("color")
                provider_color = colors.get(provider_color_key, colors.get("RES"))

                log_message(
                    "info",
                    f"\n\tSelected: {provider_color}{provider_name}{colors.get('RES')} "
                    f"({provider_color}{provider_initial}{colors.get('RES')})\n"
                )
                return provider
            else:
                log_message("warning", "\t⚠️  Invalid choice. Try again.")
        except ValueError:
            log_message("warning", "\t⚠️  Please enter a valid number.")


if __name__ == "__main__":        
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True
    )
    
    try:
        r.ping()
        log_message("info", f"✅ Connected to Redis")
    except redis.exceptions.ConnectionError as e:
        log_message("error", f"🤖❌ Redis connection failed  {e}")
        
    stop_event = threading.Event()
        
    providers_col = db["PROVIDER"]
    providers = list(providers_col.find({}, {"name": 1, "initial": 1, "color": 1, "_id": 0}))
    
    log_message("info", colors.get('CLEAR',''))
    log_message("info", render_providers(providers))
    
    provider = providers_list(providers)
        
    urls_env = os.getenv("URLS")
    URLS_LIST = [url.strip() for url in urls_env.split(",") if urls_env.strip()]
    URLS = {url: url for url in URLS_LIST}
    url = next((url for url in URLS if 'win' in url), None) 

    servers_env = os.getenv("WS_URL")
    SERVERS_LIST = [url.strip() for url in servers_env.split(",") if servers_env.strip()]
    API_SERVERS = {url: url for url in SERVERS_LIST}
    api_server = next((url for url in API_SERVERS if 'localhost' in url), None) # local
    
    r.set("trend_provider", json.dumps(provider))
    r.set("trend_url", url)
    
    driver = setup_driver()
    fetch_html(driver, url, provider)
    # last_alerts = {}
    
    threads = []
    threads.append(threading.Thread(target=fetch_hs_data, args=(driver, provider,), daemon=True))
    threads.append(threading.Thread(target=fetch_api_data, daemon=True))
    
    for t in threads:
        t.start()
        
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        log_message("error", f"\n\n\t🤖❌  {colors.get('BLRED')}Main program interrupted.{colors.get('RES')}")
        stop_event.set()
    finally:
        for t in threads:
            t.join()
        
        r.delete("trend_provider")
        r.delete("trend_url")
        r.delete("filtered_games")
        r.delete("trend_data")
        r.close()
        log_message("warning", f"\n\n\t🤖❌  {colors.get('LYEL')}All threads shut down...{colors.get('RES')}")
        
        stop_event.set()
        
             
        # games = fetch_hs_data(driver) 
        # print(f"\n\tFiltered Games: \n\t{colors.get(provider["color"])}{'\n\t'.join(g['name'] for g in games)}{colors['RES']}")
        # data = get_game_data_from_local_api(provider, games) if games else None
        # save_trend_memory(data) if data else None
    
    # prev_game, prev_provider, prev_url = game, provider, url

    # try:    
    #     while not stop_event.is_set():
    #         try:
    #             game = json.loads(r.get("game"))
    #             provider = json.loads(r.get("provider"))
    #             url = r.get("url")
                
    #             if (game, provider, url) != (prev_game, prev_provider, prev_url):
    #                 print("🔔 Game/Provider/URL changed!")
    #                 # Stop old threads
    #                 stop_event.set()
    #                 fetcH_thread.join()
    #                 # Reset stop_event for new threads
    #                 stop_event.clear()
    #                 # Refresh driver
    #                 driver.get(url)
    #                 fetch_html(driver, url, game, provider)

    #                 fetcH_thread = threading.Thread(target=fetch_hs_data, args=(driver, game,), daemon=True)
    #                 fetcH_thread.start()
                        
    #                 prev_game, prev_provider, prev_url = game, provider, url
    #         except Exception as e:
    #             log_message("error", f"Monitor loop error: {e}")

    #         stop_event.wait(1)
    # except KeyboardInterrupt:
    #     log_message("error", f"\n\n\t🤖❌  {colors.get('BLRED')}Main program interrupted.{colors.get('RES')}")
    #     stop_event.set()
    #     fetcH_thread.join()
    #     r.close()
    # finally:                        
    #     log_message("warning", f"\n\n\t🤖❌  {colors.get('LYEL')}All threads shut down...{colors.get('RES')}")
        
    #     stop_event.set()
    #     fetcH_thread.join()
    #     r.close()
