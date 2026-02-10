#!/usr/bin/env .venv/bin/python

import json, os, platform, random, re, requests, shutil, subprocess, sys, threading, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from queue import Queue as ThQueue, Empty
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from config import (PROVIDERS, DEFAULT_PROVIDER_PROPS, URLS, USER_AGENTS, VOICES, PING, TREND_FILE,
                    LRED, LBLU, LCYN, LYEL, LMAG, LGRE, LGRY, RED, MAG, YEL, GRE, CYN, BLU, WHTE, BLRED, BLYEL, BLGRE, BLMAG, BLBLU, BLCYN, BDGRY, BYEL, BGRE, BMAG, BCYN, BWHTE, DGRY, BLNK, CLEAR, RES)


def setup_driver():
    options = Options()
    if platform.system() != "Darwin" or os.getenv("IS_DOCKER") == "1":
        options.binary_location = "/opt/google/chrome/chrome"
        options.add_argument('--disable-dev-shm-usage')
        
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')  # Disable images
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    # options.add_argument("--remote-debugging-port=9222") # share driver
    # options.add_argument(f"--user-data-dir={os.getcwd()}/chrome_profile_{session_id}")
    # options.add_argument(f"--profile-directory=Profile_{game.lower()}")
    
    service = Service(shutil.which("chromedriver"))
    return webdriver.Chrome(service=service, options=options)

def render_providers():
    print(f"\n\n\t📘 {MAG}SCATTER TREND CHECKER{RES}\n\n")

    providers = list(PROVIDERS.items())
    half = (len(providers) + 1) // 2
    lines = list()

    for idx, (left_provider, left_conf) in enumerate(providers[:half], start=1):
        left_color = left_conf.color
        left_str = f"[{WHTE}{idx}{RES}] - {left_color}{left_conf.provider}{RES}\t"
        
        right_index = idx - 1 + half
        if right_index < len(providers):
            right_provider, right_conf = providers[right_index]
            right_color = right_conf.color
            right_str = f"[{WHTE}{right_index + 1:>2}{RES}] - {right_color}{right_conf.provider}{RES}"
        else:
            right_str = ""

        lines.append(f"\t{left_str:<50}\t{right_str}")
    return "\n".join(lines)

def providers_list():
    providers = list(PROVIDERS.items())

    while True:
        try:
            choice = int(input("\n\t🔔 Choose Provider: "))
            if 1 <= choice <= len(providers):
                provider = providers[choice - 1][0]
                provider_name = providers[choice - 1][1].provider
                provider_color = providers[choice - 1][1].color
                print(f"\n\tSelected: {provider_color}{provider_name} {RES}({provider_color}{provider}{RES})\n\n")
                return provider, provider_name
            else:
                print("\t⚠️  Invalid choice. Try again.")
        except ValueError:
            print("\t⚠️  Please enter a valid number.")
    
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

def fetch_html_via_selenium(driver: webdriver.Chrome, url: str, provider: str):
    driver.get(url)
    time.sleep(2)

    provider_items = driver.find_elements(By.CSS_SELECTOR, ".provider-item")

    for item in provider_items:
        try:
            img_elem = item.find_element(By.CSS_SELECTOR, ".provider-icon img")
            img_url = img_elem.get_attribute("src")

            if PROVIDERS.get(provider).img_url.lower() in img_url.lower():
                driver.execute_script("arguments[0].scrollIntoView(true);", item)
                item.click()
                time.sleep(1)
                # driver.execute_script("arguments[0].scrollIntoView(true);", item)
                # driver.find_element(By.CSS_SELECTOR, ".sort-wrap .sort-icon").click()
                # time.sleep(1)
                # scroll_game_list(driver)
                break
        except Exception:
            continue

    time.sleep(2)
    scroll_game_list(driver)
    return driver.page_source

