import requests
from token_manager import token_manager


BASE_URL = "https://api.okbet.com"


def call_api(endpoint: str):
    token = token_manager.get_token()

    if not token:
        raise Exception("No session token available")

    headers = {
        "accept": "application/json, text/plain, */*",
        "x-lang": "en",
        "x-session-platform-code": "casino_plat",
        "x-version": "v_25_9_16",
        "x-session-token": token,
    }

    url = BASE_URL + endpoint
    res = requests.get(url, headers=headers)

    return res.json()


def safe_call(endpoint: str, relogin_func):
    """
    Auto-recovers from:
    - code 1005 (session invalid / other city login)
    """

    result = call_api(endpoint)

    if isinstance(result, dict) and result.get("code") == 1005:
        print("⚠️ Session invalid (1005) → relogging...")

        driver = relogin_func()

        result = call_api(endpoint)

        return result, driver

    return result, None