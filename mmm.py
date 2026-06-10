#!/usr/bin/env .venv/bin/python


import argparse, atexit, hashlib, json, os,  platform, pyautogui, random, re, shutil, subprocess, sys, time, threading#, csv
# import pandas as pd
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from datetime import datetime
# from multiprocessing import Process, Queue as PsQueue
from queue import Queue as ThQueue, Empty
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
#from webdriver_manager.chrome import ChromeDriverManager
from pynput.keyboard import Listener as KeyboardListener, Key, KeyCode
# from pynput.mouse import Listener as MouseListener, Button
# from config import (GAME_CONFIGS, DEFAULT_GAME_CONFIG, TIMEZONE, BREAKOUT_FILE, DATA_FILE, SCREEN_POS, LEFT_SLOT_POS, RIGHT_SLOT_POS, DEFAULT_VOICE, DELAY_RANGE, SPIN_DELAY_RANGE, PROVIDERS, DEFAULT_PROVIDER_PROPS, URLS, CASINOS, 
#                     LRED, LBLU, LCYN, LYEL, LMAG, LGRE, LGRY, RED, MAG, YEL, CYN, BLU, WHTE, BLRED, BLYEL, BLGRE, BLMAG, BLBLU, BLCYN, BYEL, BMAG, BCYN, BWHTE, DGRY, BLNK, CLEAR, RES)
from config import (DEFAULT_GAME_CONFIG, SCREEN_POS, LEFT_SLOT_POS, RIGHT_SLOT_POS, HOLD_DELAY_RANGE, SPIN_DELAY_RANGE, TIMEOUT_DELAY_RANGE, EXECUTION_TIME_RANGE)
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AutoState:
    dual_slots: bool = False
    memory: dict = field(default_factory=dict)
    left_slot: bool = False
    right_slot: bool = False
    spin: bool = False
    auto_spin: bool = True
    turbo: bool = True
    feature: bool = None
    auto_play_menu: bool = False
    widescreen: bool = False
    provider: str = None
    
    auto_mode: bool = False
    # hotkeys: bool = True
    # running: bool = True
    # pressing: bool = False
    # clicking: bool = False
    # current_key: str = None
    # move: bool = False
    # auto_play: bool = False

    bet: int = 0
    bet_lvl: str = None
    last_spin: str = None
    last_trend: str = None
    last_pull_delta: float = 0


@dataclass
class GameSettings:
    sleep_times: dict

def get_sleep_times(auto_play_menu: bool=False):
    return {
        'q': 0.05,  # 20 cps
        'w': 0.02,  # 50 cps
        'e': 0.01,  # 100 cps
        'a': 0.005, # 200 cps
        's': 0.003, # 300 cps
        'd': 0.001,  # 400 cps
    } if not auto_play_menu else {
        'a': 0.005, # 200 cps
        's': 0.003, # 300 cps
        'd': 0.001  # 400 cps
    }

def configure_game(game: str, memory: dict, dual_slots: bool=False, left_slot: bool=False, right_slot: bool=False):
    state.memory = memory
    state.dual_slots = dual_slots
    state.left_slot = left_slot
    state.right_slot = right_slot

    config = GAME_CONFIGS.get(game, DEFAULT_GAME_CONFIG)
    (
        state.spin,
        state.auto_spin,
        state.turbo,
        state.feature,
        state.auto_play_menu,
        state.widescreen,
        state.provider
    ) = config

    return GameSettings(get_sleep_times(state.auto_play_menu))

def setup_driver(session_id: int, game: str):
    options = Options()
    if platform.system() != "Darwin" or os.getenv("IS_DOCKER") == "1": # non-local or docker containers
        options.binary_location = "/opt/google/chrome/chrome"  # Set explicitly
        options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-gpu')
    options.add_argument('--blink-settings=imagesEnabled=false')  # Disable images
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_argument(f"--user-data-dir={os.getcwd()}/chrome_profile_{session_id}")
    options.add_argument(f"--profile-directory=Profile_{game.lower()}")  # optional
    service = Service(shutil.which("chromedriver"))
    # service = Service("/opt/homebrew/bin/geckodriver") # Firefox
    return webdriver.Chrome(service=service, options=options)

def fetch_html_via_selenium(driver: webdriver.Chrome, game: str, url: str, provider: str):
    driver.get(url)
    time.sleep(1)

    search_box = driver.find_element(By.CLASS_NAME, "gameSearch")
    search_box.send_keys(game)

    if provider != "JILI" and "helpslot" in url: # don't include JILI for it's active default
        providers = driver.find_elements(By.CLASS_NAME, "provider-item")

        for provider_elem in providers:
            try:
                text = provider_elem.find_element(By.CLASS_NAME, "text").text.strip()
                if text == provider:
                    provider_elem.click()
                    break
            except:
                continue

    time.sleep(1)
    return driver.page_source

def extract_game_data(html: str, game: str, provider: str):
    game_data = []
    soup = BeautifulSoup(html, "html.parser")
    block = soup.find("div", class_="gameContainer")
    
    if not block:
        return None

    name_tag = block.find("div", class_="gameName")
    
    if not name_tag:
        return None
        
    name_tag_clean = re.sub(r'\s+', '', name_tag.get_text(strip=True).lower())
    game_clean = game.strip().replace(' ', '').lower()

    # print("name_tag_clean >> ", name_tag_clean)
    # print("game_clean >> ", game_clean)

    if game_clean != name_tag_clean:
        return None

    meter_tag = block.find("div", class_="meterBody")
    meter_color = None

    if meter_tag:
        classes = meter_tag.get("class", [])
        if "redMeter" in classes:
            meter_color = "red"
        elif "greenMeter" in classes:
            meter_color = "green"

    history_tags = block.select("div.historyDetails.percentage div")
    min_required_tags = 4 if provider == "PP" else 2

    # if not meter_tag or len(history_tags) < min_required_tags:
    #     return None

    history = {
        "10m": history_tags[0].get_text(strip=True),
        "1h":  history_tags[1].get_text(strip=True)
    }

    if min_required_tags == 4:
        history["3h"] = history_tags[2].get_text(strip=True)
        history["6h"] = history_tags[3].get_text(strip=True)

    if name_tag and meter_tag and len(history_tags) >= min_required_tags:
        game_data.append({
            "name": name_tag.text.strip(),
            "jackpot_meter": meter_tag.text.strip(),
            "color": meter_color,
            "history": history
        })

    return game_data

# def extract_game_data(html: str, game: str, provider: str):
#     game_data = []
#     soup = BeautifulSoup(html, "html.parser")
#     game_blocks = soup.select(".game")

#     for block in game_blocks:
#         name_tag = block.select_one(".gameName")
#         print("Found >> ", name_tag)
#         if not name_tag:
#             continue

#         name_tag_clean = re.sub(r'\s+', '', name_tag.get_text(strip=True).lower())
#         game_clean = game.strip().replace(' ', '').lower()

#         print("name_tag_clean >> ", name_tag_clean)
#         print("game_clean >> ", game_clean)

#         if game_clean != name_tag_clean:
#             continue

#         meter_tag = block.select_one(".meterBody")
#         meter_color = None

#         if meter_tag:
#             classes = meter_tag.get("class", [])
#             if "redMeter" in classes:
#                 meter_color = "red"
#             elif "greenMeter" in classes:
#                 meter_color = "green"

#         history_tags = block.select(".historyDetails.percentage div")
#         min_required_tags = 4 if provider == "PP" else 2

#         history = {
#             "10m": history_tags[0].get_text(strip=True),
#             "1h":  history_tags[1].get_text(strip=True)
#         }

#         if min_required_tags == 4:
#             history["3h"] = history_tags[2].get_text(strip=True)
#             history["6h"] = history_tags[3].get_text(strip=True)

#         if name_tag and meter_tag and history_tags:
#             game_data.append({
#                 "name": name_tag.get_text(strip=True),
#                 "jackpot_meter": meter_tag.get_text(strip=True),
#                 "color": meter_color,
#                 "history": history
#             })

#     return game_data

def load_previous_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_current_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    
    # create_log()