def extract_game_data(driver) -> list:
    filtered_games = []
    # all_games = []
    game_blocks = driver.find_elements(By.CSS_SELECTOR, ".game-block")

    for block in game_blocks:
        try:
            name = block.find_element(By.CSS_SELECTOR, ".game-title").text.strip()
            # if name:
            #     all_games.append(name)
            if "PG" in provider:
                if "Wild Ape#3258" in name:
                    continue
                if "Heist Stakes" in name:
                    name = name.replace("Heist", "Heist of")
            value_text = block.find_element(By.CSS_SELECTOR, ".progress-value").text.strip()
            value = float(value_text.replace("%", ""))
            
            if value < 50:
            # if value < 75:
            #     # print(f'{RED}Skipped{RES}: {name}, {value}, {up}')
                continue
            
            progress_bar_elem = block.find_element(By.CSS_SELECTOR, ".progress-bar")
            bg = progress_bar_elem.value_of_css_property("background-color").lower()
            up = "red" if "255, 0, 0" in bg else "green"
            
            if up == "red":
                continue
            
            history = {}
            history_tags = block.find_elements(By.CSS_SELECTOR, ".game-info-list .game-info-item")
            
            for item in history_tags:
                label = item.find_element(By.CSS_SELECTOR, ".game-info-label").text.strip().rstrip(":").replace(" ", "").lower()
                period_elem = item.find_element(By.CSS_SELECTOR, ".game-info-value")
                period_text = period_elem.text.strip()
                period = float(period_text.replace("%", ""))
                history[label] = period
                
            filtered_games.append({"name": name, "jackpot_value": value, "meter_color": up, **history})
            # print(f'{BLYEL}Final{RES}: {name}, {value}, {up}')
        except Exception:
            continue
        
    if filtered_games:
        filtered_games.sort(key=lambda g: g["name"], reverse=False)
    
        # all_games.sort(reverse=False)
        # print(f"\n\tAll Games: \n\t{PROVIDERS.get(provider).color}{'\n\t'.join(g for g in all_games)}{RES}")
    
        return filtered_games
    return None

