#!/usr/bin/env .venv/bin/python

import json, os, platform, re, redis, shutil, time, threading
from monitor import log_message
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

# -------------------------
# Redis
# -------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# -------------------------
# GAME CACHE (IMPORTANT FIX)
# -------------------------
# GAME_CACHE = {}

# -------------------------
# DRIVER
# -------------------------
def setup_driver():
    options = Options()

    if platform.system() != "Darwin" or os.getenv("IS_DOCKER") == "1":
        options.binary_location = "/opt/google/chrome/chrome"
        options.add_argument("--disable-dev-shm-usage")

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")

    service = Service(shutil.which("chromedriver"))

    return webdriver.Chrome(service=service, options=options)

# -------------------------
# FETCH HTML
# -------------------------
def fetch_html(driver, url: str):
    try:
        driver.get(url)
        time.sleep(1)

        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "van-button--primary"))
        )

        btn.click()
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

# -------------------------
# ICON PARSER (FIXED)
# -------------------------
def get_game_id_from_icon(url: str):
    if not url:
        return None

    url = url.split("?")[0]
    match = re.search(r"/(\d+)\.(?:png|webp|jpg|jpeg)$", url)

    return int(match.group(1)) if match else None

def parse_rtp(item):
    try:
        el = item.find_element(By.CSS_SELECTOR, ".rtp_up")
        rtp = el.find_element(By.CSS_SELECTOR, "span").text.strip().replace("RTP:", "")
        classes = el.get_attribute("class") or ""
        is_on = "on" in classes.split()

        return rtp, is_on

    except:
        return None, False

# -------------------------
# MAIN SCRAPER
# -------------------------
def fetch_rtp_data(driver: webdriver.Chrome):
    while not stop_event.is_set():
        data = {}
        lists = []

        try:
            container = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "realtime_rtp"))
            )

            sections = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, "realtime_rtp_list"))
            )

            if not all([container, sections]): continue

            top = container.find_element(By.CLASS_NAME, "realtime_rtp_top")
            img = top.find_element(By.CSS_SELECTOR, ".common_game_icon img")
            icon_url = img.get_attribute("data-src") or img.get_attribute("src") or ""
            game_id = get_game_id_from_icon(icon_url)
            # log_message("info", f"ICON URL: {icon_url}")
            # log_message("info", f"Top game ID: {game_id}")
            top_rtp, top_rtp_on = parse_rtp(top)
            top_total_bet = top.find_element(By.CSS_SELECTOR, ".total").text.strip()

            if not all([top, img, top_total_bet]): continue

            data["top"] = {
                "game_id": game_id,
                "rtp": top_rtp,
                "up": top_rtp_on,
                "total_bet": top_total_bet
            }

            for section in sections:
                try:
                    title = section.find_element(By.CSS_SELECTOR, ".title").text.strip()
                    items = section.find_elements(By.TAG_NAME, "li")

                    if not all([title, items]): continue

                    games = []

                    for item in items:
                        try:
                            rtp, rtp_on = parse_rtp(item)
                            img = item.find_element(By.CSS_SELECTOR, ".common_game_icon img")

                            if not all([rtp, img]): continue

                            icon = img.get_attribute("data-src") or img.get_attribute("src")
                            game_id = get_game_id_from_icon(icon)

                            games.append({
                                "game_id": game_id,
                                "rtp": rtp,
                                "up": rtp_on
                            })

                        except:
                            continue

                    if games:
                        lists.append({
                            "title": title,
                            "games": games
                        })
                except:
                    continue

            data["lists"] = lists

            # r.set("rtp_data", json.dumps(data))

            if not lists: continue

            # if lists:
            #     # r.set("rtp_data", json.dumps(data))

            #     # log_message("info", f"\nSECTION: {lists[0]['title']}")
            #     # log_message("info", f"\nGAMES: {len(lists[0]['games'])}")
            #     # log_message("info", f"\nLISTS: {lists}")

            #     log_message("info", f"\nDATA: {data}")

            #     # return data

            r.set("rtp_data", json.dumps(data))
            # return data
            driver.refresh()
        except Exception as e:
            log_message("error", f"🤖❌  {e}")

        # except Exception as e:
        #     log_message("error", f"RTP error: {e}")
        #     time.sleep(0.5)


# -------------------------
# MAIN
# -------------------------
if __name__ == "__main__":

    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True
    )

    try:
        r.ping()
        log_message("info", "✅ Connected to Redis")
    except Exception as e:
        log_message("error", f"🤖❌ Redis connection failed  {e}")

    url = "https://www.gperya.com/community/realtime-rtp/"

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

    fetch_thread = threading.Thread(target=fetch_rtp_data, args=(driver,), daemon=True)
    fetch_thread.start()

    prev_game, prev_provider = game, provider

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
                    
                    fetch_thread = threading.Thread(target=fetch_rtp_data, args=(driver,), daemon=True)
                    fetch_thread.start()

                    prev_game, prev_provider = game, provider

                # fetch_rtp_data(driver)
                # driver.refresh()
                # stop_event.wait(0.5)
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