# def create_log():
#     sanitized = re.sub(r'\W+', '_', state.game.strip().lower())
#     output_csv = f"{'helpslot' if 'helpslot' in state.url else 'slimeserveahead'}_{sanitized}_log.csv"

#     raw_data = get_game_info()

#     # if not game_data:
#     #     raise ValueError(f"No data found for game: {game_key}")

#     # # Prepare one row from JSON
#     timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#     value = float(raw_data["jackpot_meter"].strip('%'))

#     history = raw_data.get("history", {})

#     # # Compose CSV row
#     row = {
#         "timestamp": timestamp,
#         "value": value,
#         "5s_change": "",  # No real-time tracking
#         "1m_change": "",  # No real-time tracking
        
#         "10m_change": history.get("10m", ""),
#         "1h_change": history.get("1h", ""),
#         "3h_change": history.get("3h", ""),
#         "6h_change": history.get("6h", ""),
#     }

#     # # Write to CSV
#     fieldnames = ["timestamp", "value", "5s_change", "1m_change", "10m_change", "1h_change", "3h_change", "6h_change"]

#     write_header = not os.path.exists(output_csv)

#     with open(output_csv, "a", newline="") as csvfile:
#         writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
#         if write_header:
#             writer.writeheader()
#         writer.writerow(row)

#     print(f"✅ Wrote data for {raw_data['name']} to {output_csv}")

# def hash_data(data):
#     return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()

