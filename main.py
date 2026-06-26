#!/usr/bin/env .venv/bin/python

import time
import json
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

# =========================
# CONFIG
# =========================
BASE_URL = "https://api.okbet.com"
ENDPOINT = "/api/front/gamePortal/recordResultList/lg"


# =========================
# DRIVER SETUP
# =========================
def create_driver():
    options = Options()

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    driver = webdriver.Chrome(options=options)
    return driver


# =========================
# TOKEN EXTRACTION (ROBUST)
# =========================
def extract_token(driver):

    # dump storage
    storage = driver.execute_script("""
        let items = {};
        for (let i = 0; i < localStorage.length; i++) {
            let k = localStorage.key(i);
            items[k] = localStorage.getItem(k);
        }
        return items;
    """)

    print("📦 storage dump:", storage)

    import json

    # 🔥 try parsing JSON values properly
    for k, v in storage.items():
        try:
            parsed = json.loads(v)

            # deep search
            if isinstance(parsed, dict):
                for kk, vv in parsed.items():
                    if "token" in kk.lower() and isinstance(vv, str):
                        return vv

                    # nested object
                    if isinstance(vv, dict):
                        for kkk, vvv in vv.items():
                            if "token" in kkk.lower() and isinstance(vvv, str):
                                return vvv

        except:
            pass

    # cookies fallback
    cookies = driver.get_cookies()
    print("🍪 cookies:", cookies)

    for c in cookies:
        if "token" in c["name"].lower():
            return c["value"]

    return None


# =========================
# LOGIN FLOW
# =========================
def login_and_get_token():
    driver = create_driver()

    driver.get("https://okbet.com")

    print("⏳ waiting for site to load...")

    WebDriverWait(driver, 120).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

    print("🔎 extracting token...")

    token = None
    timeout = time.time() + 120

    while time.time() < timeout:
        token = extract_token(driver)

        if token:
            print("✅ TOKEN FOUND")
            print(token[:30], "...")
            return driver, token

        print("⏳ token not ready yet, retrying...")
        time.sleep(3)

    driver.quit()
    raise Exception("❌ Token not found after waiting")


# =========================
# API CALL
# =========================
def call_api(token):
    headers = {
        "accept": "application/json, text/plain, */*",
        "x-lang": "en",
        "x-session-platform-code": "casino_plat",
        "x-version": "v_25_9_16",
        "x-session-token": token,
    }

    url = BASE_URL + ENDPOINT

    r = requests.get(url, headers=headers)
    return r.json()


# =========================
# MAIN LOOP (AUTO RECOVER)
# =========================
def main():
    driver, token = login_and_get_token()

    while True:
        try:
            res = call_api(token)

            print("📡 API:", res)

            # auto relogin on invalid session
            if isinstance(res, dict) and res.get("code") == 1005:
                print("⚠️ session expired → relogin")

                driver.quit()
                driver, token = login_and_get_token()

            time.sleep(5)

        except Exception as e:
            print("❌ error:", e)
            time.sleep(3)


if __name__ == "__main__":
    main()