#!/usr/bin/env .venv/bin/python


import json, os, platform, redis, shutil, time, threading
from monitor import log_message
from decimal import Decimal
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv

load_dotenv()

colors = {}
for key, value in os.environ.items():
    if key.isupper() and not key.startswith("DB_") and not key.startswith("PROVIDER_"):
        colors[key] = value.encode("utf-8").decode("unicode_escape")
        
LOG_LEVEL = os.getenv("LOG_LEVEL")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")


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
def fetch_html(driver: webdriver.Chrome, url: str):
    try:
        driver.get(url)
        time.sleep(1)
        
        accept_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "van-button--primary"))
        )
        
        accept_btn.click()
    except Exception:
        pass
    except TimeoutException:
        log_message(f"Timeout loading {url}")
        driver.execute_script("window.stop();")
    except KeyboardInterrupt:
        raise
    except Exception as e:
        log_message(f"Error loading {url}: {e}")
        
    time.sleep(1)
    return driver.page_source

def fetch_winners_data(driver: webdriver.Chrome) -> list:
    while not stop_event.is_set():
        results = []
        seen = set()  # to avoid duplicates

        try:
            message_list = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.van-list"))
            )
            
            cards = message_list.find_elements(By.CSS_SELECTOR, "div.feed_card")

            if not all([message_list, cards]): continue
            
            for card in cards:
                try:
                    name_elem = card.find_elements(By.CSS_SELECTOR, "div.feed_top div.name")
                    time_elem = card.find_elements(By.CSS_SELECTOR, "div.feed_top div.time")
                    game_elem = card.find_elements(By.CSS_SELECTOR, "div.community_bet div.game_name")
                    bet_elem = card.find_elements(By.CSS_SELECTOR, "div.community_bet div.bet span")

                    if not all([name_elem, time_elem, game_elem, bet_elem]): continue

                    name = name_elem[0].text.strip()
                    win_time = time_elem[0].text.strip()
                    game_name = game_elem[0].text.strip()
                    
                    if "Super Ace 2" in game_name:
                        game_name = game_elem[0].text.strip().replace("2", "II")
                    
                    bet = bet_elem[0].text.strip()
                    multiplier = bet_elem[1].text.strip() if len(bet_elem) > 1 else ""

                    # Skip empty entries
                    if not all([name, win_time, game_name, bet, multiplier]): continue

                    key = (name, win_time, game_name, bet, multiplier)
                    if key not in seen:
                        seen.add(key)
                        results.append({
                            "user": name,
                            "time": win_time,
                            "game": game_name,
                            "bet": bet,
                            "multiplier": multiplier
                        })
                except:
                    continue

                    # Scroll the message list to trigger rendering of more cards
                    # driver.execute_script("arguments[0].scrollTop += 200", message_list)
                    # time.sleep(0.5)  # small delay for JS to render

            if not results: continue

            results = results[:12] # LIMIT TO 12 ITEMS

            # except TimeoutException:
            #     log_message(f"Timeout: Message list did not load in {wait_time} seconds")
            # except Exception as e:
            #     log_message(f"Error fetching HTML: {e}")
            r.set("winners_data", json.dumps(results))
            # log_message("info", results)
            # return results
            driver.refresh()
        except Exception as e:
            log_message("error", f"🤖❌  {e}")

# def fetch_winners_data(driver: webdriver.Chrome, game: dict) -> list:
#     while not stop_event.is_set():
#         cards = driver.find_elements(By.CSS_SELECTOR, "div.feed_card")
        
        
        
#         card = driver.find_element(By.CSS_SELECTOR, ".game-block")
#         try:
#             name = card.find_element(By.CSS_SELECTOR, ".game-title").text.strip()
#             if name != game.get("name"):
#                 return None
                
#             value_text = card.find_element(By.CSS_SELECTOR, ".progress-value").text.strip()
#             value = float(value_text.replace("%", ""))
                
#             progress_bar_elem = card.find_element(By.CSS_SELECTOR, ".progress-bar")
#             bg = progress_bar_elem.value_of_css_property("background-color").lower()
#             up = "red" if "255, 0, 0" in bg else "green"

#             history = {}
#             history_tags = card.find_elements(By.CSS_SELECTOR, ".game-info-list .game-info-item")
            