def compare_data(prev: dict, current: dict):
    slots = ["left", "right"]
    bet_level = None
    result = None
    bear_score = 0
    percent = f"{LGRY}%{RES}"

    border = f"{'-' * 32}"
    margin_left = len(str(border).expandtabs().strip()) - 2
    padding = margin_left - len(str(PROVIDERS.get(provider).provider).expandtabs().strip()) - 1
    slot_mode = f"{RED}dual{RES}" if state.dual_slots else f"{BLU}left{RES}" if state.left_slot else f"{MAG}right{RES}" if state.right_slot else f"{DGRY}solo{RES}"

    banner = f'''\t♦️  {border}  ♠️
        \t{BCYN}{current['name'].upper()}{RES}
        🃏\t{LGRY}{PROVIDERS.get(provider).provider}{RES}{' ' * padding}🎰
        \t{BLGRE}Slot{RES}: {slot_mode}
        \t{BLGRE}Mode{RES}: {CYN}{'auto' if state.auto_mode else 'manual'}{RES}
        ♣️  {border}  ♥️'''

    current_jackpot = pct(current['jackpot_meter'])
    jackpot_bar = get_jackpot_bar(current_jackpot, current['color'])
    is_breakout = False
    is_breakout_delta = False
    lowest_low = state.memory["lowest_low"]
    lowest_low_delta = state.memory["lowest_low_delta"]

    if prev and 'jackpot_meter' in prev:
        prev_jackpot = pct(prev['jackpot_meter'])
        delta = round(current_jackpot - prev_jackpot, 2)
        colored_delta = f"{LRED}{pct(delta)}{RES}" if delta < 0 else f"{LGRE}{delta}{RES}"
        sign = "+" if delta > 0 else ""
        diff = f"({YEL}Prev{RES}: {prev_jackpot}{percent} {LMAG}Δ{RES}: {sign}{colored_delta}{percent})"

        print(f"\n\n\t\t⏰ {LBLU}{TIMEZONE.strftime('%I:%M %p')}{LGRY} {TIMEZONE.strftime('%a')}{RES}")
        print(f"{banner}")
        print(f"\n\t🎰 {BLMAG}Jackpot Meter{RES}: {BLRED}{current_jackpot}{RES}{percent} {diff} ✅") if current_jackpot < prev_jackpot else \
            print(f"\n\t🎰 {BLMAG}Jackpot Meter{RES}: {current_jackpot}{percent} {diff} ❌")
        print(f"\n\t{jackpot_bar} {BLRED if current_jackpot < prev_jackpot else BLGRE}{current_jackpot}{percent}\n")
    else:
        print(f"\n\n\t\t⏰ {LBLU}{TIMEZONE.strftime('%I:%M %p')}{LGRY} {TIMEZONE.strftime('%a')}{RES}")
        print(f"{banner}")
        print(f"\n\t🎰 {BLMAG}Jackpot Meter{RES}: {current_jackpot}{percent}")
        print(f"\n\t{jackpot_bar} {current_jackpot}{percent}\n")

    for index, (period, value) in enumerate(current['history'].items()):
        old_value = prev['history'].get(period) if prev else None
        colored_value = f"{LRED}{pct(value)}{RES}" if pct(value) < 0 else f"{LGRE}{pct(value)}{RES}"
        diff = ""

        if old_value is not None:
            colored_old_value = f"{LRED}{pct(old_value)}{RES}" if pct(old_value) < 0 else f"{LGRE}{pct(old_value)}{RES}"
            new_num = pct(value)
            old_num = pct(old_value)

            if new_num is not None and old_num is not None:
                delta = round(new_num - old_num, 2)
                colored_delta = f"{LRED}{pct(delta)}{RES}" if delta < 0 else f"{LGRE}{delta}{RES}"
                sign = "+" if delta > 0 else ""
                diff = f"({YEL}Prev{RES}: {colored_old_value}{percent}, {LMAG}Δ{RES}: {sign}{colored_delta}{percent})"

                if new_num < old_num and delta < 0:
                    bear_score += 1

                if index == 0:
                    new_num_10m = new_num
                    old_num_10m = old_num
                    new_delta_10m = delta

                    updated = False

                    if lowest_low == 0 or new_num < lowest_low:
                        lowest_low = round(new_num, 2)
                        state.memory["lowest_low"] = lowest_low
                        is_breakout = True
                        alert_queue.put((None, "break_out"))
                        updated = True

                    if lowest_low_delta == 0 or delta < lowest_low_delta:
                        lowest_low_delta = round(delta, 2)
                        state.memory["lowest_low_delta"] = lowest_low_delta
                        is_breakout_delta = True
                        alert_queue.put((None, "delta_break_out"))
                        updated = True

                    if updated:
                        save_breakout_memory(current['name'], lowest_low, lowest_low_delta)
                elif index == 1 and new_num_10m is not None and old_num_10m is not None and new_delta_10m is not None:
                    h10, h1 = pct(new_num_10m), pct(new_num)
                    ph10, ph1 = pct(old_num_10m), pct(old_num)

                    old_delta_10m = state.last_pull_delta
                    state.last_pull_delta = new_delta_10m
                    new_delta_10m_1h = h10 - h1
                    old_delta_10m_1h = ph10 - ph1

                    delta_shift = new_delta_10m - old_delta_10m
                    delta_shift_analysis = new_delta_10m < old_delta_10m
                    delta_shift_decision = new_delta_10m < 0
                    delta_shift_10m_1h = new_delta_10m_1h - old_delta_10m_1h

                    score = 0
                    trend = list()
                    is_reversal = False

                    # ✅ 1. Check for directional reversal: Strong signal
                    # if (h10 < 0 < h1) or (h10 > 0 > h1):
                    if h10 < 0 < h1 or h10 > 0 > h1:
                        trend.append("Reversal Potential")
                        score += 2

                    # ✅ 2. Sharp shift in pull momentum: Medium-strong signal
                    if abs(delta_shift_10m_1h) > 20:
                        trend.append("Strong Pull Surge")
                        score += 2

                    # ✅ 3. Pull strength weakening: Negative signal
                    if abs(new_delta_10m_1h) < abs(old_delta_10m_1h):
                        trend.append(f"Weakening Pull {LMAG}Δ{RES} 👎")
                        score -= 1
                        bear_score -= 1 if h10 < ph10 and new_delta_10m < 0 else bear_score

                    # ✅ 4. Low jackpot movement but big delta shift: Hidden pressure
                    if abs(current_jackpot - prev_jackpot) < 0.05 and abs(delta_shift_10m_1h) > 15:
                        trend.append(f"Hidden Pull {LGRE}({RES}No Visible/Low Jackpot, High {LMAG}Δ{RES}{LGRE}){RES}")
                        score += 1

                    # ✅ 5. Confirm with consistent bear power
                    if old_delta_10m != 0 and new_delta_10m < old_delta_10m and new_delta_10m < 0 and h10 < ph10:
                        new_delta_10m
                        trend.append("Consistent Bear Pressure")
                        score += 1
                        bear_score += 1 if h10 < ph10 and new_delta_10m < 0 else bear_score
                    elif old_delta_10m!= 0 and new_delta_10m >= old_delta_10m:
                        trend.append("Weak Pull 👎")
                        score -= 1
                        bear_score -= 1 if h10 < ph10 and new_delta_10m < 0 else bear_score

                    # ✅ 6. Very Strong Pull
                    if h10 <= -50 or new_delta_10m <= -50 or delta_shift <= -50 and h10 < ph10:
                        trend.append("Very Strong Bearish Pull")
                        score += 3
                        bear_score += 2 if h10 < ph10 and new_delta_10m < 0 else bear_score

                    # ✅ 7. Reversal
                    if prev['color'] == 'green' and current['color'] == 'red': #and current_jackpot - prev_jackpot
                        trend.append(f"{BLNK}{BLRED}R {WHTE}E {BLBLU}V {BLYEL}E {BLMAG}R {BLGRE}S {LGRY}A {BLCYN}L  🚀🚀{RES}")
                        is_reversal = True
                        score += 2
                        bear_score += 1 if h10 < ph10 and new_delta_10m < 0 else bear_score

                    # ✅ 8. Check for neutralization
                    if not trend:
                        trend.append("Neutral")

                    alert_queue.put((None, "Reversal!")) if is_reversal else None

                    result = {
                        'new_delta_10m': round(new_delta_10m, 2),
                        'old_delta_10m': round(old_delta_10m, 2),
                        'new_delta_10m_1h': round(new_delta_10m_1h, 2),
                        'old_delta_10m_1h': round(old_delta_10m_1h, 2),
                        'delta_shift': round(delta_shift, 2),
                        'delta_shift_analysis': delta_shift_analysis,
                        'delta_shift_decision': delta_shift_decision,
                        'delta_shift_10m_1h': round(delta_shift_10m_1h, 2),
                        'pull_score': score,
                        'pull_trend': trend
                    }

                    if old_delta_10m != 0 and h10 < ph10 and delta_shift_decision:
                        if score >= 7 and h10 <= -50 and new_delta_10m <= -50 and delta_shift <= -50 and delta_shift_10m_1h <= -50:
                            bet_level = "max"
                        elif score >= 5 and h10 <= -20 and new_delta_10m <= -20 and delta_shift <= -20 and delta_shift_10m_1h <= -20:
                            bet_level = "high"
                        elif score >= 2:
                            bet_level = "mid"
                        elif score >= 0:
                            bet_level = "low"
                        else:
                            bet_level = None

                        # AUTO SPIN
                        if state.auto_mode and bet_level in [ "max", "high" ] and score >= 5:
                            if state.dual_slots:
                                pyautogui.press('space')
                                spin_queue.put((bet_level, None, slots[0]))
                                spin_queue.put((bet_level, None, slots[1]))
                                time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                spin_queue.put((bet_level, None, slots[0]))
                                time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                spin_queue.put((bet_level, None, slots[1]))
                            elif state.left_slot:
                                spin_queue.put((bet_level, None, slots[0]))
                                time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                if score >= 6:
                                    spin_queue.put((bet_level, None, slots[0]))
                                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                if score >= 7:
                                    bet_queue.put((bet_level, True, slots[0]))
                                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                    spin_queue.put((bet_level, None, slots[0]))
                                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                if score >= 8:
                                    bet_queue.put((bet_level, True, slots[0]))
                                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                    spin_queue.put((bet_level, None, slots[0]))
                            elif state.right_slot:
                                spin_queue.put((bet_level, None, slots[1]))
                                time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                if score >= 6:
                                    spin_queue.put((bet_level, None, slots[1]))
                                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                if score >= 7:
                                    bet_queue.put((bet_level, True, slots[1]))
                                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                    spin_queue.put((bet_level, None, slots[1]))
                                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                if score >= 8:
                                    bet_queue.put((bet_level, True, slots[1]))
                                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                    spin_queue.put((bet_level, None, slots[1]))
                            else:
                                # pyautogui.press('space')
                                # time.sleep(3)
                                # spin(bet_level=bet_level, chosen_spin=None)
                                spin_queue.put((bet_level, None, None))
                        elif score < 5 and state.auto_mode:
                            if state.dual_slots:
                                bet_queue.put((bet_level, True, slots[0]))
                                time.sleep(random.randint(*SPIN_DELAY_RANGE))
                                bet_queue.put((bet_level, True, slots[1]))
                            elif state.left_slot:
                                bet_queue.put((bet_level, True, slots[0]))
                            elif state.right_slot:
                                bet_queue.put((bet_level, True, slots[1]))

        print(f"\t{CYN}⏱{RES} {LYEL}{period}{RES}:  {colored_value}{percent} {diff}") if period == "10m" and pct(value) >= 0 else \
            print(f"\t{CYN}⏱{RES} {LYEL}{period}{RES}: {colored_value}{percent} {diff}") if period == "10m" and pct(value) < 0 else \
            print(f"\t{CYN}⏱{RES} {LYEL}{period}{RES}:   {colored_value}{percent} {diff}") if pct(value) >= 0 else \
            print(f"\t{CYN}⏱{RES} {LYEL}{period}{RES}:  {colored_value}{percent} {diff}")

    print(f"\n\t🐻 Bear Score: {BWHTE}{bear_score}{RES}")
    if bear_score >= 2:
        print("\n\t✅ Bearish Momentum Detected")
    else:
        print("\n\t❌ Not Enough Bearish Momentum")

    if result is not None:
        pull_score = result.get('pull_score', 0)

        if pull_score >= 8 and bet_level == "max":
            trend_strength = "💥💥💥 Extreme Pull"
        elif pull_score >= 7 and bet_level in [ "max", "high" ]:
            trend_strength = "🔥🔥 Intense Pull"
        elif pull_score >= 6 and bet_level in [ "max", "high" ]:
            trend_strength = "☄️ Very Strong Pull"
        elif pull_score >= 5:
            trend_strength = "🔴 Stronger Pull"
        elif pull_score >= 4:
            trend_strength = "🟠 Strong Pull"
        elif pull_score >= 2:
            trend_strength = "🟡 Moderate Pull"
        elif pull_score >= 1:
            trend_strength = "🌀 Weak Pull"
        elif pull_score >= 0:
            trend_strength = "🌀 Neutral"
        else:
            trend_strength = "❓ Invalid"

        print(f"\n\t💤 Pull Score: {BLCYN}{trend_strength}{RES} [ {BMAG}{pull_score}{RES} ]")
        state.last_trend = f"{re.sub(r'[^\x00-\x7F]+', '', trend_strength)} Score {pull_score}"
        alert_queue.put((None, "pull_trend_score")) if state.last_trend is not None else None

        for idx, pull_trend in enumerate(result.get('pull_trend')):
            print("\n\t💤 Pull Trend: ") if idx == 0 else None
            print(f"\t\t{BWHTE}{pull_trend}{RES}") if pull_trend else None

        print(f"\n\t🧪 Delta{LMAG}Δ{RES} Shift: {BLRED}{result.get('delta_shift')}{RES}") if result.get('delta_shift') < 0 else \
            print(f"\n\t🧪 Delta{LMAG}Δ{RES} Shift: {result.get('delta_shift')}")
        print(f"\t🧪 Delta{LMAG}Δ{RES} Shift ({LGRY}Analysis{RES}): ✅") if result.get('delta_shift_analysis') else \
            print(f"\t🧪 Delta{LMAG}Δ{RES} Shift ({LGRY}Analysis{RES}): ❌")
        print(f"\t🧪 Delta{LMAG}Δ{RES} Shift ({LGRY}Decision{RES}): ✅") if result.get('delta_shift_decision') else \
            print(f"\t🧪 Delta{LMAG}Δ{RES} Shift ({LGRY}Decision{RES}): ❌")
            
        print(f"\n\t🧪 Delta{LMAG}Δ{RES} Shift ({LGRY}10m_1h{RES}): {BLRED}{result.get('delta_shift_10m_1h')}{RES}") if result.get('delta_shift_10m_1h') < 0 else \
            print(f"\n\t🧪 Delta{LMAG}Δ{RES} Shift ({LGRY}10m_1h{RES}): {result.get('delta_shift_10m_1h')}")
        print(f"\t🧪 Delta{LMAG}Δ{RES} Shift ({LGRY}Decision 10m_1h{RES}): ✅") if result.get('delta_shift_10m_1h') <= -20 else \
            print(f"\t🧪 Delta{LMAG}Δ{RES} Shift ({LGRY}Decision 10m_1h{RES}: ❌")
        
        print(f"\n\t🧲 Delta{LMAG}Δ{RES} Pull Power ({LGRY}Current 10m{RES}): {BLRED}{result.get('new_delta_10m')}{RES}") if result.get('new_delta_10m') < 0 else \
            print(f"\n\t🧲 Delta{LMAG}Δ{RES} Pull Power ({LGRY}Current 10m{RES}): {result.get('new_delta_10m')}")
        print(f"\t🧲 Delta{LMAG}Δ{RES} Pull Power ({LGRY}Prev 10m{RES}): {BLRED}{result.get('old_delta_10m')}{RES}") if result.get('old_delta_10m') < 0 else \
            print(f"\t🧲 Delta{LMAG}Δ{RES} Pull Power ({LGRY}Prev 10m{RES}): {result.get('old_delta_10m')}")

        print(f"\n\t📊 Delta{LMAG}Δ{RES} Trend Change Power ({LGRY}Current 10m_1h{RES}): {BLRED}{result.get('new_delta_10m_1h')}{RES}") if result.get('new_delta_10m_1h') < 0 else \
            print(f"\n\t📊 Delta{LMAG}Δ{RES} Trend Change Power ({LGRY}Current 10m_1h{RES}): {result.get('new_delta_10m_1h')}")
        print(f"\t📊 Delta{LMAG}Δ{RES} Trend Change Power ({LGRY}Previous 10m_1h{RES}): {BLRED}{result.get('old_delta_10m_1h')}{RES}") if result.get('old_delta_10m_1h') < 0 else \
            print(f"\t📊 Delta{LMAG}Δ{RES} Trend Change Power ({LGRY}Previous 10m_1h{RES}): {result.get('old_delta_10m_1h')}{RES}")
        
        print(f"\n\t⚡ Break Out: {BLRED}{lowest_low}{RES}{percent} {"✅" if is_breakout else "❌"}") if lowest_low < 0 else \
            print(f"\n\t⚡ Break Out: {lowest_low}{percent} {"✅" if is_breakout else "❌"}")
        print(f"\t⚡ Break Out Delta{LMAG}Δ{RES}: {BLRED}{lowest_low_delta}{RES}{percent} {"✅" if is_breakout_delta else "❌"}") if lowest_low_delta < 0 else \
            print(f"\t⚡ Break Out Delta{LMAG}Δ{RES}: {lowest_low_delta}{percent} {"✅" if is_breakout_delta else "❌"}")
        
    alert_queue.put((bet_level, None))
    # alert_queue.put((None, game)) if bet_level is not None else None
    state.bet_lvl = bet_level
    state.last_spin = None
    state.last_trend = None

    print(f"\n\t\t{'💰' if current['color'] == 'red' else '⚠️'}  {LYEL}Bet [{RES} {(BLNK) + (LRED if current['color'] == 'red' else LBLU)}{bet_level.upper()}{RES} {LYEL}]{RES}\n\n") if bet_level is not None else \
        print("\n\t\t🚫  Don't Bet!  🚫\n\n")
    
    # countdown_thread = threading.Thread(target=countdown_timer, args=(bet_level,59, stop_event,), daemon=True)
    # countdown_queue.put((bet_level, 59, stop_event))
    # threading.Thread(target=countdown_timer, args=(bet_level,59), daemon=True).start()
    
    # if bet_level is not None:
    #     print(f"\n\t>>> Bet [ {BLYEL}{bet_level.upper()}{RES} ]\n\n")
    #     countdown_thread = threading.Thread(target=countdown_timer, args=(59,), daemon=True)
    #     countdown_thread.start()
    # else:
    #     print(f"\n\t❌ Don't Bet! ❌\n")
    # print('\t[2] - BET_LEVEL << ', bet_level)
    # alert_queue.put((bet_level, None))
    # state.last_spin = None
    # state.last_trend = None