def get_game_data_from_local_api(provider: str, games: list):
    user_agent = random.choice(USER_AGENTS)
    REQUEST_FROM = random.choice(["H5", "H6"])
    URL = next((url for url in URLS if 'helpslot' in url), None)
    HEADERS = {"Accept": "application/json", "User-Agent": user_agent}
    
    try:
        response = requests.get(f"{URL}/api/games?manuf={provider}&requestFrom={REQUEST_FROM}", headers=HEADERS)
        if response.status_code != 200:
            print(f"❌ Error {response.status_code}: {response.text}")
            return []
        try:
            json_data = response.json()
            data = json_data.get("data", [])
        except ValueError:
            print(f"❌ Server did not return JSON: {response.text}")
            return []
        
        if "PG" in provider:
            data = [g for g in data if g.get("value") >= 90 and g.get("up") and g.get("name") != "Wild Ape#3258"]
            # data = [g for g in data if all([g.get("min10") < 0, g.get("hr1") < 0]) and g.get("name") != "Wild Ape#3258"]
        else:
            data = [g for g in data if g.get("value") >= 90 and g.get("up") and g.get("name")]
        
        # print(f'\n{DGRY}Data{RES}: {WHTE}{data}{RES}')
        # print(f'\n{DGRY}Games{RES}: {WHTE}{games}{RES}')
        # data_dict = {d["name"]: d for d in data}  # API data keyed by name
        data_dict = {d["name"]: d for d in data}  # API data keyed by name
        # print(f"\n{WHTE}Before >> {RES}Data Dict: {data_dict}")
        # games_found = {g["name"]: g for g in games}
        # search_games = [name for name in games_found if name not in data_names]
        # Find missing games
        # print(f"\n{WHTE}Games Found Loop{RES}:")
        # games_found = {g["name"]: g for g in games}
        # for i in games_found:
        #     print(f"Get Name (i): {BLU}{i}{RES}")
            # ❌ Exception: string indices must be integers, not 'str'
            # print(f"Get Data_Dict.get(i[name]): {RED}{data_dict.get(i["name"])}{RES}")
        
        # print(f"\n{WHTE}Games Found Loop{RES}:")
        search_games = []
        games_found = [g for g in games if g["name"] in data_dict]
        if games_found:
            # print(f"\n\t{LRED}Games Found{RES}\n")
            data = [{**g, **data_dict.get(g["name"])} for g in games_found]
            data_dict = {d["name"]: d for d in data}
            # print(f"\n{MAG}{data_dict}{RES}")
            # for i in games_found:
            #     print(f"{WHTE}Games Found{RES}: {BLU}{i}{RES}")
        # Precompute for fast lookup
        # games_found = {g["name"]: g for g in games}
            search_games = [name for name in games if name not in games_found]
        else:
            # print(f"\n{LRED}Not Games Found{RES}")
            # search_games = [name for name in games]
            search_games = [name for name in games]
        #     if search_games:
        #         data = [{**g, **data_dict.get(g["name"])} for g in games_found]
        #         data_dict = {d["name"]: d for d in data}
        
        # for i in search_games:
        #     print(f"{WHTE}Search Games{RES}: {RED}{i}{RES}")
    
        # print(f"\n{WHTE}Search Games: {RES}{search_games}")
    # Fetch missing games in parallel
        if search_games:
            # search_game = [g["name"] for g in search_games]
            with ThreadPoolExecutor(max_workers=len(search_games)) as executor:
                # futures = [executor.submit(search_game_data_from_local_api, search["name"]) for search in search_games]
                futures = [executor.submit(search_game_data_from_local_api, search["name"]) for search in search_games]
                # wait(futures)
                # Collect results
                results = [f.result() for f in futures if f.result() is not None]
                # results = list(executor.map(search_game_data_from_local_api, search_games))
                
                # print(f"\n{WHTE}Results Loop{RES}: {RES}")
                # for i in results:
                #     print(f"{WHTE}Results{RES}: {LYEL}{i}{RES}")
            # data.extend(filter(None, results))
            # data.extend(filter(None, games_found))
            # games_found = [g for g in games if g["name"] in data_dict]
            results_dict = {r['name']: r for r in results}
            # for i in results_dict:
            #     if "Rooster Rumble" in i:
            #         print(f"{WHTE}Results Dict{RES}: {LYEL}{i}{RES}")
            data = [{**g, **results_dict[g['name']]} for g in search_games if g['name'] in results_dict]
            # for i in search_merge:
            #     if "Rooster Rumble" in i:
            #         print(f"{WHTE}Search Merge{RES}: {LYEL}{i}{RES}")
            # enriched = enrich_game_data(search_merge)
            # return enriched
                # if not games_found:
                #     print(f"\n{LRED}Not Games Found{RES}")
                #     data = [g for g in games if g["name"] in results_dict]
                #     # data_dict = {d["name"]: d for d in data}
                # else:
                # print(f"\n{LRED}Games Found{RES}")
                # data = [{**g, **data_dict.get(g["name"])} for g in results_dict]
                # data.extend(filter(None, search_merge))
                # data.extend(filter(None, games_found))
            # data_dict = {d["name"]: d for d in data}
            # print(f"\n{WHTE}Games Found Loop{RES}:")
            # print(f"\n{WHTE}Refactor Loop{RES}: {MAG}{data}{RES}")
        # games_found = [g for g in games if g["name"] in data_dict]
        # print(f"\n{CYN}Games Found List: {RES} {games_found}")
        # for i in games_found:
        #     print(f"Get Name (i): {BLU}{i}{RES}")
        #     print(f"Get Data_Dict.get(i[name]): {RED}{data_dict.get(i["name"])}{RES}")
        # data.extend(filter(None, games_found))
            
        # if games_found:
        #     data = [{**g, **data_dict.get(g["name"])} for g in games_found]
        #     print(f'\n{MAG}Refactor Data{RES}: {data}')
        #     data_dict = {d["name"]: d for d in data}
            
        # search_games = [g for g in games if g["name"] not in data_dict]
        # print(f"\n{WHTE}Search Games List{RES}: {search_games}")
        # # for i in search_games:
        # #     print(f"Get Name (i): {BLU}{i}{RES}")
        # #     print(f"Get Data_Dict.get(i[name]): {RED}{data_dict.get(i["name"])}{RES}") # Always None
        
        # # # search_games = [g for g in games_found if g["name"] not in data_dict]
        # # # print(f"\nSearch Games: {search_games}")

        # # # Now you can fetch their info
        # if search_games:
        #     search_game = {s["name"]: s for s in search_games}
        #     with ThreadPoolExecutor(max_workers=len(search_games)) as executor:
        #         # {s["name"]: s for s in search_games}
        #         # results = list(executor.map(search_game_data_from_local_api, search_games))
        #         results = list(executor.map(search_game_data_from_local_api, search_games))
        #         # print(f"\nResults: {results}")
        #         # print(f"\n{WHTE}Results Loop{RES}:")
        #         # for i in results:
        #         #     print(f"{YEL}{i}{RES}")
        #         print(f'\n{LBLU}Results List{RES}: {results}')
        #     search_refactor = [{**g, **results} for g in search_games]
        #     print(f'\n{MAG}Search Refactor Data{RES}: {search_refactor}')
            # data.extend(search_refactor)
            # data_dict = {d["name"]: d for d in data}
            
            # data.extend(filter(None, results))  # add fetched data to data list
            # search_merge = [{**g, **results} for g in search_games]
            # data.extend(search_merge)
            # data_dict = {d["name"]: d for d in data}  # API data keyed by name
            
            # data_dict = {d["name"]: d for d in data} # Rebuild data_dict including the newly fetched entries
            
        # data.extend(filter(None, search_games))
        # print(f"\n{WHTE}After >> Data List{RES}: {LGRE}{data}{RES}")
        # for i in data:
        #     print(f"Get Name (i): {BLU}{i}{RES}")
        #     print(f"Get Data_Dict.get(i[name]): {RED}{data_dict.get(i["name"])}{RES}")
        # Merge all games
        # print(f"Data: {data}")
        # print(f"\n{WHTE}After >> {RES}Data Dict: {data_dict}")
        # print(f"\nGames: {games}")
        # combined_games = [{**g, **data_dict.get(g["name"])} for g in games]
        # print(f"\n{WHTE}Combined Games List{RES}: {LCYN}{combined_games}{RES}")
        # print(f"\n{WHTE}Games Loop{RES}:")
        # for i in games:
        #     print(f"Get Name (i): {BLU}{i}{RES}")
        #     print(f"Get Data_Dict.get(i[name]): {RED}{data_dict.get(i["name"])}{RES}")
        # print(f"\n{WHTE}Combined Games Loop{RES}:")
        # for i in combined_games:
        #     print(f"Get Name (i): {BLU}{i}{RES}")
        #     print(f"Get Data_Dict.get(i[name]): {RED}{data_dict.get(i["name"])}{RES}")
        if data:
            enriched = enrich_game_data(data)
            return enriched
        return None
        # enriched = enrich_game_data(data)
        # return enriched
    except Exception as e:
        print(f"❌ Exception: {e}")
        return []
    