#             for item in history_tags:
#                 label = item.find_element(By.CSS_SELECTOR, ".game-info-label").text.strip().rstrip(":").replace(" ", "").lower()
#                 period_elem = item.find_element(By.CSS_SELECTOR, ".game-info-value")
#                 period_text = period_elem.text.strip()
#                 period = float(period_text.replace("%", ""))
#                 history[label] = period
                
#                 # if label == "10min":
#                 #     # state.helpslot_10m = period
#                 #     r.set("helpslot_10m", period)
#                 # if label == "1hr":
#                 #     # state.helpslot_1h = period
#                 #     r.set("helpslot_1h", period)
#                 # if label == "3hrs":
#                 #     # state.helpslot_3h = period
#                 #     r.set("helpslot_3h", period)
#                 # if label == "6hrs":
#                 #     state.helpslot_6h = period
#                 #     r.set("helpslot_6h", period)
                
#             winners_data = {
#                 "name": game.get("name"), 
#                 "jackpot_value": value, 
#                 "meter_color": up, 
#                 **history
#             }
#             r.set("winners_data", json.dumps(winners_data))
#         except Exception as e:
#             log_message("error", f"🤖❌  {e}")
            

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
        
        
    url = "https://www.gperya.com/community/new-winners/"
    
    while True:
        try:
            game = json.loads(r.get("game"))
            provider = json.loads(r.get("provider"))
            if game and provider: break
        except Exception as e:
            log_message("error", f"Failed to read monitor data from Redis: {e}")
            time.sleep(0.5)
            
    stop_event = threading.Event()
    
    driver = setup_driver()
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(2)
    
    fetch_html(driver, url)

    fetch_thread = threading.Thread(target=fetch_winners_data, args=(driver,), daemon=True)
    fetch_thread.start()

    prev_game, prev_provider = game, provider

    
    # fetch_thread = threading.Thread(target=fetch_winners_data, args=(driver, game,), daemon=True)
    # fetch_thread.start()
    
    # prev_game, prev_provider, prev_url = game, provider, url
    
    # fetch_thread = threading.Thread(target=fetch_winners_data, args=(driver,), daemon=True)
    # fetch_thread.start()

    try: 
        while not stop_event.is_set():
            try:
                game = json.loads(r.get("game"))
                provider = json.loads(r.get("provider"))
                
                if (game, provider) != (prev_game, prev_provider):
                    print("🔔 Game/Provider changed!")
                    stop_event.set()
                    fetch_thread.join()
                    stop_event.clear()
                    fetch_html(driver, url)
                    
                    fetch_thread = threading.Thread(target=fetch_winners_data, args=(driver,), daemon=True)
                    fetch_thread.start()

                    prev_game, prev_provider = game, provider

                # fetch_winners_data(driver)
                # driver.refresh()
                
                # winners_data_raw = r.get("winners_data")
                # if not winners_data_raw:
                #     time.sleep(0.5)
                #     continue
                
                # winners_data = json.loads(winners_data_raw)
                # for item in winners_data:
                #     log_message("info", item)
                
                # time.sleep(20)
            #     games = fetch_html(driver, url)

            #     for g in games:
            #         log_message("info", g)
        #         game = json.loads(r.get("game"))
        #         provider = json.loads(r.get("provider"))
        #         url = r.get("url")
                
        #         if (game, provider, url) != (prev_game, prev_provider, prev_url):
        #             print("🔔 Game/Provider/URL changed!")
        #             # Stop old threads
        #             stop_event.set()
        #             fetch_thread.join()
        # #             # Reset stop_event for new threads
        #             stop_event.clear()
        # #             # Refresh driver
        #             driver.refresh()
        #             # fetch_html(driver, url)
                    
        #             fetch_thread = threading.Thread(target=fetch_winners_data, args=(driver,), daemon=True)
        #             fetch_thread.start()
                        
        #             prev_game, prev_provider, prev_url = game, provider, url
            except Exception as e:
                log_message("error", f"Monitor loop error: {e}")

            stop_event.wait(0.5)
    except KeyboardInterrupt:
        log_message("error", f"\n\n\t🤖❌  {colors.get('BLRED')}Main program interrupted.{colors.get('RES')}")
    finally:                        
        log_message("warning", f"\n\n\t🤖❌  {colors.get('LYEL')}All threads shut down...{colors.get('RES')}")
        
        stop_event.set()
        if fetch_thread.is_alive():
            fetch_thread.join(timeout=3)
        driver.quit()
        r.close()
        