#!/usr/bin/env .venv/bin/python


import json, os, platform, re, redis, shutil, time, threading
from monitor import log_message
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
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
URLS_LIST = [url.strip() for url in os.getenv("URLS").split(",") if os.getenv("URLS").strip()]
URLS = {url: url for url in URLS_LIST}
URL_BASE = next((url for url in URLS if 'kbe' in url), None)    

def setup_driver():
    options = Options()

    if platform.system() != "Darwin":
        options.binary_location = "/opt/google/chrome/chrome"
        options.add_argument("--disable-dev-shm-usage")

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(shutil.which("chromedriver"))
    return webdriver.Chrome(service=service, options=options)

# -------------------------
# Fetch HTML via Selenium
# -------------------------
def fetch_html(driver: webdriver.Chrome):
    driver.get(URL_BASE)
    time.sleep(1)

    try:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                "button.src-components-Dialogs-ModalRules-index-module_proceed_putIX"
            ))
        )
        btn.click()
    except Exception:
        pass
    except TimeoutException:
        log_message("info", f"Timeout loading {URL_BASE}")
        driver.execute_script("window.stop();")
    except KeyboardInterrupt:
        log_message("error", f"\n\n\t🤖❌  {colors.get('BLRED')}Main program interrupted.{colors.get('RES')}")
    except Exception as e:
        log_message("error", f"Error loading {URL_BASE}: {e}")

    time.sleep(1)
    return driver.page_source

def virtuoso_scroll(driver):
    scroller = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            By.CSS_SELECTOR,
            "[data-testid='virtuoso-scroller']"
        ))
    )

    # ✅ SAFE: no click, only focus
    driver.execute_script("arguments[0].focus();", scroller)
    time.sleep(0.3)

    actions = ActionChains(driver)

    # simulate real user scroll
    for _ in range(8):
        actions.send_keys(Keys.PAGE_DOWN).perform()
        time.sleep(0.25)

    for _ in range(5):
        actions.send_keys(Keys.ARROW_DOWN).perform()
        time.sleep(0.2)

    actions.send_keys(Keys.END).perform()
    time.sleep(1)

    # force wheel event (Virtuoso listens to this)
    driver.execute_script("""
        const el = document.querySelector('[data-testid="virtuoso-scroller"]');
        if (el) {
            el.dispatchEvent(new WheelEvent('wheel', {deltaY: 900}));
        }
    """)

def fetch_winners_data(driver: webdriver.Chrome):
    last_seen = None

    while not stop_event.is_set():
        container = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "div[class*='RecentlyWins']"
            ))
        )
        try:
            items = container.find_elements(
                By.CSS_SELECTOR,
                "div[class*='ListItem']"
            )

            if not items: continue

            first = items[0]
            text = first.text.strip()

            if not text: continue

            lines = [x.strip() for x in text.split("\n") if x.strip()]

            if len(lines) < 5: continue

            player = lines[0]

            # detect amount (usually last numeric with + or digits)
            amount = ""
            for l in reversed(lines):
                if any(ch.isdigit() for ch in l):
                    amount = l.replace("+", "").replace(",", "")
                    break

            # game name = everything between player and amount
            middle = []
            for l in lines[1:]:
                if l == amount: break
                middle.append(l)

            game_name = " ".join(middle).strip()
                
            bet = ""
            m = re.search(r"Stake\s+([\d,.]+)", game_name)
            if m: bet = m.group(1).replace(",", "")

            game = re.sub(r"\s*Stake.*$", "", game_name).strip()

            current = f"{player}|{game_name}|{amount}"

            if current != last_seen:
                last_seen = current
                # log_message("info", f"🏆 FIRST WINNER {len(lines)} → {player} | {game} | {bet} {amount}")
                winners_data = {
                    "itemName": player,
                    "gameName": game.title(),
                    "betAmount": float(bet),
                    "betMul": str(float(amount)/float(bet)) if bet != "0.00" else "0.00",
                    "payOut": float(amount)
                }
                r.set("winners_data", json.dumps(winners_data))
                # log_message("info", f"🏆 {winners_data}")

        except Exception as e:
            log_message("error", f"🤖❌  {e}")


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
        log_message("info", f"✅ Connected to Redis")
    except redis.exceptions.ConnectionError as e:
        log_message("error", f"🤖❌ Redis connection failed  {e}")
        raise SystemExit(1)

    stop_event = threading.Event()
    driver = setup_driver()
    driver.set_window_size(1920, 3000)
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(2)

    fetch_html(driver)
    virtuoso_scroll(driver)

    fetch_thread = threading.Thread(target=fetch_winners_data, args=(driver,), daemon=True)
    fetch_thread.start()

    try:
        while not stop_event.is_set():
            try:
                stop_event.wait(0.3)
            except Exception as e:
                log_message("error", f"Monitor loop error: {e}")
    except KeyboardInterrupt:
        stop_event.set()
        log_message("error", f"\n\n\t🤖❌  {colors.get('BLRED')}Main program interrupted.{colors.get('RES')}")
    finally:                        
        log_message("warning", f"\n\n\t🤖❌  {colors.get('LYEL')}All threads shut down...{colors.get('RES')}")
        
        stop_event.set()

        if fetch_thread.is_alive(): fetch_thread.join(timeout=3)
        
        driver.quit()

        try:
            r.delete("winners_data")
            r.close()
        except Exception:
            pass