def get_jackpot_bar(percentage: float, color: str, bar_length: int=20) -> str:
    filled_blocks = round((percentage / 100) * bar_length)
    empty_blocks = bar_length - filled_blocks
    filled_bar = '🟩' if color == 'green' else '🟥'
    empty_bar = '⬛'
    color_code = LGRE if color == 'green' else LRED

    return f"{color_code}{filled_bar * filled_blocks}{RES}{empty_bar * empty_blocks}"

def pct(p): return float(p.strip('%')) if isinstance(p, str) and '%' in p else float(p)

def load_breakout_memory(game: str):
    today = TIMEZONE.strftime("%Y-%m-%d")
    if os.path.exists(BREAKOUT_FILE):
        with open(BREAKOUT_FILE, 'r') as f:
            data = json.load(f)
            day_data = data.get(today, {})
            return day_data.get(game.lower(), {"lowest_low": 0, "lowest_low_delta": 0})
    return {"lowest_low": 0, "lowest_low_delta": 0}

def save_breakout_memory(game: str, lowest_low: float, lowest_low_delta: float):
    today = TIMEZONE.strftime("%Y-%m-%d")
    data = {}

    if os.path.exists(BREAKOUT_FILE):
        with open(BREAKOUT_FILE, 'r') as f:
            data = json.load(f)

    if today not in data:
        data[today] = {}

    data[today][game.lower()] = {
        "lowest_low": lowest_low,
        "lowest_low_delta": lowest_low_delta
    }

    with open(BREAKOUT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def play_alert(bet_level: str=None, say: str=None):
    if platform.system() == "Darwin":
        while True:
            try:
                bet_level, say = alert_queue.get(timeout=10)

                sound_map = {
                    "max": "bet max",
                    "high": "bet high",
                    "mid": "bet mid",
                    "low": "bet low",
                    None: "do not bet"
                }

                sound_file = (
                    "break_out" if say is not None and say == "break_out" else \
                    f"{state.last_trend}" if say is not None and say == "pull_trend_score" else \
                    f"{state.last_spin}" if say is not None and say == "spin_type" else \
                    "auto mode disabled" if say is not None and say == "auto mode DISABLED" else \
                    "auto mode enabled" if say is not None and say == "auto mode ENABLED" else \
                    "hotkeys disabled" if say is not None and say == "hotkeys DISABLED" else \
                    "hotkeys enabled" if say is not None and say == "hotkeys ENABLED" else \
                    "turbo mode on" if say is not None and say == "turbo mode ON" else \
                    "normal speed on" if say is not None and say == "normal speed ON" else \
                    f"{say}" if say is not None else \
                    sound_map.get(bet_level)
                )

                # voices = [ "Trinoids", "Kanya", "Karen", "Kathy", "Nora" ]
                # voice = random.choice(voices) if not state.last_trend else DEFAULT_VOICE
                if casino == "JLJL9":
                    voice = DEFAULT_VOICE
                elif casino == "Bingo Plus":
                    voice = "Trinoids"
                elif casino == "Casino Plus":
                    voice = "Kathy"
                elif casino == "Rollem 88":
                    voice = "Karen"
                else:
                    voice = "Nora"
                subprocess.run(["say", "-v", voice, sound_file])
            except Empty:
                continue
            except Exception as e:
                print(f"\n\t[Alert Thread Error] {e}")
    else:
        pass

def countdown_timer(stop_event: threading.Event, reset_event: threading.Event, countdown_queue: ThQueue, seconds: int = 60):
    time_left = seconds
    
    while not stop_event.is_set():
        # print(f"[Timer] Time left: {time_left}s")
        mins, secs = divmod(time_left, 60)
        text = "Betting Ends In" if state.bet_lvl is not None else "Waiting For Next Iteration"
        timer = f"\t⏳ {text}: {BLYEL}{mins:02d}{BLNK}{BWHTE}:{RES}{BLYEL}{secs:02d}{RES}  [ {CYN}{game}{RES} ]"
        if reset_event.is_set():
            time_left = seconds
            mins, secs = divmod(time_left, 60)
            text = "Betting Ends In" if state.bet_lvl is not None else "Waiting For Next Iteration"
            timer = f"\t⏳ {text}: {BLYEL}{mins:02d}{BLNK}{BWHTE}:{RES}{BLYEL}{secs:02d}{RES}  [ {CYN}{game}{RES} ]"
            reset_event.clear()

        # if time_left <= 5:
        #     alert_queue.put((None, "5 seconds remaining")) if time_left == 5 else None
        #     timer = f"\t⏳ {text}: {BWHTE}... {BLNK}{BLRED}{secs}{RES}"

        if time_left <= 0:
            countdown_queue.put("Timeout")
            break

        # Overwrite the current terminal line
        # sys.stdout.write(f"\r{timer.ljust(80)}")
        # sys.stdout.flush()
        # time.sleep(1)
        # seconds -= 1

        # print(f"{time_left:02d}")
        # sys.stdout.write(f"\r{str(time_left).ljust(80)}")
        # sys.stdout.flush()
        # print(f"[Timer] Time left: {secs}s")
        # print(f"[Timer] Time left: {time_left}s")
        countdown_queue.put(time_left)  # Optional: publish time remaining
        time.sleep(1)
        time_left -= 1
        # print(f"[Timer] Time left: {secs}s")
        # text = "Betting Ends In" if state.bet_lvl is not None else "Waiting For Next Iteration"
        # timer = f"\t⏳ {text}: {BLYEL}{mins:02d}{BLNK}{BWHTE}:{RES}{BLYEL}{secs:02d}{RES}  [ {CYN}{game}{RES} ]"
        sys.stdout.write(f"\r{timer.ljust(80)}")
        # sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

# def countdown_timer(bet_level: str=None, seconds: int=59, stop_event: threading.Event=None):
#     while True:
#         try:
#             bet_level, seconds, stop_event = countdown_queue.get()

#             while seconds > 0 and not stop_event.is_set():
#                 mins, secs = divmod(seconds, 60)
#                 text = "Betting Ends In" if bet_level is not None else "Waiting For Next Iteration"
#                 if seconds > 5:
#                     timer = f"\t⏳ {text}: {BLYEL}{mins:02d}{BLNK}{BWHTE}:{RES}{BLYEL}{secs:02d}{RES}"
#                 else:
#                     alert_queue.put((None, "5 seconds remaining")) if seconds == 5 else None
#                     timer = f"\t⏳ {text}: {BWHTE}... {BLNK}{BLRED}{secs}{RES}"

#                 timer += f"  [ {CYN}{game}{RES} ]"
#                 # Overwrite the current terminal line
#                 sys.stdout.write(f"\r{timer.ljust(80)}")
#                 sys.stdout.flush()
#                 time.sleep(1)
#                 seconds -= 1
#             # Final clear line
#             sys.stdout.write("\r" + " " * 80 + "\r")
#             sys.stdout.flush()
#         except Empty:
#             continue

def bet_switch(bet_level: str=None, extra_bet: bool=None, slot_position: str=None):
    while True:
        try:
            bet_level, extra_bet, slot_position = bet_queue.get(timeout=10)

            if state.left_slot and slot_position == "left":
                center_x, center_y = LEFT_SLOT_POS.get("center_x"), LEFT_SLOT_POS.get("center_y")
            elif state.right_slot and slot_position == "right":
                center_x, center_y = RIGHT_SLOT_POS.get("center_x"), RIGHT_SLOT_POS.get("center_y")
            else:
                center_x, center_y = SCREEN_POS.get("center_x"), SCREEN_POS.get("center_y")
                # pyautogui.moveTo(x=center_x, y=center_y) if state.auto_mode else None

            cx, cy = center_x, center_y
            x1, x2, y1, y2 = 0, SCREEN_POS.get("right_x"), 0, SCREEN_POS.get("bottom_y")

            if slot_position is not None and state.auto_mode:
                pyautogui.doubleClick(x=cx, y=y2)
                time.sleep(0.5)
                if extra_bet and game.startswith("Fortune Gems"):
                    pyautogui.click(x=cx-228, y=cy-126)
                    pyautogui.doubleClick(x=cx-100, y=cy-126)
                    pyautogui.doubleClick(x=cx-100, y=cy-126)
                else:
                    pyautogui.moveTo(x=cx-100, y=cy-126)
                    
            alert_queue.put((None, "extra_bet")) if extra_bet else None
        except Empty:
            continue

def spin(bet_level: str=None, chosen_spin: str=None, slot_position: str=None):
    while True:
        try:
            bet_level, chosen_spin, slot_position = spin_queue.get(timeout=10)
            spin_types = [ "normal", "board_spin", "board_spin_delay", "board_spin_turbo", "auto_spin", "turbo" ]
            chosen_spin = random.choice(spin_types) if chosen_spin is None else chosen_spin
            # chosen_spin = "normal"
            # bet_values = list()
            # extra_bet = False
            # bet_reset = False
            # lucky_bet_value = 1
            bet = 0

            if state.dual_slots:
                if slot_position == "left":
                    center_x, center_y = LEFT_SLOT_POS.get("center_x"), LEFT_SLOT_POS.get("center_y")
                elif slot_position == "right":
                    center_x, center_y = RIGHT_SLOT_POS.get("center_x"), RIGHT_SLOT_POS.get("center_y")
                time.sleep(1) if state.auto_mode else None
                pyautogui.doubleClick(x=center_x, y=center_y) if state.auto_mode else None
            elif state.left_slot and slot_position == "left":
                center_x, center_y = LEFT_SLOT_POS.get("center_x"), LEFT_SLOT_POS.get("center_y")
                # pyautogui.doubleClick(x=center_x, y=center_y) if state.auto_mode else None
                # time.sleep(0.5)
            elif state.right_slot and slot_position == "right":
                center_x, center_y = RIGHT_SLOT_POS.get("center_x"), RIGHT_SLOT_POS.get("center_y")
                # pyautogui.doubleClick(x=center_x, y=center_y) if state.auto_mode else None
                # time.sleep(0.5)
            else:
                center_x, center_y = SCREEN_POS.get("center_x"), SCREEN_POS.get("center_y")

            cx, cy = center_x, center_y
            x1, x2, y1, y2 = 0, SCREEN_POS.get("right_x"), 0, SCREEN_POS.get("bottom_y")

            if slot_position is not None and not state.dual_slots:
                pyautogui.doubleClick(x=cx, y=y2) if state.auto_mode else None
                time.sleep(2)
            
            # print(f"POSITION during switching slots below coordinates: {slot_position}")
            # print(f"Y-axis (screen_height - 1): {y2}")

            # if is_lucky_bet and bet_level is None:
            #     print('\nDEBUG (SETTING BETS) ...\n')
            #     bet = lucky_bet_value
            # elif bet_level == "max":
            #     bet_values = [ 1, 2, 3, 5 ]
            #     bet = random.choice(bet_values)
            # elif bet_level == "high":
            #     bet_values = [ 1, 2, 3 ]
            #     bet = random.choice(bet_values)
            # elif bet_level == "mid":
            #     bet_values = [ 1, 2 ]
            #     bet = random.choice(bet_values)
            # elif bet_level == "low":
            #     bet_values = [ 1, 2 ]
            #     # bet = random.choice(bet_values)
            #     bet = 1

            # print('\nDEBUG (is_lucky_bet) ', is_lucky_bet)
            # print('DEBUG (bet_level) ', bet_level)
            # print('DEBUG (bet_reset) ', bet_reset)
            # print('\nDEBUG (bet) ', bet)

            # BETS
            # if not is_lucky_bet and not state.dual_slots:
            #     print('\nDEBUG (Changing bets)...\n')
            #     if bet == 1:
            #         pyautogui.click(x=random_x - 190, y=random_y + 325)
            #         pyautogui.click(x=random_x - 50, y=random_y + 250)
            #     elif bet == 2:
            #         pyautogui.click(x=random_x - 190, y=random_y + 325)
            #         pyautogui.click(x=random_x - 50, y=random_y + 150)
            #     elif bet == 3:
            #         pyautogui.click(x=random_x - 190, y=random_y + 325)
            #         pyautogui.click(x=random_x - 50, y=random_y + 50)
            #     elif bet == 5:
            #         pyautogui.click(x=random_x - 190, y=random_y + 325)
            #         pyautogui.click(x=random_x - 50, y=random_y)
                    
            #     time.sleep(1)
                
            if chosen_spin == "normal":  # optimize later for space or click dynamics
                if state.spin:
                    pyautogui.doubleClick(x=cx, y=cy + 315)
                else:
                    pyautogui.press('space')
            elif chosen_spin == "board_spin":  # Click confirm during first board spin    
                if provider in [ "JILI", "FC" ]:
                    pyautogui.click(x=cx, y=cy)
                elif provider in [ "PG", "PP" ]:
                    pyautogui.press('space')
                    time.sleep(random.randint(*SPIN_DELAY_RANGE))
                    pyautogui.click(x=cx, y=cy)
            elif chosen_spin == "board_spin_delay":
                if provider in [ "JILI", "FC" ]:
                    pyautogui.click(x=cx, y=cy)
                elif provider in [ "PG", "PP" ]:
                    pyautogui.press('space')
                    time.sleep(random.randint(*DELAY_RANGE))
                    pyautogui.click(x=cx, y=cy)
            elif chosen_spin == "board_spin_turbo":
                if provider in [ "JILI", "FC" ]:
                    pyautogui.doubleClick(x=cx, y=cy)
                elif provider in [ "PG", "PP" ]:
                    pyautogui.press('space')
                    pyautogui.click(x=cx, y=cy)
            elif chosen_spin == "auto_spin":
                if slot_position is None and state.widescreen and provider == "JILI":
                    pyautogui.doubleClick(x=cx + 380, y=cy + 325)
                else:
                    action = random.choice([
                        lambda: pyautogui.press('space'),
                        lambda: pyautogui.doubleClick(x=cx, y=cy),
                        lambda: pyautogui.click(x=cx, y=cy)
                    ]) if not state.spin else lambda: pyautogui.doubleClick(x=cx, y=cy + 315)
                    action()
            elif chosen_spin == "turbo":
                if slot_position is None and state.widescreen and provider == "JILI":
                    pyautogui.doubleClick(x=cx + 450, y=cy + 325)
                else:
                    action = random.choice([
                        lambda: pyautogui.press('space'),
                        lambda: pyautogui.doubleClick(x=cx, y=cy),
                        lambda: pyautogui.click(x=cx, y=cy)
                    ]) if not state.spin else lambda: pyautogui.doubleClick(x=cx, y=cy + 315)
                    action()
                    
                time.sleep(2)
            
            # BET RESET
            # if bet_reset and not is_lucky_bet:
            #     print('\nDEBUG (BET RESET) ...\n')
            #     pyautogui.click(x=random_x - 190, y=random_y + 325)
            #     pyautogui.click(x=random_x - 50, y=random_y + 250)
            #     time.sleep(1)

            state.last_spin = chosen_spin
            alert_queue.put((None, "spin_type"))

            print(f"\n\t*** {state.last_trend} ***")
            print(f"\tBet: {bet} ({chosen_spin.replace('_', ' ').upper()})\n")
            print(f"\tSlot: {slot_position}\n") if state.dual_slots or state.left_slot or state.right_slot else None
        except Empty:
            continue

# def on_key_press(key):
#     if key == Key.esc:
#         state.running = False
#         os._exit(0)

#     if key == Key.up:
#         state.auto_mode = not state.auto_mode
#         status = "ENABLED" if state.auto_mode else "DISABLED"
#         play_alert(say=f"auto mode {status}")
#         print(f"Auto Mode: {status}")

#     if key == Key.down:
#         state.hotkeys = not state.hotkeys
#         status = "ENABLED" if state.hotkeys else "DISABLED"
#         play_alert(say=f"hotkeys {status}")
#         print(f"Hotkeys: {status}")

#     if key == Key.right:
#         print("Turbo: ON")
#         play_alert(say="turbo mode ON")
#         pyautogui.PAUSE = 0
#         pyautogui.FAILSAFE = False

#     elif key == Key.left:
#         print("Normal Speed: ON")
#         play_alert(say="normal speed ON")
#         pyautogui.PAUSE = 0.1
#         pyautogui.FAILSAFE = True

#     if key == Key.space:
#         if state.spin:
#             state.pressing = True
#             state.current_key = 'space'
#             num_clicks = 1
#             state.move = True
#         else:
#             state.auto_play = False

#     if isinstance(key, KeyCode):
#         if key.char in [ 'q', 'w', 'e', 'a', 's', 'd' ]:
#             state.pressing = True
#             state.current_key = key.char
#             state.move = True if key.char not in [ 'a', 's', 'd' ] and state.turbo else False
#             if not state.auto_play_menu:
#                 num_clicks = { 'q': 20, 'w': 50, 'e': 100, 'a': 200, 's': 300, 'd': 400 }[ key.char ]
#                 state.auto_play = False
#             else:
#                 num_clicks = { 'q': 1, 'w': 1, 'e': 1, 'a': 200, 's': 300, 'd': 400 }[ key.char ]
#                 state.auto_play = False if key.char in [ 'a', 's', 'd' ] and state.turbo else state.auto_play
#         else:
#             state.pressing = True
#             state.current_key = key.char
#             num_clicks = 1
#             if key.char == 'r':
#                 state.move = True
#                 state.auto_play = False
#             elif key.char == 'v' and state.auto_spin:
#                 state.move = True
#                 state.auto_play = False
#             # elif key.char in [ '1', '2', '3' ] and turbo is True:
#             #     move = True
#             elif key.char == 'f' and state.feature:
#                 state.move = True
#                 state.auto_play = False
#             else:
#                 state.auto_play = False
#     elif key in [ Key.tab, Key.shift ]:
#         state.pressing = True
#         state.current_key = 'tab' if key == Key.tab else 'shift'
#         num_clicks = 1
#         state.move = True
#         state.auto_play = False
#     else:
#         return

#     print(f"\nPressed [{ state.current_key }] ---> { num_clicks } {'click' if num_clicks == 1 else 'clicks'}")

# def on_key_release(key):
#     if key == Key.space:
#         if state.spin:
#             state.pressing = False
#             state.current_key = 'space'
#             num_clicks = 1
#             state.move = False
#         else:
#             state.auto_play = False

#     if isinstance(key, KeyCode):
#         state.pressing = False
#         state.current_key = key.char
#         if key.char in [ 'q', 'w', 'e' ] and state.turbo and state.auto_play_menu:
#             state.move = False
#         elif key.char == 'r':
#             state.move = False
#             state.auto_play = False
#         elif key.char == 'v' and state.auto_spin:
#             state.move = False
#             state.auto_play = False
#         # elif key.char in [ '1', '2', '3' ] and turbo is True:
#         #     move = False
#         elif key.char == 'f' and state.feature:
#             state.move = False
#             state.auto_play = False
#         else:
#             state.auto_play = False
#     elif key in [ Key.tab, Key.shift ]:
#         state.pressing = False
#         state.current_key = 'tab' if key == Key.tab else 'shift'
#         state.move = False
#         state.auto_play = False
#     else:
#         return

#     print(f"\nReleased ---> [{ state.current_key }]")

# def set_location(key):
#     x1, x2 = 0, 0
#     y1, y2 = 0, 0

#     random_x = center_x + random.randint(x1, x2)
#     random_y = center_y + random.randint(y1, y2)

#     if key in [ 'r', 'u', 'i', 'o', 'p', 'j', 'k', 'l' 'm', ',', '.', '/' ]: # SLOT SCREEN
#         if state.game == "Fortune Goddess":
#             if key == 'r':
#                 pyautogui.doubleClick(x=random_x, y=random_y)
#         elif state.game == "Lucky Fortunes":
#             if key == 'r':
#                 pyautogui.doubleClick(x=random_x, y=random_y)
#             elif key in [ 'u', 'i', 'o', 'p', 'j', 'k', 'l' 'm', ',', '.', '/' ]:
#                 pyautogui.click(x=random_x, y=random_y)
#         elif state.auto_play_menu:
#             if key == 'r':
#                 pyautogui.moveTo(x=random_x, y=random_y)
#         else:
#             return
#     elif key == 'f' and state.feature: # FEATURE
#         if state.game == "Fortune Goddess":
#             pyautogui.click(x=random_x, y=random_y + 200)
#             pyautogui.doubleClick(x=random_x, y=random_y + 315)
#         elif state.game == "Lucky Fortunes":
#             pyautogui.click(x=random_x, y=random_y + 200)
#             pyautogui.doubleClick(x=random_x, y=random_y + 380)
#         elif state.auto_play_menu:
#             pyautogui.doubleClick(x=random_x - 600, y=random_y - 70)
#     elif key == 'v' and state.auto_spin: # AUTO SPIN
#         if state.game == "Fortune Goddess":
#             pyautogui.click(x=random_x - 150, y=random_y + 290)
#             pyautogui.doubleClick(x=random_x, y=random_y + 315)
#         elif state.game == "Lucky Fortunes":
#             pyautogui.click(x=random_x - 150, y=random_y + 365)
#             pyautogui.doubleClick(x=random_x, y=random_y + 380)
#         elif state.auto_play_menu:
#             pyautogui.click(x=random_x + 445, y=random_y + 455)
#             pyautogui.click(x=random_x, y=random_y + 180)
#     elif key == 'space' and state.spin: # SPIN BUTTON
#         if state.game == "Fortune Goddess":
#             pyautogui.moveTo(x=random_x, y=random_y + 315)
#         elif state.game == "Lucky Fortunes":
#             pyautogui.moveTo(x=random_x, y=random_y + 380)
#     elif key in [ 'tab', 'shift', 'q', 'w', 'e', 'a' ] and state.turbo: # TURBO BUTTON
#         if state.game == "Fortune Goddess":
#             if key == 'tab':
#                 pyautogui.doubleClick(x=random_x - 210, y=random_y + 350)
#             elif key == 'shift':
#                 pyautogui.click(x=random_x - 210, y=random_y + 350)
#             else:
#                 pyautogui.click(x=random_x - 210, y=random_y + 350)
#         elif state.game == "Lucky Fortunes":
#             if key == 'tab':
#                 pyautogui.doubleClick(x=random_x - 210, y=random_y + 415)
#             elif key == 'shift':
#                 pyautogui.click(x=random_x - 210, y=random_y + 415)
#             else:
#                 pyautogui.click(x=random_x - 210, y=random_y + 415)
#         elif state.auto_play_menu:
#             if not state.auto_play:
#                 pyautogui.click(x=random_x + 445, y=random_y + 455)
#                 state.auto_play = True

#             if key == 'q':
#                 pyautogui.click(x=random_x - 250, y=random_y - 120)
#             elif key == 'w':
#                 pyautogui.click(x=random_x - 60, y=random_y - 120)
#             elif key == 'e':
#                 pyautogui.click(x=random_x + 150, y=random_y - 120)

#             pyautogui.moveTo(x=random_x, y=random_y + 180)

# def keyboard(settings):
#     while state.running:
#         if state.hotkeys and state.pressing and state.current_key: #in settings.sleep_times:
#             if state.current_key == 'd':
#                 pyautogui.doubleClick()
#             else:
#                 if not state.move:
#                     pyautogui.click()
#                 # else:
#                 #     set_location(state.current_key)

#             time.sleep(settings.sleep_times.get(state.current_key, 0.001))
#         else:
#             time.sleep(0.001)

# def mouse():
#     while state.running:
#         if state.clicking and state.auto_play:
#             print("[ MOUSE ] Mouse clicked")
#             state.auto_play = False
#         time.sleep(0.02)

# def on_click(x, y, button, pressed):
#     if button == Button.left:
#         state.clicking = pressed

# def start_listeners(settings):
#     threading.Thread(target=keyboard, args=(settings,), daemon=True).start()
#     threading.Thread(target=mouse, daemon=True).start()

#     with KeyboardListener(on_press=on_key_press, on_release=on_key_release) as kb_listener:
#         kb_listener.join()
#         mouse_listener.join()
    # try:
    #     with KeyboardListener(on_press=on_key_press, on_release=on_key_release) as kb_listener:
    #         kb_listener.join()
    #         mouse_listener.join()
    # except KeyboardInterrupt:
    #     print("\n\n[!] Program interrupted by user. Exiting cleanly...\n")

def monitor_game_info(driver: webdriver.Chrome, game: str, provider: str, data_queue: ThQueue):
    previous_hash = None

    while True:
        try:
            html = driver.page_source
            data = extract_game_data(html, game, provider)
            current_info = next((elem for elem in data if elem["name"].lower() == game.lower()), None)

            if current_info:
                current_hash = hashlib.md5(json.dumps(current_info, sort_keys=True).encode()).hexdigest()
                if current_hash != previous_hash:
                    previous_hash = current_hash
                    data_queue.put(current_info)
                    # all_data = load_previous_data()
                    # previous_data = all_data.get(game.lower())
                    # compare_data(previous_data, current_info)
                    # all_data[game.lower()] = current_info
                    # save_current_data(all_data)
                    # previous_hash = current_hash
            else:
                print(f"⚠️  Game '{game}' not found in current HTML")
        except Exception as e:
            print(f"🤖❌  {e}")

        time.sleep(0.5)

from pynput.keyboard import Listener as KeyboardListener, Key
from queue import Queue, Empty
import threading
import time

def game_selector():
    state = {
        "typed": "",
        "selected_idx": None,
        "blinking": True
    }

    command_queue = Queue()

    def blink_loop():
        blink_on = True
        while state["blinking"]:
            try:
                # Try to get new input from queue without blocking
                key_event = command_queue.get_nowait()
                if key_event == "EXIT":
                    state["blinking"] = False
                    break
                elif isinstance(key_event, str):
                    state["typed"] = key_event
            except Empty:
                pass

            print(f"{CLEAR}", end="")
            blink_id = int(state["typed"]) if state["typed"].isdigit() and 1 <= int(state["typed"]) <= len(GAME_CONFIGS) else None
            print(render_games(blink_idx=blink_id, blink_on=blink_on))
            print(f"\n\t{DGRY}>>> Select Game: {WHTE}{state['typed']}{RES}", end='', flush=True)

            blink_on = not blink_on
            time.sleep(0.5)

    def on_input(key):
        typed = state["typed"]
        if key == Key.backspace:
            typed = typed[:-1]
        elif key == Key.esc:
            print("\nCancelled.")
            command_queue.put("EXIT")
            return False
        elif key == Key.enter:
            if typed.isdigit() and 1 <= int(typed) <= len(GAME_CONFIGS):
                state['selected_idx'] = int(typed)
                command_queue.put("EXIT")
                return False
            else:
                typed = ""
        elif hasattr(key, 'char') and key.char and key.char.isdigit():
            typed += key.char

        command_queue.put(typed)

    blink_thread = threading.Thread(target=blink_loop, daemon=True)
    blink_thread.start()

    with KeyboardListener(on_press=on_input) as kb_listener:
        kb_listener.join()

    print(f"{CLEAR}", end="")
    print(render_games())
    if state['selected_idx']:
        game_name = list(GAME_CONFIGS.keys())[state['selected_idx'] - 1]
        print(f"\n\tSelected: {WHTE}{game_name.upper()}{RES}")
        blink_thread.join()
        return game_name
    
def render_games(blink_idx: int=None, blink_on: bool=True):
    print(f"\n\n\t📘 {MAG}SCATTER JACKPOT MONITOR{RES}\n\n")

    games = list(GAME_CONFIGS.items())
    half = (len(games) + 1) // 2
    lines = list()

    for idx, (left_game, left_conf) in enumerate(games[:half], start=1):
        left_color = PROVIDERS.get(left_conf.provider).color
        left_text = " " * len(left_game) if blink_idx == idx and not blink_on else left_game
        left_str = f"[{WHTE}{idx}{RES}] - {left_color}{left_text}{RES}\t"

        right_index = idx - 1 + half
        if right_index < len(games):
            right_game, right_conf = games[right_index]
            right_color = PROVIDERS.get(right_conf.provider).color
            right_text = " " * len(right_game) if blink_idx == right_index + 1 and not blink_on else right_game
            right_str = f"[{WHTE}{right_index + 1:>2}{RES}] - {right_color}{right_text}{RES}"
        else:
            right_str = ""

        lines.append(f"\t{left_str:<50}\t{right_str}")
    return "\n".join(lines)

def parse_args():
    parser = argparse.ArgumentParser(description="Select and monitor a game.")
    parser.add_argument("--game", type=str, required=False, 
        help="Game number (e.g. 3) or name (e.g. 'Book of Ra')")

    return parser.parse_args()


if __name__ == "__main__":
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)

    print(f"{CLEAR}", end="")
    games = list(GAME_CONFIGS.items())

    args = parse_args()
    # game_name = args.game

    # if args.game.isdigit():
    #     choice = int(args.game)
    #     if 1 <= choice <= len(games):
    #         # return games[idx - 1]
    #         game = games[choice - 1][0]
    #     else:
    #         print(f"[Error] Invalid game number: {choice}")
    #         sys.exit(1)
    # else:
    #     # Try to match by name (case-insensitive)
    #     for name in games:
    #         print("name >> ", name[0].strip())#).replace(" ", ""))
    #         if args.game.lower() in name.lower():
    #             game = name
    #     print(f"[Error] Game name not recognized: {args.game}")
    #     sys.exit(1)

    if not args.game:
        if platform.system() != "Darwin":
            game = game_selector()
        else:
            print(render_games())
            while True:
                try:
                    choice = int(input("\n\t🔔 Enter the Game of your choice: "))
                    if 1 <= choice <= len(games):
                        game = games[choice - 1][0]
                        print(f"\n\tSelected: {WHTE}{game}{RES}")
                        break
                    else:
                        print("\t⚠️  Invalid choice. Try again.")
                except ValueError:
                    print("\t⚠️  Please enter a valid number.")

        # print(f"\n\t>>> {RED}Select Source URL{RES} <<<\n")

        # source_urls = list(URLS)

        # for i, url in enumerate(source_urls, start=1):
        #     print(f"\t[{WHITE}{i}{RES}] - {"":>1} {'helpslot' if 'helpslot' in url else 'slimeserveahead'} ({url})")

        # while True:
        #     try:
        #         choice = int(input("\n\tEnter the source URL of your choice: "))
        #         if 1 <= choice <= len(source_urls):
        #             url = source_urls[choice - 1]
        #             print(f"\n\tSelected: {url}")
        #             break
        #         else:
        #             print("\tInvalid choice. Try again.")
        #     except ValueError:
        #         print("\tPlease enter a valid number.")
        
        provider = GAME_CONFIGS.get(game).provider
        url = next((url for url in URLS if 'helpslot' in url), None)

        print(f"\n\n\t{BLNK}{DGRY}🔔 Select Casino{RES}\n")

        casinos = list(CASINOS)

        for i, casino in enumerate(casinos, start=1):
            print(f"\t[{WHTE}{i}{RES}]  - {casino}")

        while True:
            try:
                choice = int(input("\n\t🔔 Enter the Casino of your choice: "))
                if 1 <= choice <= len(casinos):
                    casino = casinos[choice - 1]
                    print(f"\n\tSelected: {WHTE}{casino}{RES}")
                    break
                else:
                    print("\t⚠️  Invalid choice. Try again.")
            except ValueError:
                print("\t⚠️  Please enter a valid number.")

        enable_dual = int(input(f"\n\n\t🔔 Enter number of slots: "))
        dual_slots = True if enable_dual > 1 else False
        left_slot = False
        right_slot = False

        if not dual_slots:
            enable_left = input(f"\n\n\tDo you want to enable {BLU}left slot{RES} ❓ {DGRY}(y/N){RES}: ").strip().lower()
            if enable_left in [ "y", "Y", "yes" ]:
                try:
                    left_slot = True
                except ValueError:
                    print("\t⚠️ Invalid number. Defaulting to disabled.")
                    left_slot = False
            else:
                left_slot = False

            if not left_slot:
                enable_right = input(f"\n\n\tDo you want to enable {MAG}right slot{RES} ❓ {DGRY}(y/N){RES}: ").strip().lower()
                if enable_right in [ "y", "Y", "yes" ]:
                    try:
                        right_slot = True
                    except ValueError:
                        print("\t⚠️ Invalid number. Defaulting to disabled.")
                        right_slot = False
                else:
                    right_slot = False

    print(f"\n\n\t... {WHTE}Starting real-time jackpot monitor.\n\t    Press ({BLMAG}Ctrl+C{RES}{WHTE}) to stop.{RES}\n")
    
    memory = load_breakout_memory(game)

    state = AutoState()
    settings = configure_game(game, memory, dual_slots, left_slot, right_slot)
    
    session_id = 1 if casino == "JLJL9" else 2 if casino == "Bingo Plus" else 3 if casino == "Casino Plus" else 4

    driver = setup_driver(session_id, game)
    atexit.register(driver.quit) if driver else None
    fetch_html_via_selenium(driver, game, url, provider) # Load once at the start

    # # # threading.Thread(target=keyboard, args=(settings,), daemon=True).start()
    # # # threading.Thread(target=mouse, daemon=True).start()
    stop_event = threading.Event()
    reset_event = threading.Event()

    alert_queue = ThQueue()
    bet_queue = ThQueue()
    data_queue = ThQueue()
    countdown_queue = ThQueue()
    spin_queue = ThQueue()
    
    alert_thread = threading.Thread(target=play_alert, daemon=True)
    bet_thread = threading.Thread(target=bet_switch, daemon=True)
    countdown_thread = threading.Thread(target=countdown_timer, args=(stop_event, reset_event, countdown_queue,), daemon=True)
    monitor_thread = threading.Thread(target=monitor_game_info, args=(driver, game, provider, data_queue,), daemon=True)
    spin_thread = threading.Thread(target=spin, daemon=True)

    alert_thread.start()
    bet_thread.start()
    countdown_thread.start()
    monitor_thread.start()
    spin_thread.start()

    try:
        while True:
            try:
                # Wait for new data from monitor thread (max 10s)
                data = data_queue.get(timeout=60)
                alert_queue.put((None, game))
                print("Got matching data from thread:", data)

                # Reset the countdown because data came in
                reset_event.set()

                all_data = load_previous_data()
                previous_data = all_data.get(game.lower())
                compare_data(previous_data, data)
                all_data[game.lower()] = data
                save_current_data(all_data)
            except Empty:
                print("⚠️  No data received in 1 minute.")

            # Handle timeout signal from countdown
            try:
                result = countdown_queue.get_nowait()
                if result == "Timeout":
                    print("Timer expired.")
                    # stop everything if timer expires
                    stop_event.set()
                    break
            except Empty:
                pass  # No timer event
    except KeyboardInterrupt:
        print("\n\t[EXIT] Main program interrupted.")
        stop_event.set()  # Stop the countdown thread
        
    alert_thread.join(timeout=1)
    bet_thread.join(timeout=1)
    countdown_thread.join(timeout=1)
    spin_thread.join(timeout=1)
    monitor_thread.join(timeout=1)
    print("[Main] All threads shut down.")