def search_game_data_from_local_api(game: str):
    # print(f'{WHTE}GAME STRING: {RES}{game}')
    user_agent = random.choice(USER_AGENTS)
    REQUEST_FROM = random.choice(["H5", "H6"])
    URL = next((url for url in URLS if 'helpslot' in url), None)
    HEADERS = {
        "Accept": "application/json",
        "User-Agent": user_agent
    }
    PARAMS = {
        "name": game,
        "requestFrom": REQUEST_FROM
    }
    
    try:
        response = requests.get(f"{URL}/api/games", headers=HEADERS, params=PARAMS)

        if response.status_code == 200:
            try:
                json_data = response.json()
                data = json_data.get("data", [])
                game_data = data[0] if data else None

                if game_data and game_data.get("value") >= 90:
                    return game_data
            except ValueError:
                print(f"❌ Server did not return JSON: {response.text}")
                json_data = {"error": "Invalid JSON response"}
    except Exception as e:
        print(f"❌ Error calling API: {e}")
        return {"error": str(e)}, REQUEST_FROM
    
def make_object(obj: dict):
    helpslot = {
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
    
    return helpslot, api

def enrich_game_data(games: list, provider: str = "JILI") -> list:
    """
    Enrich a list of game dicts with jackpot_value, meter_color, trending, and bet level.
    Filters and sorts games according to provider-specific rules.
    """
    enriched = []

    for g in games:
        helpslot, api = make_object(g)
        # Skip games that don't meet provider-specific thresholds
        # if provider in ["JILI", "PG"]:
        #     if any([
        #         not all((data["jackpot"] >= 50 for data in (helpslot, api))),
        #         # not all((helpslot["10m"] < 5, helpslot["1h"] < helpslot["3h"] < helpslot["6h"])),
        #         # not all(api[period] > 0 for period in ["1h", "3h", "6h"])
        #     ]):
        #         continue
            
        # Determine trending status
        trending = all([
            # any(data["meter"] == "red" for data in (helpslot, api)) and
            any([
                # helpslot["10m"] < 5 and helpslot["1h"] < helpslot["3h"] < helpslot["6h"],
                all((helpslot["10m"] <= 0, helpslot["10m"] < helpslot["1h"] < helpslot["3h"])),
                # all(api[period] > 0 for period in ["1h", "3h", "6h"])
            ])
            # any(data["meter"] == "red" for data in (helpslot, api)),
            # helpslot["10m"] < 5 and helpslot["1h"] < helpslot["3h"] < helpslot["6h"],
            # all(api[period] > 0 for period in ["1h", "3h", "6h"])
        ])
        
        # Determine bet level
        if api["jackpot"] > 95 and helpslot["jackpot"] > 95:
            bet_lvl = "Bonus" 
        elif all(data["jackpot"] > 85 for data in (helpslot, api)) or api["10m"] < -60:
            bet_lvl = "High"
        # elif (any(data["jackpot"] > 50 for data in (helpslot, api))
        #     and any(data["meter"] == "red" for data in (helpslot, api))) or api["10m"] < -30:
        elif all([api["jackpot"] > 80, any(data["meter"] == "red" for data in (helpslot, api))]) or g.get("min10", 0) < -30:
            bet_lvl = "Mid"
        else:
            bet_lvl = "Low"
            
        enriched.append({
            **g,
            "trending": trending,
            "bet_lvl": bet_lvl
        })

    # Filter out Mid/Low if not trending
    # enriched = [g for g in enriched if not ("Low" in g["bet_lvl"] or not g.get("trending"))]
    enriched = [g for g in enriched]
    # enriched = [g for g in enriched]
            
    # Sort by bet level, trending, value, jackpot
    priority = {"Bonus": 4, "High": 3, "Mid": 2, "Low": 1}
    enriched.sort(
        key=lambda g: (
            priority[g["bet_lvl"]],
            0 if (g["bet_lvl"] in ["Bonus", "High"] and not g.get("trending"))
               or (g["bet_lvl"] in ["Mid", "Low"] and g.get("trending")) else 1,
            g["jackpot_value"],
            g["value"]
        ),
        reverse=True
    )
    
    save_trend_memory(enriched)
    return enriched
    
def play_alert(alert_queue, stop_event):
    if platform.system() == "Darwin":
        while not stop_event.is_set():
            try:
                say = alert_queue.get_nowait()
                sound_file = (say)
                
                if sound_file == "ping":
                    subprocess.run(["afplay", PING])
                else:
                    # voice = VOICES["Trinoids"] if ("Bonus" in sound_file or "Trending" in sound_file) else VOICES["Samantha"]
                    voice = VOICES["Trinoids"] if "Bonus" in sound_file else VOICES["Samantha"]
                    sound_file = sound_file.replace("is_trending", "").strip()
                    subprocess.run(["say", "-v", voice, "--", sound_file])
            except Empty:
                time.sleep(0.05)
            except Exception as e:
                print(f"\n\t[Alert Thread Error] {e}")
    else:
        pass

def load_trend_memory():
    if os.path.exists(TREND_FILE):
        with open(TREND_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    return {}

def save_trend_memory(game_data: list):
    data = OrderedDict()
    
    if os.path.exists(TREND_FILE):
        with open(TREND_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f, object_pairs_hook=OrderedDict)
            except json.JSONDecodeError:
                data = OrderedDict()  # fallback if file is empty/corrupted

    # Ensure data is an OrderedDict
    data = OrderedDict(data)
    
    for game in game_data:
        game_name = game.get("name").lower()        
        # Remove old entry if it exists, to reinsert at the front
        if game_name in data:
            data.pop(game_name)
        
        # Insert latest data at the beginning
        data = OrderedDict([(game_name, game)] + list(data.items()))
        
    # Keep only the latest 10 entries
    while len(data) > 10:
        data.popitem(last=True)  # remove oldest entry at the end

    with open(TREND_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    # data = OrderedDict()
    # for game in game_data:
    #     game_name = game.get("name").lower()
    #     data = OrderedDict([(game_name, game)] + list(data.items()))
        
    # with open(TREND_FILE, "w", encoding="utf-8") as f:
    #     json.dump(data, f, ensure_ascii=False, indent=2)
        
    # data = OrderedDict()
    
    # for game in game_data:
    #     game_name = game.get("name", "").lower()
    #     if not game_name:
    #         continue
    #     # data = OrderedDict([(game_name, game)] + list(data.items()))
    #     data[game_name] = game
        
    # # data = sorted(data.items(), key=lambda x: x[0])
        
    # with open(TREND_FILE, "w", encoding="utf-8") as f:
    #     json.dump(data, f, ensure_ascii=False, indent=2)
        
if __name__ == "__main__":
    try:
        stop_event = threading.Event()
        alert_queue = ThQueue()
        alert_thread = threading.Thread(target=play_alert, args=(alert_queue, stop_event), daemon=True)
        alert_thread.start()
        
        if os.path.exists(TREND_FILE):
            os.remove(TREND_FILE)
        
        print(f"{CLEAR}", end="")
        print(render_providers())

        url = next((url for url in URLS if 'helpslot' in url), None)
        provider, provider_name = providers_list()
        alert_queue.put(provider_name)
       
        driver = setup_driver() 
        fetch_html_via_selenium(driver, url, provider)
        last_alerts = {}
        
        while True:
            games = extract_game_data(driver) 
            print(f"\n\tFiltered Games: \n\t{PROVIDERS.get(provider).color}{'\n\t'.join(g['name'] for g in games)}{RES}")
            data = get_game_data_from_local_api(provider, games) if games else None
            # save_trend_memory(data) if data else None
            
            if data:
                games = []
                prev_games = []
                percent = f"{LGRY}%{RES}"
                now = time.time()
                today = time.localtime(now)
                
                print(
                    f"\n\t\t\t\t⏰  {BYEL}{time.strftime('%I', today)}{BWHTE}:{BYEL}{time.strftime('%M', today)}"
                    f"{BWHTE}:{BLYEL}{time.strftime('%S', today)} {LBLU}{time.strftime('%p', today)} "
                    f"{MAG}{time.strftime('%a', today)}{RES}"
                )
                
                for game in data:
                    helpslot, api = make_object(game)
                    clean_name = re.sub(r"\s*\(.*?\)", "", game.get('name'))
                    if "Wild Ape#3258" in clean_name and "PG" in provider:
                        clean_name = clean_name.replace("#3258", "X10000").strip()
                        
                    tag = "💥💥💥 " if game.get('trending') else "🔥🔥🔥 "
                    
                    signal = f"{LRED}⬇{RES}" if api["meter"] == "red" else f"{LGRE}⬆{RES}"
                    colored_value_10m = f"{RED if api["10m"] < 0 else GRE if api["10m"] > 0 else CYN}{' ' + str(api["10m"]) if api["10m"] > 0 else api["10m"]}{RES}"
                    colored_value_1h = f"{RED if api["1h"] < 0 else GRE if api["1h"] > 0 else CYN}{' ' + str(api["1h"]) if api["1h"] > 0 else api["1h"]}{RES}"
                    colored_value_3h = f"{RED if api["3h"] < 0 else GRE if api["3h"] > 0 else CYN}{' ' + str(api["3h"]) if api["3h"] > 0 else api["3h"]}{RES}"
                    colored_value_6h = f"{RED if api["6h"] < 0 else GRE if api["6h"] > 0 else CYN}{' ' + str(api["6h"]) if api["6h"] > 0 else api["6h"]}{RES}"
                    
                    helpslot_signal = f"{LRED}⬇{RES}" if helpslot["meter"] == "red" else f"{LGRE}⬆{RES}"
                    colored_value_10min = f"{RED if helpslot["10m"] < 0 else GRE if helpslot["10m"] > 0 else CYN}{' ' + str(helpslot["10m"]) if helpslot["10m"] > 0 else helpslot["10m"]}{RES}"
                    colored_value_1hr = f"{RED if helpslot["1h"] < 0 else GRE if helpslot["1h"] > 0 else CYN}{' ' + str(helpslot["1h"]) if helpslot["1h"] > 0 else helpslot["1h"]}{RES}"
                    colored_value_3hrs = f"{RED if helpslot["3h"] < 0 else GRE if helpslot["3h"] > 0 else CYN}{' ' + str(helpslot["3h"]) if helpslot["3h"] > 0 else helpslot["3h"]}{RES}"
                    colored_value_6hrs = f"{RED if helpslot["6h"] < 0 else GRE if helpslot["6h"] > 0 else CYN}{' ' + str(helpslot["6h"]) if helpslot["6h"] > 0 else helpslot["6h"]}{RES}"
                    
                    bet_str = f"{BLNK if game.get('bet_lvl') != 'Low' else ''}💰 {BLU if game.get('bet_lvl') in [ 'Mid', 'Low' ] else BLYEL if game.get('bet_lvl') == 'Bonus' else BGRE}{game.get('bet_lvl').upper()}{RES} "
                    
                    print(
                        f"\n\t{tag} {BMAG}{clean_name} {bet_str}{RES}{DGRY}→ {signal} "
                        f"{RED if not game.get('up') else GRE}{game.get('value')}{RES}{percent} "
                        f"({helpslot_signal} {RED if game.get('meter_color') == 'red' else GRE}{game.get('jackpot_value')}{RES}{percent} {DGRY}Helpslot{RES})"
                    )
                    print(f"\t\t{CYN}⏱{RES} {LYEL}10m{RES}:{colored_value_10m}{percent}  {CYN}⏱{RES} {LYEL}1h{RES}:{colored_value_1h}{percent}  {CYN}⏱{RES} {LYEL}3h{RES}:{colored_value_3h}{percent}  {CYN}⏱{RES} {LYEL}6h{RES}:{colored_value_6h}{percent}")
                    print(f"\t\t{CYN}⏱{RES} {LYEL}10m{RES}:{colored_value_10min}{percent}  {CYN}⏱{RES} {LYEL}1h{RES}:{colored_value_1hr}{percent}  {CYN}⏱{RES} {LYEL}3h{RES}:{colored_value_3hrs}{percent}  {CYN}⏱{RES} {LYEL}6h{RES}:{colored_value_6hrs}{percent} {DGRY}Helpslot{RES})")
                    
                    games = list(load_trend_memory().keys())
                    if games != prev_games:
                        prev_games = games.copy()
                        
                    if game.get('bet_lvl') == 'Bonus' or (game.get('bet_lvl') == 'High' and game.get('trending')):
                        if game.get("name", "").lower() in games:
                            alert_queue.put(
                                f"{clean_name} {game.get('bet_lvl')} {game.get('value')}" if game.get("bet_lvl") == "Bonus"
                                else f"{clean_name} is_trending" if game.get("trending")
                                else clean_name
                            )
                        else:
                            break
                    # if clean_name not in last_alerts or now - last_alerts[clean_name] > alert_cooldown:
                    #     if game.get('bet_lvl') == 'Bonus' or (game.get('bet_lvl') == 'High' and game.get('trending')):
                    #         last_alerts[clean_name] = now
                        # if game.get("name", "").lower() in list(load_trend_memory().keys()):
                        #     if game.get('bet_lvl') == 'Bonus' or (game.get('bet_lvl') in [ 'High', 'Mid' ] and game.get('trending')):
                        #         alert_queue.put(
                        #             f"{clean_name} {game.get('bet_lvl')} {game.get('value')}" if game.get("bet_lvl") == "Bonus"
                        #             else f"{clean_name} is_trending" if game.get("trending")
                        #             else clean_name
                        #         )
                print("\n")
            else:                    
                text = f"\n\t🚫 {BDGRY}No Trending Games Found !{RES}"
                
                # if load_trend_memory():
                #     text += f"\n\t\tLast Trending Games:\n\t\t{WHTE}{'\n\t\t'.join(load_trend_memory().keys()).title()}{RES}\n"
                    
                print(f"\r{text}")
                alert_queue.put("No Trending Games Found")
                # sys.stdout.flush()

            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n\n\t🤖❌  {BLRED}Main program interrupted.{RES}")
        stop_event.set()
        
    driver.quit()
    