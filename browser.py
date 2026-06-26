from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from token_manager import token_manager
import time


def create_driver():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")

    # IMPORTANT: avoid shared Chrome profile to prevent "other cities"
    # options.add_argument("--user-data-dir=...")  ❌ DO NOT reuse profile

    driver = webdriver.Chrome(options=options)
    return driver


def login_and_extract_token():
    driver = create_driver()

    driver.get("https://okbet.com")

    # 👉 WAIT FOR MANUAL OR AUTO LOGIN
    # If automated login, insert steps here

    time.sleep(10)  # replace with explicit waits in real version

    # Extract token (adjust key if needed)
    token = driver.execute_script("""
        return window.localStorage.getItem('x-session-token')
    """)

    if not token:
        driver.quit()
        raise Exception("Token not found in localStorage")

    token_manager.set_token(token)

    print("✅ Token updated:", token[:20], "...")

    return driver