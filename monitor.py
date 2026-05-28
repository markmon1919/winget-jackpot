#!/usr/bin/env .venv/bin/python


import hashlib, json, logging, math, os, platform, pyautogui, random, re, redis, subprocess, sys, time, threading
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from queue import Queue as ThQueue, Empty
from pynput.keyboard import Listener as KeyboardListener, Key, KeyCode
# from trend import load_trend_memory
from config import (HOLD_DELAY_RANGE, SPIN_DELAY_RANGE, TIMEOUT_DELAY_RANGE, EXECUTION_TIME_RANGE)

from config import (DEFAULT_GAME_CONFIG, SCREEN_POS, LEFT_SLOT_POS, RIGHT_SLOT_POS)
from database import db
from dotenv import load_dotenv

load_dotenv()

colors = {}
for key, value in os.environ.items():
    if key.isupper() and not key.startswith("DB_") and not key.startswith("PROVIDER_"):
        colors[key] = value.encode("utf-8").decode("unicode_escape")

LOG_LEVEL = os.getenv("LOG_LEVEL")
API_PORT = os.getenv("API_PORT")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

logger = logging.getLogger("monitor")
logger.setLevel(logging.DEBUG if LOG_LEVEL == "DEBUG" else logging.INFO)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.DEBUG if LOG_LEVEL == "DEBUG" else logging.INFO)

formatter = logging.Formatter("%(message)s")
stream_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(stream_handler)


@dataclass
class AutoState:
    game: dict = None
    provider: str = None
    api_server: str = None
    game_id: int = 0
    slot_size: str = None
    spin_btn: bool = False
    auto_spin: bool = True
    turbo: bool = True
    feature: bool = None
    auto_play_menu: bool = False
    widescreen: bool = False

    auto_mode: bool = False
    fast_mode: bool = False
    dual_slots: bool = False
    split_screen: bool = False
    left_slot: bool = False
    right_slot: bool = False
    # forever_spin: bool = False
    
    # hotkeys: bool = True
    # running: bool = True
    # pressing: bool = False
    # clicking: bool = False
    # current_key: str = None
    # move: bool = False
    # auto_play: bool = False

    breakout: dict = field(default_factory=dict)
    neutralize: bool = False
    is_low_breakout: bool = False
    is_low_delta_breakout: bool = False
    is_high_breakout: bool = False
    is_high_delta_breakout: bool = False
    is_reversal: bool = False
    is_reversal_potential: bool = False
    bet: int = 0
    # bet_lvl: str = None
    extra_bet: bool = False
    last_spin: str = None
    last_trend: str = None
    interval: int = 0
    last_pull_delta: float = 0.0
    pull_delta: float = 0.0
    old_delta: float = 0.0
    # prev_pull_delta: float = 0.0
    prev_pull_score: int = 0
    prev_bear_score: int = 0
    pull_score: int = 0
    bear_score_inc: bool = False
    pull_score_inc: bool = False
    curr_color: str = None
    min10: float = 0.0
    last_min10: float = 0.0
    prev_jackpot_val: float = 0.0
    prev_10m: float = 0.0
    prev_1hr: float = 0.0
    last_slot: str = None
    non_stop: bool = False
    elapsed: int = 0
    last_time: Decimal = Decimal('0')
    current_color: str = None
    api_jackpot_delta: float = 0.0
    api_10m: float = 0.0
    api_1h: float = 0.0
    api_3h: float = 0.0
    new_jackpot_val: float = 0.0
    jackpot_hs_signal: str = None
    # new_data: bool = False
    prev_helpslot_jackpot: float = 0.0
    api_major_pullback: bool = False
    helpslot_jackpot: float = 0.00
    helpslot_meter: str = None
    helpslot_jackpot_delta: float = 0.0
    helpslot_10m: float = 0.0
    helpslot_1h: float = 0.0
    helpslot_3h: float = 0.0
    # helpslot_6h: float = 0.0
    helpslot_major_pullback: bool = False
    extreme_pull: bool = False
    intense_pull: bool = False
    spike: bool = False
    pull_thresh: int = 0
    min10_thresh: int = 0
    last_trigger_sec: int = 0
    api_jackpot: float = 0.0
    api_bullish: bool = False
    predicted_delta_10m: float = 0.0
    wheel_sleep: int = 6
    wheel_secs: float = 0.0
    wheel_mode: bool = False
    quick_spin: bool = False
    slow_mode: bool = False
    scatter_mode: bool = False
    scatter_spin: bool = False
    hs_jackpot: float = 0.0
    last_trigger: str = None
    session_mode: str = None
    hit_win: bool = False
    api_vol: float = 0.0
    api_vol_signal: str = None
    api_vol_static: float = 0.0
    rtp: bool = None
    rtp_val: float = 0.0
    last_rtp: bool = None

    last_users: dict = field(default_factory=dict)
    last_rtp_hash: str = None
    last_winners_hash: str = None
    lock: threading.Lock = field(default_factory=threading.Lock)

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

def configure_game(game: dict, api_server: str, auto_mode: bool=False, fast_mode: bool=False, dual_slots: bool=False, split_screen: bool=False, left_slot: bool=False, right_slot: bool=False):#, forever_spin: bool=False):
    state.game = game
    state.provider = game.get("provider")
    state.api_server = api_server
    state.auto_mode = auto_mode
    state.fast_mode = fast_mode
    state.dual_slots = dual_slots
    state.split_screen = split_screen
    state.left_slot = left_slot
    state.right_slot = right_slot
    # state.forever_spin = forever_spin

    cfg = game.get("config", {})

    state.game_id         = cfg.get("id",              DEFAULT_GAME_CONFIG.id)
    state.slot_size       = cfg.get("slot_size",       DEFAULT_GAME_CONFIG.slot_size)
    state.spin_btn        = cfg.get("spin_btn",        DEFAULT_GAME_CONFIG.spin_btn)
    state.auto_spin       = cfg.get("auto_spin",       DEFAULT_GAME_CONFIG.auto_spin)
    state.turbo           = cfg.get("turbo",           DEFAULT_GAME_CONFIG.turbo)
    state.feature         = cfg.get("feature",         DEFAULT_GAME_CONFIG.feature)
    state.auto_play_menu  = cfg.get("auto_play_menu",  DEFAULT_GAME_CONFIG.auto_play_menu)
    state.widescreen      = cfg.get("widescreen",      DEFAULT_GAME_CONFIG.widescreen) if not state.dual_slots else False

    return GameSettings(get_sleep_times(state.auto_play_menu))
        
def render_providers(providers):
    log_message("info", f"\n\n\t📘 {colors.get('ORA')}SCATTER JACKPOT MONITOR{colors.get('RES')}\n\n")

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
            
def render_games(provider: dict):
    games = list(
        db["GAME"].find(
            {"provider": provider["initial"]},
            {"_id": 0, "name": 1}
        )
    )
    
    trending_games = []
    # # if os.path.exists(TREND_FILE):
    # #     trending_games = [g for g in load_trend_memory().keys()]

    if not games:
        return "\n\t⚠️  No games found\n"

    half = (len(games) + 1) // 2
    lines = []

    for idx, left in enumerate(games[:half], start=1):
        is_blinking = False
        left_color_key = provider.get("color")
        left_color = colors.get(left_color_key, colors.get("RES"))
        left_str = f"[{colors.get('WHTE')}{idx}{colors.get('RES')}] - {left_color}{left['name']}{colors.get('RES')}"
        
        if left["name"].lower() in trending_games:
            left_str = f" {colors.get('LMAG')}{idx}{colors.get('RES')}  - {colors.get('LYEL')}{colors.get('BLNK')}{left} 🔥{colors.get('RES')}"
            is_blinking = True

        right_index = idx - 1 + half
        if right_index < len(games):
            right = games[right_index]
            right_color_key = provider.get("color")
            right_color = colors.get(right_color_key, colors.get("RES"))
            right_str = f"[{colors.get('WHTE')}{right_index + 1}{colors.get('RES')}] - {right_color}{right['name']}{colors.get('RES')}"
        # else:
        #     right_str = "\t"
        
        if right["name"].lower() in trending_games:
            right_str = f" {colors.get('LMAG')}{right_index + 1:>2}{colors.get('RES')}  - {colors.get('LYEL')}{colors.get('BLNK')}{right} 🔥{colors.get('RES')}"

        if is_blinking:
            lines.append(f"\t{left_str:<50}\t\t\t{right_str}")
        else:
            lines.append(f"\t{left_str:<50}\t\t{right_str}")

    return "\n".join(lines)

def games_list(provider: dict):
    games = list(
        db["GAME"].find(
            {"provider": provider["initial"]},
            {"_id": 0, "name": 1, "config": 1, "provider": 1}
        )
    )
    
    while True:
        try:
            choice = int(input("\n\t🔔 Enter the Game of your choice: "))
            if 1 <= choice <= len(games):
                game = games[choice - 1]
                log_message("info", f"\n\tSelected: {colors.get('WHTE')}{game.get("name")}{colors.get('RES')}")
                return game
            else:
                log_message("warning", "\t⚠️  Invalid choice. Try again.")
        except ValueError:
            log_message("warning", "\t⚠️  Please enter a valid number.")

def bet_switch(bet_level: str=None, extra_bet: bool=False):
    try:
        # bet_level, extra_bet, slot_position = bet_queue.get_nowait()

        # # if state.left_slot or slot_position == "left":
        # #     center_x, CENTER_Y = LEFT_SLOT_POS.get("center_x"), LEFT_SLOT_POS.get("center_y")
        # # elif state.right_slot or slot_position == "right":
        # #     center_x, CENTER_Y = RIGHT_SLOT_POS.get("center_x"), RIGHT_SLOT_POS.get("center_y")
        # # else:
        # #     center_x, CENTER_Y = SCREEN_POS.get("center_x"), SCREEN_POS.get("center_y")
        #     # pyautogui.moveTo(x=center_x, y=CENTER_Y) if state.auto_mode else None
        
        if bet_in_progress.is_set():
            sys.stdout.write("\t⚠️  Betting in progress, skipping")
            state.extra_bet = not extra_bet
            return None
            
        bet_in_progress.set()

        cx, cy = CENTER_X, CENTER_Y
        
        action = []
        
        if (
            provider.get("initial") == "JILI"
            and any(n in game.get("name", "") for n in ("Fortune Gems", "Pirate Queen", "Ali Baba", "Neko Fortune"))
        ):
            if state.widescreen:
                action.extend([
                    # pyautogui.click(x=cx-228, y=cy-126)
                    # pyautogui.doubleClick(x=cx-100, y=cy-126)
                    # pyautogui.doubleClick(x=cx-100, y=cy-126)
                ])
            else:
                if "Pirate Queen" in game.get("name"):
                    cy += 60
                if extra_bet:
                    action.extend([
                        pyautogui.click(x=cx-220, y=cy-130),
                        time.sleep(0.5),
                        pyautogui.click(x=cx-60, y=cy-130)
                    ])
                else:
                    action.extend([
                        pyautogui.doubleClick(x=cx-60, y=cy-130),
                        time.sleep(0.5),
                        pyautogui.click(x=cx-220, y=cy-130)
                    ]) 
                
        action()
        
        # if slot_position is not None and state.split_screen:
        #     pyautogui.doubleClick(x=cx, y=by)
        #     time.sleep(1)
        #     # if extra_bet and game.startswith("Fortune Gems"):                    
        #     if (
        #         extra_bet
        #         and provider.get("initial") == "JILI"
        #         and any(n in game.get("name", "") for n in ("Fortune Gems", "Neko Fortune"))
        #     ):
        #         pyautogui.click(x=cx-228, y=cy-126)
        #         pyautogui.doubleClick(x=cx-100, y=cy-126)
        #         pyautogui.doubleClick(x=cx-100, y=cy-126)
        #     else:
        #         pyautogui.moveTo(x=cx-100, y=cy-126)
        # else:
        #     # if extra_bet and game.startswith("Fortune Gems"):
        #     if extra_bet:
        #         if game in "Fortune Gems":
        #             x1, y1 = cx - 550, cy + 215
        #             x2, y2 = cx - 248, cy + 215
        #         elif game in "Neko Fortune":
        #             x1, y1 = cx - 585, cy + 237
        #             x2, y2 = cx - 350, cy + 237
        #         # log_message("info", f"\t\n{BLRED}cx, cy{RES} >> ", cx, cy) Arguments: (735, 478)
        #         pyautogui.click(x=x1, y=y1)
        #         pyautogui.click(x=x2, y=y2)

        # if extra_bet:
        #     state.extra_bet = not state.extra_bet
        #     status = "on" if state.extra_bet else "disabled"
        #     alert_queue.put(f"extra_bet {status}")
        #     log_message("debug", f"\tExtra Bet: {status}")
        # bet_queue.task_done()
    except Exception as e:
        log_message("info", f"\n\t[Alert Thread Error] {e}")
    finally:
        if extra_bet:
            time.sleep(4)
            
        bet_in_progress.clear()
        
        status = "ON" if state.extra_bet else "OFF"
        alert_queue.put(f"extra bet {status}")
            
    #     state.extra_bet = not extra_bet
    #     if extra_bet:
    #         state.extra_bet = False
            # state.extra_bet = not state.extra_bet
            # status = "on" if state.extra_bet else "disabled"
            # alert_queue.put(f"extra_bet {status}")
            # log_message("debug", f"\tExtra Bet: {status}")

def spin(combo_spin: bool = False, scatter_mode: bool = False, turbo_spin: bool = False, scatter_spin: bool = False, wheel_mode: bool = False, quick_spin: bool = False):
    # while not stop_event.is_set():

    if spin_in_progress.is_set() and not scatter_mode and not wheel_mode and not quick_spin:
        # state.last_spin = None
        sys.stdout.write("\t⚠️  Spin still in action, skipping")
        return None
        
    spin_in_progress.set()

    cx, cy, by = CENTER_X, CENTER_Y, BTM_Y

    spin_types = [ "normal_spin", "spin_hold", "board_spin", "board_spin_hold", "board_spin_turbo", "spin_slide", "auto_spin", "turbo_spin", "super_turbo", "spam_spin" ]
    
    spin_type = None

    try:
        # cmd, combo_spin = spin_queue.get_nowait()
        # spin_in_progress, combo_spin = spin_queue.get(timeout=1)
        if not wheel_mode and not quick_spin:
            if "JILI" in provider.get("initial"):
                spin_types = [ s for s in spin_types if not s.startswith("spam") ]
                spin_types.extend([ "max_turbo" ])
            
            if not combo_spin and any(n in provider.get("initial") for n in ("PG", "PP")):
                spin_types = [ s for s in spin_types if not s.startswith("board") ]
                
            # if combo_spin:
            #     spin_types = [ s for s in spin_types if s.startswith("board") ]
            #     spin_types.extend(["combo_spin", "spam_spin"])
                
            if not turbo_spin:
                # spin_types.extend(["turbo_spin", "super_turbo", "spam_spin", "combo_spin"])
                # if scatter_mode:
                #     # spin_types = [ s for s in spin_types if any(x in s for x in ("turbo")) ]
                #     spin_type = "scatter_spin"
                # else:
                spin_types = [s for s in spin_types if not any(x in s for x in ("turbo", "spam", "auto"))]
            
                if not scatter_mode:
                    # if state.fast_mode and random.random() < 0.7:
                    #     spin_types = [ "normal_spin" ]

                    if state.fast_mode:
                        # if random.random() < 0.8:
                        spin_type = "board_spin" if random.random() < 0.4 else "normal_spin"
                        # if random.random() < 0.4:
                        #     spin_type = "board_spin"
                    else:
                        spin_types = [s for s in spin_types if any(x in s for x in ("turbo", "spam", "auto", "board"))]

                        # spin_types = [s for s in spin_types if not any(x in s for x in ("turbo", "spam", "auto"))]

                    if state.hs_jackpot < 5 and random.random() < 0.7:
                        spin_type = "scatter_spin"

            else:
                if state.auto_mode:
                    if random.random() < 0.4:
                        spin_types = [s for s in spin_types if any(x in s for x in ("turbo", "spam", "auto"))]
                    else:
                        spin_types = [s for s in spin_types if not any(x in s for x in ("turbo", "spam"))]

                    if not scatter_mode:
                        # if state.fast_mode and random.random() < 0.7:
                        #     spin_types = [ "normal_spin" ]

                        if state.hs_jackpot < 5 and random.random() < 0.7:
                            spin_type = "scatter_spin"
            
            # if not scatter_mode:
            #     if state.fast_mode and random.random() < 0.7: # 70% no turbo spin
            #         spin_types = [ s for s in spin_types if not any(x in s for x in ("turbo", "spam")) ]
            #         # spin_type = random.choice(spin_types)
            #     # else:
            #     #     spin_type = random.choice(spin_types)
            #     if state.hs_jackpot < 5 and random.random() < 0.7: # 70% scatter spin
            #         spin_type = "scatter_spin"
            # else:
            #     spin_type = random.choice(spin_types) #if not spam_spin else "spam_spin"
            
            # if not state.fast_mode and wait_before_spin:
            #     if random.random() < 0.8: # 80% use normal spin
            #         spin_type = "normal_spin"
            #     else:
            #         spin_type = random.choice(spin_types)
            # else:
            #     spin_type = random.choice(spin_types) #if not spam_spin else "spam_spin"
            
            if "PP" in provider.get("initial"):
                spin_types = [ "normal_spin", "scatter_spin" ]#, "spin_slide" ]
            
            # spin_type = random.choice(spin_types) if not scatter_mode else "scatter_spin"
        else:
            if quick_spin:
                reset_action = []

                if state.widescreen:
                    if provider.get("initial") == "JILI": # Playtime
                        cx += 30
                        cy += 40
                    reset_action.extend([
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'))
                    ])
                else:
                    if game.get("name", "").__contains__("Super Ace"):
                        by -= 80
                    reset_action.extend([
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                        


                        # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right'))
                    ])

                random.choice(reset_action)()
                time.sleep(1)
        
        spin_type = "wheel_spin" if wheel_mode else "scatter_spin" if scatter_mode else spin_type if spin_type is not None else random.choice(spin_types)

        # shrink_percentage = 60 if state.widescreen else 32
        # width = int(max(RIGHT_X, BTM_Y) * (shrink_percentage / 100))
        # height = int(min(RIGHT_X, BTM_Y) * (shrink_percentage / 100))
        # # border_space_top = cy // 3 if state.widescreen else 0
        # radius_x, radius_y = width // 2, height // 2 #if widescreen else width // 2
        # # rand_x = cx + random.randint(-radius_x, radius_x)
        # # rand_y = cy + random.randint(-radius_y, radius_y) + (border_space_top if radius_y <= 0 else -border_space_top)
        # # rand_x2 = cx - random.randint(-radius_x, radius_x)
        # # rand_y2 = cy - random.randint(-radius_y, radius_y) + (border_space_top if radius_y <= 0 else -border_space_top)
        
        # # y_start = 200
        # # y_end = cy
        # y_start = 200
        # y_end = BTM_Y - cy
        
        # if (
        #     provider.get("initial") == "JILI"
        #     and any(n in game.get("name", "") for n in ("Pirate Queen", "Golden Empire"))
        # ):
        #     y_start *= 2
                
        rand_x = cx - random.randint(-radius_x, radius_x)
        rand_y = random.randint(y_start, y_end)
        # mystic = 100
        # cruise_royal = 100
        # queen of bounty = cy

        rand_x2 = cx - random.randint(-radius_x, radius_x)
        rand_y2 = random.randint(y_start, y_end)

        # print(f'\theight >>> {height}')
        # print(f'\tBTM_Y >>> {BTM_Y}')
        # print(f'\tcx >>> {cx}')
        # print(f'\tcy >>> {cy}')
        # print(f'\tradius_x >>> {radius_x}')
        # print(f'\tradius_y >>> {radius_y}')
        # print(f'\trand_x >>> {rand_x}')
        # print(f'\trand_y >>> {rand_y}')
        # print(f'\trand_x2 >>> {rand_x2}')
        # print(f'\trand_y2 >>> {rand_y2}')
        
        action = []
        
        hold_delay = random.uniform(*HOLD_DELAY_RANGE)
        spin_delay = random.uniform(*SPIN_DELAY_RANGE)
        timeout_delay = random.uniform(*TIMEOUT_DELAY_RANGE)
        execution_time = random.uniform(*EXECUTION_TIME_RANGE)
        # print(f'widescreen: {widescreen}')
        # print(f'state.spin_btn: {state.spin_btn}')
        
        if spin_type == "normal_spin":
            if state.widescreen:
                action.extend([
                    lambda: pyautogui.click(x=cx + 520, y=cy + 335, button='left'),
                    lambda: pyautogui.click(x=cx + 520, y=cy + 335, button='right'),
                    lambda: pyautogui.press('space'),
                    # lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                    # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), pyautogui.mouseUp(button='left')),
                    # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), pyautogui.mouseUp(button='right'))
                ])
            else:
                if "PP" in provider.get("initial"):
                    action.extend([
                        lambda: pyautogui.click(x=cx, y=by - 200, button='left'),
                        # lambda: pyautogui.press('space'),
                        # lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                        lambda: (pyautogui.mouseDown(x=cx, y=by - 200, button='left'), pyautogui.mouseUp(button='left'))
                    ])
                else:
                    if game.get("name", "").__contains__("Super Ace"):
                        by -= 80
                    # NO RIGHT CLICK FOR BUTTON IN PG (BUT MOUSEDOWN IS GOOD)
                    action.extend([
                        lambda: pyautogui.click(x=cx, y=by - 100, button='left'),
                        lambda: pyautogui.click(x=cx, y=by - 100, button='right'),
                        # lambda: pyautogui.press('space'),
                        # lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                        lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), pyautogui.mouseUp(button='left')),
                        lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), pyautogui.mouseUp(button='right'))
                    ]) if not state.spin_btn else \
                    action.extend([
                        lambda: pyautogui.click(x=cx, y=by - 100, button='left'),
                        lambda: pyautogui.click(x=cx, y=by - 100, button='right'),
                        # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), pyautogui.mouseUp(button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), pyautogui.mouseUp(button='right'))
                    ])
        elif spin_type == "spin_hold":
            if state.widescreen:
                action.extend([
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                ])
            else:
                if game.get("name", "").__contains__("Super Ace"):
                    by -= 80
                action.extend([
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                ]) if not state.spin_btn else \
                action.extend([
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                ])
        # elif spin_type == "spin_delay":
        #     if state.widescreen:
        #         action.extend([
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='left')),
        #             # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='right')),
        #             # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.keyUp('space')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
        #         ])
        #     else:
        #         action.extend([
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='right')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.keyUp('space')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
        #         ]) if not state.spin_btn else \
        #         action.extend([
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='left')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='right')),
        #             # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
        #         ])
        # elif spin_type == "spin_hold_delay":
        #     if state.widescreen:
        #         action.extend([
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.press('space')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),                       
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),                        
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right'))
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
        #         ])
        #     else:
        #         action.extend([
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.press('space')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),                       
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),                        
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right'))
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
        #         ]) if not state.spin_btn else \
        #         action.extend([
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),                       
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),                        
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right'))
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
        #         ])
        elif spin_type == "board_spin":
            if state.widescreen:
                action.extend([
                    lambda: pyautogui.click(x=rand_x, y=rand_y, button='left'),
                    lambda: pyautogui.click(x=rand_x, y=rand_y, button='right'),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.mouseUp(button='right'))
                ])
            else:
                if game.get("name", "").__contains__("Super Ace"):
                    by -= 80
                action.extend([
                    lambda: pyautogui.click(x=rand_x, y=rand_y, button='left'),
                    lambda: pyautogui.click(x=rand_x, y=rand_y, button='right'),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.mouseUp(button='right')),
                ]) if not state.spin_btn else \
                action.extend([
                    lambda: pyautogui.click(x=rand_x, y=rand_y, button='left'),
                    lambda: pyautogui.click(x=rand_x, y=rand_y, button='right'),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.mouseUp(button='right')),
                ])
        elif spin_type == "board_spin_hold":
            if state.widescreen:
                action.extend([
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'))
                ])
            else:
                if game.get("name", "").__contains__("Super Ace"):
                    by -= 80
                action.extend([
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left'), time.sleep(hold_delay), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(random.uniform(0.05, 0.12)), time.sleep(hold_delay), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(random.uniform(0.05, 0.12)), time.sleep(hold_delay), pyautogui.mouseDown(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(random.uniform(0.05, 0.12)), time.sleep(hold_delay), pyautogui.mouseDown(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left'), time.sleep(hold_delay), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right'), time.sleep(hold_delay), pyautogui.mouseUp(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseUp(button='right'))
                ]) if not state.spin_btn else \
                action.extend([
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left'), time.sleep(hold_delay), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right'), time.sleep(hold_delay), pyautogui.mouseUp(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left'), time.sleep(hold_delay), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right'), time.sleep(hold_delay), pyautogui.mouseUp(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='left'), time.sleep(hold_delay), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(button='right'), time.sleep(hold_delay), pyautogui.mouseUp(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(hold_delay), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(hold_delay), pyautogui.mouseUp(button='right'))
                ])
        # elif spin_type == "board_spin_delay":
        #     if state.widescreen:
        #         action.extend([
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
        #         ])
        #     else:
        #         action.extend([
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
        #         ]) if not state.spin_btn else \
        #         action.extend([
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
        #         ])
        # elif spin_type == "board_spin_hold_delay":
        #     if state.widescreen:
        #         action.extend([
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right'))
        #         ])
        #     else:
        #         action.extend([
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right'))
        #         ]) if not state.spin_btn else \
        #         action.extend([
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
        #             lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right'))
        #         ])
        elif spin_type == "spin_slide":
            if state.widescreen:
                action.extend([
                    # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                    # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp())
                    lambda: (
                        pyautogui.press('space'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12))
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='left') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='left')
                    ),
                    lambda: (
                        pyautogui.press('space'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='right') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='right')
                    ),                    
                    lambda: (
                        pyautogui.click(x=cx + 520, y=cy + 335, button='left'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='left') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='left')
                    ),
                    lambda: (
                        pyautogui.click(x=cx + 520, y=cy + 335, button='left'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='right') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='right')
                    ),
                    lambda: (
                        pyautogui.click(x=cx + 520, y=cy + 335, button='right'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='left') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='left')
                    ),
                    lambda: (
                        pyautogui.click(x=cx + 520, y=cy + 335, button='right'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='right') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='right')
                    )
                ])
            else:
                if game.get("name", "").__contains__("Super Ace"):
                    by -= 80
                action.extend([
                    # lambda: (pyautogui.press('space'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.press('space'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                    # lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                    # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    
                    
                    # lambda: (pyautogui.press('space'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    
                    # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),                    
                    
                    lambda: (
                        pyautogui.press('space'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='left') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='left')
                    ),
                    lambda: (
                        pyautogui.press('space'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='right') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='right')
                    ),
                    lambda: (
                        pyautogui.click(x=cx, y=by - 100, button='left'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='left') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='left')
                    ),
                    lambda: (
                        pyautogui.click(x=cx, y=by - 100, button='left'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='right') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='right')
                    )
                    # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=0.3), pyautogui.mouseUp()),
                    # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                    # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp())
                ]) if not state.spin_btn else \
                action.extend([
                    # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                    # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                    # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp())
                    lambda: (
                        pyautogui.click(x=cx, y=by - 100, button='left'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='left') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='left')
                    ),
                    lambda: (
                        pyautogui.click(x=cx, y=by - 100, button='left'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='right') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='right')
                    ),
                    lambda: (
                        pyautogui.click(x=cx, y=by - 100, button='right'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='left') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='left')
                    ),
                    lambda: (
                        pyautogui.click(x=cx, y=by - 100, button='right'),
                        time.sleep(random.uniform(0.05, 0.12)),
                        (pyautogui.moveTo(x=rand_x, y=rand_y, duration=random.uniform(0.05, 0.12)) 
                            if random.random() < 0.7 else pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        pyautogui.mouseDown(button='right') if random.random() < 0.7 else None,
                        pyautogui.moveTo(x=rand_x2, y=rand_y2, duration=execution_time),
                        pyautogui.mouseUp(button='right')
                    )
                ])
        elif spin_type == "board_spin_turbo":
            if state.widescreen:
                action.extend([
                    lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='left'),
                    lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='right'),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.press('space')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.press('space')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.keyDown('space')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.keyDown('space')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'))
                ])
            else:
                if game.get("name", "").__contains__("Super Ace"):
                    by -= 80
                action.extend([
                    lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='left'),
                    lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='right'),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.press('space')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.press('space')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.keyDown('space')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.keyDown('space')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'))
                ]) if not state.spin_btn else \
                action.extend([
                    lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='left'),
                    lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='right'),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=by - 100, button='right')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'))
                ])
        elif spin_type == "turbo_spin": # add turbo-on + space then board stop and turbo-off soon; also auto_spin + board_stop..etc
            if state.widescreen:
                if provider.get("initial") == "JILI": # Playtime
                    cx += 30
                    cy += 40
                action.extend([
                    lambda: pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left'),
                    lambda: pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right'),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.press('space')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.press('space')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.keyDown('space')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.keyDown('space')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.doubleClick(button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.doubleClick(button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.doubleClick(button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.doubleClick(button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.click(button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.click(button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.click(button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.click(button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.press('space'), pyautogui.press('space')),
                    lambda: (pyautogui.press('space'), pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                    lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.press('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.press('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space'), pyautogui.press('space')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                    lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='right'))
                ])
            else:
                if "PG" in provider.get("initial"):
                    action.extend([
                        lambda: pyautogui.doubleClick(x=cx, y=by - 100, button='left'),
                        # lambda: pyautogui.doubleClick(x=cx, y=by - 100, button='right'),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(button='right')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='right')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        
                        # # TURBO ENABLED
                        # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.press('space'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # # TURBO ENABLED
                        
                        lambda: (pyautogui.press('space'), pyautogui.press('space')),
                        lambda: (pyautogui.press('space'), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='right')),
                        # lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='left')),
                        # lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='right'))
                    ])
                else:
                    if game.get("name", "").__contains__("Super Ace"):
                        by -= 80
                    action.extend([
                        lambda: pyautogui.doubleClick(x=cx, y=by - 100, button='left'),
                        lambda: pyautogui.doubleClick(x=cx, y=by - 100, button='right'),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.press('space')),
                        lambda: (pyautogui.press('space'), pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=by - 100, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.press('space')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space'), pyautogui.press('space')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=by - 100, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='right'))
                    ]) if not state.spin_btn else \
                    action.extend([
                        #
                    ])
        elif spin_type == "super_turbo": # 1 star if JILI
            if state.widescreen:
                if provider.get("initial") == "JILI": # Playtime
                    cx += 30
                    cy += 40
                action.extend([
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    # lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    # lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    # lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    # lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    # lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    # lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    # lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    # lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),                    
                    # auto spin style
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    # spen then turbo
                    lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.click(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'))
                ])
            else:
                if "PG" in provider.get("initial"):
                    action.extend([
                        # TURBO ENABLED
                        lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.press('space'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        # TURBO ENABLED
                        lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='left'))
                    ])
                else:
                    if game.get("name", "").__contains__("Super Ace"):
                        by -= 80
                    action.extend([
                        lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # auto spin style
                        lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'))
                    ]) if not state.spin_btn else \
                    action.extend([
                        #
                    ])
        elif spin_type == "max_turbo": # 2 stars only JILI
            if state.widescreen:
                if provider.get("initial") == "JILI": # Playtime
                    cx += 30
                    cy += 40
                action.extend([
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    # auto spin style
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    # spen then turbo
                    lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
                    lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right'))
                ])
            else:
                if game.get("name", "").__contains__("Super Ace"):
                    by -= 80
                action.extend([
                    lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # auto spin style
                    lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
                    # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right'))
                ])
        elif spin_type == "auto_spin":
            if state.widescreen:
                if provider.get("initial") == "JILI": # Playtime
                    cx += 30
                    cy += 40
                action.extend([
                    lambda: pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'),
                    lambda: pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'),
                    lambda: (pyautogui.click(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 380, y=cy + 325,button='left')),
                    lambda: (pyautogui.click(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 380, y=cy + 325,button='right'))
                ])
            else:
                if "PG" in provider.get("initial"):
                    action.extend([
                        lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='left'), time.sleep(0.3), pyautogui.click(x=cx - 195, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='left'), time.sleep(0.3), pyautogui.click(x=cx - 100, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='left'), time.sleep(0.3), pyautogui.click(x=cx, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='left'), time.sleep(0.3), pyautogui.click(x=cx + 100, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=by - 100, button='left')),
                        lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='left'), time.sleep(0.3), pyautogui.click(x=cx + 195, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='right'), time.sleep(0.3), pyautogui.click(x=cx - 195, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='right'), time.sleep(0.3), pyautogui.click(x=cx - 100, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='right'), time.sleep(0.3), pyautogui.click(x=cx, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='right'), time.sleep(0.3), pyautogui.click(x=cx + 100, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=by - 100, button='left')),
                        # lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='right'), time.sleep(0.3), pyautogui.click(x=cx + 195, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=by - 100, button='left'))
                    ])
                else:
                    if game.get("name", "").__contains__("Super Ace"):
                        by -= 80
                    action.extend([
                        lambda: pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'),
                        lambda: pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'),
                        lambda: (pyautogui.click(x=cx + 95, y=by - 100, button='left'), pyautogui.click(x=cx + 95, y=by - 100, button='left')),
                        lambda: (pyautogui.click(x=cx + 95, y=by - 100, button='right'), pyautogui.click(x=cx + 95, y=by - 100, button='right'))
                    ]) if not state.spin_btn else \
                action.extend([
                    #
                ])
        elif spin_type == "combo_spin":
            action.extend([
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp(button='right')),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp(button='left')),
                    lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp(button='right')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.press('space')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.keyUp('space')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                    # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                    lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                    # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                    # spam
                    lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_y2, y=rand_y2, button='left')),
                    # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_y2, y=rand_y2, button='right')),
                    # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_y2, y=rand_y2, button='left')),
                    # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_y2, y=rand_y2, button='right')),
                    lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_y2, y=rand_y2, button='left')),
                    # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_y2, y=rand_y2, button='right')),
                    # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_y2, y=rand_y2, button='right')),
            ])
        elif spin_type == "spam_spin":
            if provider.get("initial") == "JILI":
                action.extend([
                    lambda: [ pyautogui.typewrite(['space'] * 6, interval=execution_time) for _ in range(3) ],
                    lambda: [ pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=execution_time, button="left") for _ in range(3) ],
                    lambda: [ pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=execution_time, button="right") for _ in range(3) ],
                    lambda: [ pyautogui.click(x=cx, y=by - 100, clicks=6, interval=execution_time, button="left") for _ in range(3) ],
                    lambda: [ pyautogui.click(x=cx, y=by - 100, clicks=6, interval=execution_time, button="right") for _ in range(3) ],
                    lambda: [ pyautogui.doubleClick(x=rand_x, y=rand_y, interval=execution_time, button="left") for _ in range(3) ],
                    lambda: [ pyautogui.doubleClick(x=rand_x, y=rand_y, interval=execution_time, button="right") for _ in range(3) ],
                    lambda: [ pyautogui.doubleClick(x=cx, y=by - 100, interval=execution_time, button="left") for _ in range(3) ],
                    lambda: [ pyautogui.doubleClick(x=cx, y=by - 100, interval=execution_time, button="right") for _ in range(3) ],
                    # lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, clicks=3, interval=execution_time, button="left"),
                    # lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, clicks=3, interval=execution_time, button="right"),
                    # lambda: pyautogui.doubleClick(x=cx, y=by - 100, clicks=3, interval=execution_time, button="left"),
                    # lambda: pyautogui.doubleClick(x=cx, y=by - 100, clicks=3, interval=execution_time, button="right"),
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp(button='left')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp(button='right')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=cx, y=by - 100, button="left"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='left')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=cx, y=by - 100, button="right"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='right')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button="left"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='left')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button="right"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='right')) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=execution_time, button="left"), pyautogui.keyUp('space')) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=execution_time, button="right"), pyautogui.keyUp('space')) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=by - 100, clicks=6, interval=execution_time, button="left"), pyautogui.keyUp('space')) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=by - 100, clicks=6, interval=execution_time, button="right"), pyautogui.keyUp('space')) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=rand_x, y=rand_y, interval=execution_time, button="left"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=rand_x, y=rand_y, interval=execution_time, button="right"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=cx, y=by - 100, interval=execution_time, button="left"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=cx, y=by - 100, interval=execution_time, button="right"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.click(x=cx, y=by - 100, button="left"), pyautogui.click(x=rand_x, y=rand_y, interval=timeout_delay, button="left"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.click(x=cx, y=by - 100, button="left"), pyautogui.click(x=rand_x, y=rand_y, interval=timeout_delay, button="right"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.click(x=cx, y=by - 100, button="right"), pyautogui.click(x=rand_x, y=rand_y, interval=timeout_delay, button="right"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.click(x=cx, y=by - 100, button="right"), pyautogui.click(x=rand_x, y=rand_y, interval=timeout_delay, button="left"), time.sleep(timeout_delay)) for _ in range(3) ]
                ])
            else:
                if game.get("name", "").__contains__("Super Ace"):
                    by -= 80
                action.extend([
                    lambda: [ pyautogui.typewrite(['space'] * 6, interval=execution_time) for _ in range(3) ],
                    lambda: [ pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=execution_time, button="left") for _ in range(3) ],
                    lambda: [ pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=execution_time, button="right") for _ in range(3) ],
                    lambda: [ pyautogui.click(x=cx, y=by - 100, clicks=6, interval=execution_time, button="left") for _ in range(3) ],
                    lambda: [ pyautogui.click(x=cx, y=by - 100, clicks=6, interval=execution_time, button="right") for _ in range(3) ],
                    lambda: [ pyautogui.doubleClick(x=rand_x, y=rand_y, interval=execution_time, button="left") for _ in range(3) ],
                    lambda: [ pyautogui.doubleClick(x=rand_x, y=rand_y, interval=execution_time, button="right") for _ in range(3) ],
                    lambda: [ pyautogui.doubleClick(x=cx, y=by - 100, interval=execution_time, button="left") for _ in range(3) ],
                    lambda: [ pyautogui.doubleClick(x=cx, y=by - 100, interval=execution_time, button="right") for _ in range(3) ],
                    # lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, clicks=3, interval=execution_time, button="left"),
                    # lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, clicks=3, interval=execution_time, button="right"),
                    # lambda: pyautogui.doubleClick(x=cx, y=by - 100, clicks=3, interval=execution_time, button="left"),
                    # lambda: pyautogui.doubleClick(x=cx, y=by - 100, clicks=3, interval=execution_time, button="right"),
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp(button='left')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button="right"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='right')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=cx, y=by - 100, button="left"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='left')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=cx, y=by - 100, button="right"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='right')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button="left"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='left')) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button="right"), pyautogui.typewrite(['space'] * 6, interval=execution_time), pyautogui.mouseUp(button='right')) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=execution_time, button="left"), pyautogui.keyUp('space')) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=execution_time, button="right"), pyautogui.keyUp('space')) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=by - 100, clicks=6, interval=execution_time, button="left"), pyautogui.keyUp('space')) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=by - 100, clicks=6, interval=execution_time, button="right"), pyautogui.keyUp('space')) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=rand_x, y=rand_y, interval=execution_time, button="left"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=rand_x, y=rand_y, interval=execution_time, button="right"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=cx, y=by - 100, interval=execution_time, button="left"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=cx, y=by - 100, interval=execution_time, button="right"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.click(x=cx, y=by - 100, button="left"), pyautogui.click(x=rand_x, y=rand_y, interval=execution_time, button="left"), time.sleep(timeout_delay)) for _ in range(3) ],
                    lambda: [ (pyautogui.click(x=cx, y=by - 100, button="right"), pyautogui.click(x=rand_x, y=rand_y, interval=execution_time, button="right"), time.sleep(timeout_delay)) for _ in range(3) ]
                ]) if not state.spin_btn else \
            action.extend([
                #
            ])
        elif spin_type == "wheel_spin":
            if state.widescreen:
                action.extend([
                    lambda: pyautogui.click(x=cx + 520, y=cy + 335, button='left'),
                    lambda: pyautogui.click(x=cx + 520, y=cy + 335, button='right')
                ])
            else:
                if "PP" in provider.get("initial"):
                    action.extend([])
                else:
                    action.extend([
                        lambda: pyautogui.click(x=cx, y=by - 100, button='left'),
                        lambda: pyautogui.click(x=cx, y=by - 100, button='right')
                    ]) if not state.spin_btn else \
                    action.extend([
                        lambda: pyautogui.click(x=cx, y=by - 100, button='left'),
                        lambda: pyautogui.click(x=cx, y=by - 100, button='right'),
                    ])
            # if state.widescreen:
            #     if provider.get("initial") == "JILI": # Playtime
            #         cx += 30
            #         cy += 40
            #     action.extend([
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # auto spin style
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # spen then turbo
            #         # lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.press('space'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right')),
            #         # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='left')),
            #         # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(spin_delay), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right'))
            #     ])
            # else:
            #     action.extend([
            #         lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # auto spin style
            #         lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='left')),
            #         # lambda: (pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=by - 100, button='right'))
            #     ])
        # elif spin_type == "quick_spin":
        #     if state.widescreen:
        #         action.extend([
        #             lambda: pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left'),
        #             lambda: pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right'),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.press('space'), pyautogui.press('space')),
        #             lambda: (pyautogui.press('space'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.press('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.press('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.press('space')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='left'),
        #             lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='right'),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'))
        #         ])
        #     else:
        #         action.extend([
        #             lambda: pyautogui.doubleClick(x=cx, y=by - 100, button='left'),
        #             lambda: pyautogui.doubleClick(x=cx, y=by - 100, button='right'),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.press('space'), pyautogui.press('space')),
        #             lambda: (pyautogui.press('space'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.press('space')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='left'),
        #             lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='right'),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.press('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.keyDown('space')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'))
        #         ]) if not state.spin_btn else \
        #         action.extend([
        #             lambda: pyautogui.doubleClick(x=cx, y=by - 100, button='left'),
        #             lambda: pyautogui.doubleClick(x=cx, y=by - 100, button='right'),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
        #             lambda: (pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
        #             lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='left'),
        #             lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='right'),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=by - 100, button='right')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=by - 100, button='left')),
        #             lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'))
        #         ])
        elif spin_type == "scatter_spin":                    
            if state.widescreen:
                action.extend([
                    # lambda: pyautogui.click(x=cx + 520, y=cy + 335, button='left'),
                    # lambda: pyautogui.click(x=cx + 520, y=cy + 335, button='right'),
                    # lambda: pyautogui.press('space'),
                ])
            else:
                if "PP" in provider.get("initial"):                
                    action.extend([
                        lambda: (pyautogui.press('space'), time.sleep(random.uniform(0.05, 0.12)), pyautogui.mouseDown(x=cx, y=by - 200, button='left'), time.sleep(10 - (timer().timestamp() % 10)), pyautogui.mouseUp(button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(10 - (timer().timestamp() % 10)), pyautogui.keyUp('space'), pyautogui.press('space')),
                        
                        # lambda: pyautogui.click(x=cx, y=by - 100, button='left'),
                        # lambda: pyautogui.click(x=cx, y=by - 100, button='right'),
                        # lambda: pyautogui.press('space'),
                        # lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                        # lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=cx, y=by - 100, button='left'), time.sleep(10 - (timer().timestamp() % 10)), pyautogui.mouseUp(button='left')),
                        # lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=cx, y=by - 100, button='right'), time.sleep(10 - (timer().timestamp() % 10)), pyautogui.mouseUp(button='right'))
                    ]) 
                if game.get("name", "").__contains__("Super Ace"):
                    by -= 80
                action.extend([
                    lambda: pyautogui.click(x=cx, y=by - 100, button='left'),
                    # lambda: pyautogui.click(x=cx, y=by - 100, button='right'),
                    lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                    lambda: pyautogui.press('space'),
                    lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                    lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), pyautogui.mouseUp(button='left')),
                    # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), pyautogui.mouseUp(button='right'))
                    lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                    lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
                ]) if not state.spin_btn else \
                action.extend([
                    # lambda: pyautogui.click(x=cx, y=by - 100, button='left'),
                    # lambda: pyautogui.click(x=cx, y=by - 100, button='right'),
                    
                    # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='left'), pyautogui.mouseUp(button='left')),
                    # lambda: (pyautogui.mouseDown(x=cx, y=by - 100, button='right'), pyautogui.mouseUp(button='right'))
                ])
        if not action:
            log_message("info", f"\t⚠️ No available spin actions for {spin_type}")
            return
        
        # alert_queue.put(f"{state.last_spin}")
        # if not state.fast_mode:
        #     alert_queue.put(f"{spin_type}")
            # alert_queue.put(str(int(abs(state.predicted_delta_10m))))
        
        # if not state.fast_mode and wait_before_spin:
        #     interval_ms = Decimal(str(time.time())) - state.last_time
            
        #     if spin_type.startswith("auto") and "PG" in provider.get("initial"):
        #         reduce_ms = random.uniform(3.5, 4.5)
        #     elif spin_type.__contains__("turbo"):
        #         reduce_ms = random.uniform(0.0, 1.5)
        #     else:
        #         reduce_ms = random.uniform(2.5, 3.0) # avg: 1.79ms waiting time
            
        #     # waiting_time = float(interval_ms) - random.uniform(0.0, 3.0) # before this is 3
        #     waiting_time = float(interval_ms) - reduce_ms
            
        #     if spin_type.endswith("delay"):# or spin_type.startswith("combo"):
        #         waiting_time = waiting_time - hold_delay
        #     elif spin_type.endswith("slide"):
        #         waiting_time = waiting_time - timeout_delay
        #     # elif spin_type.startswith("super"):
        #     #     if "PG" in provider.get("initial"):
        #     #         waiting_time = waiting_time - 0.3
        #     #     elif "JILI" in provider.get("initial"):
        #     #         waiting_time = waiting_time - 0.5
            
        #     # elif spin_type.startswith("auto") and "PG" in provider.get("initial"):
        #     #     waiting_time = 0
            
        #     # sys.stdout.write(f"\t\t<{colors['BLNK']}🌀{colors['RES']} {colors['RED']}{spin_type.replace('_', ' ').upper()}{colors['RES']} Waiting Time: {colors['WHTE']}{waiting_time}{colors['RES']} Interval MS: {colors['WHTE']}{interval_ms}{colors['RES']} State-Interval: {colors['WHTE']}{state.interval}{colors['RES']}>\n")
            
        #     time.sleep(abs(waiting_time))
        # else:
        #     sys.stdout.write(f"\t\t<{colors['BLNK']}🌀{colors['RES']} {colors['RED']}SPIKE SPIN{colors['RES']}>\n")
        
        if scatter_mode:
            # time.sleep(10 - (timer().second % 10))
            time.sleep(10 - (timer().timestamp() % 10))
            
        if wheel_mode: 
            # base = state.wheel_sleep
            # variation = base * 0.1   # 10%
            # time.sleep(random.uniform(base, base + variation))

            time.sleep(state.wheel_secs)
        
        random.choice(action)()
        
        # prevent hold down key bug
        # if any([spin_type.endswith("delay"), spin_type.endswith("hold")]): pyautogui.mouseUp()
        
        # COMBO SPIN INITIAL spin(normal or auto_spin)
        # if spin_type.startswith("combo"):
        #     init_action = []
        #     init_action.extend([
        #         lambda: pyautogui.click(x=cx, y=by - 100, button='left'),
        #         # lambda: pyautogui.click(x=cx, y=by - 100, button='right'),
        #         lambda: pyautogui.press('space'),
        #         lambda: (pyautogui.click(x=cx + 195, y=by - 100, button='left'), time.sleep(0.3), pyautogui.click(x=cx - 195, y=by - 205, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'))
        #     ])
        #     random.choice(init_action)()
        #     time.sleep(0.5)
        #     random.choice(action)()
        
        # if not state.fast_mode and wait_before_spin and spin_type == "normal_spin":
        #     extra_spin = []
        #     if state.widescreen:
        #         if provider.get("initial") == "JILI": # Playtime
        #             cx += 30
        #             cy += 40
        #         extra_spin.extend([
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             # auto spin style
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
        #             lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'))
        #         ])
        #     else:
        #         if "PG" in provider.get("initial"):
        #             extra_spin.extend([
        #                 # TURBO ENABLED
        #                 lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
        #                 # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
        #                 # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
        #                 # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
        #                 # lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='right'), pyautogui.press('space'), pyautogui.click(x=cx - 200, y=by - 100, button='left')),
        #                 # TURBO ENABLED
        #                 lambda: (pyautogui.click(x=cx - 200, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx - 200, y=by - 100, button='left'))
        #             ])
        #         else:
        #             extra_spin.extend([
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=cx, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 # auto spin style
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='left'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='left')),
        #                 lambda: (pyautogui.click(x=cx + 152, y=by - 100, button='right'), pyautogui.doubleClick(x=cx + 95, y=by - 100, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=by - 100, button='right'))
        #             ]) if not state.spin_btn else \
        #             extra_spin.extend([
        #                 #
        #             ])
                    
        #     random.choice(extra_spin)()
        #     alert_queue.put(f"{spin_type}")
                    
        # now_time = time.time()
        # current_sec = int(now_time) % 10
        # return spin_type
        
        # now_time = time.time()
        # current_sec = int(now_time) % 60
        # sys.stdout.write(f"\t\t<{BLNK}🌀{RES} {RED}{spin_type.replace('_', ' ').upper()}{RES} {MAG}{current_sec}{RES}>\n")

        # print(f"\tHold Delay: {hold_delay:.2f}")
        # print(f"\tSpin Delay: {spin_delay:.2f}")
        # print(f"\tTimeout Delay: {timeout_delay:.2f}")
        # print(f"\tCombo Spin: {combo_spin}")
        # print(f"\n\t\t<{BLNK}🌀{RES} {RED}{spin_type.replace('_', ' ').upper()} {RES}>\n")
        # alert_queue.put(f"{spin_type}")
        # spin_in_progress.clear()
    finally:
        state.last_spin = spin_type
        spin_in_progress.clear()
        # if not state.fast_mode:
        #     if state.last_spin not in already_alerted:
        #         alert_queue.put(f"{state.last_spin}")
        #         already_alerted.add(state.last_spin)
        # if scatter_mode: state.scatter_mode = False
        if scatter_spin: state.scatter_spin = False
        if wheel_mode: state.wheel_mode = False
        if quick_spin: state.quick_spin = False
        if not state.auto_mode: alert_queue.put(f"{spin_type}")
      
def play_alert(say: str = None):
    voices_env = os.getenv("VOICES", "")
    VOICES_LIST = [v.strip() for v in voices_env.split(",") if v.strip()]
    VOICES = {name: name for name in VOICES_LIST}
    PING = os.getenv("PING")
    TINK = os.getenv("TINK")
    
    if platform.system() == "Darwin":
        while not stop_event.is_set():
            try:
                if not alert_queue.empty():
                    say = alert_queue.get_nowait()
                    sound_file = (say)

                    if sound_file == "ping":
                        subprocess.run(["afplay", PING])
                    elif sound_file == "tink":
                        subprocess.run(["afplay", TINK])
                    else:                    
                        voice = VOICES["Trinoids"] if (
                            # all([state.min10 >= state.min10_thresh, state.pull_delta >= state.pull_thresh])
                            # or "pull_score_spin" in sound_file
                            # or "bet max" in sound_file
                            "pull_score_spin" in sound_file or "bet max" in sound_file or any(keyword in sound_file for keyword in ["DRAIN", "LOADED"])
                        ) else VOICES["Samantha"]
                        
                        subprocess.run(["say", "-v", voice, "--", sound_file])
                        
                    alert_queue.task_done()
                else:
                    time.sleep(0.05)
            except Empty:
                continue
            except Exception as e:
                log_message("info", f"\n\t[Alert Thread Error] {e}")
            finally:
                already_alerted.clear()
        else: # Other OS no code yet
            pass

# -------------------------
# Thread-safe overlay log_message (with fixed redraw order)
# -------------------------
_overlay_states = {}       # Tracks last line count per overlay key
_overlay_lines_cache = {}  # Stores last lines printed per overlay
_overlay_locks = {}        # Lock per overlay key
_overlay_order = [ "banner", "hs_data", "api_data", "rtp_data", "winners_data" ]  # Fixed redraw order

def log_message(level: str = "info", message: str = None, overwrite: bool = False, *args, **kwargs):
    """
    Logs a message to stdout/logger.
    If overwrite=True, updates the same terminal area (overlay effect), thread-safe per overlay key.
    _overlay_key: internal key for independent overlays.
    """
    if not message:
        return

    key = kwargs.pop("_overlay_key", "default")

    if overwrite:
        if key not in _overlay_states:
            _overlay_states[key] = 0
            _overlay_lines_cache[key] = []
            _overlay_locks[key] = threading.Lock()
            
        with _overlay_locks[key]:
            lines = message.splitlines()
            _overlay_lines_cache[key] = lines
            _overlay_states[key] = len(lines)
            # Redraw overlays in fixed order
            sys.stdout.write("\033[H")  # Move to top of terminal
            sys.stdout.write("\033[J")  # Clear screen from cursor down

            for overlay_key in _overlay_order:
                overlay_lines = _overlay_lines_cache.get(overlay_key, [])
                if overlay_lines:
                    sys.stdout.write("\n".join(overlay_lines) + "\n")

            sys.stdout.flush()
        return
    # Normal logging if not overwriting
    try:
        level_lower = level.lower()
        if level_lower == "debug":
            logger.debug(message, *args, **kwargs)
        elif level_lower == "warning":
            logger.warning(message, *args, **kwargs)
        elif level_lower == "error":
            logger.error(message, *args, **kwargs)
        elif level_lower == "critical":
            logger.critical(message, *args, **kwargs)
        else:
            logger.info(message, *args, **kwargs)
    except Exception as e:
        sys.stderr.write(f"\n\t[log_message Error] {e}\n")

def timer():
    current_timestamp = Decimal(str(datetime.now().timestamp()))
    today = datetime.fromtimestamp(float(current_timestamp))
    return today

def time_ago(timestamp_str: str) -> str:
    ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    now = datetime.now()
    diff = now - ts

    total_seconds = diff.total_seconds()
    
    tag = f"{colors['BLNK']}🔥{colors['RES']}"
    
    if total_seconds < 1:
        state.hit_win = True
        # Less than 1 second: show milliseconds
        return f"{colors['RED']}{total_seconds:.2f} ms {tag}"
    elif total_seconds < 60:
        # Seconds with milliseconds
        seconds = int(total_seconds)
        state.hit_win = True if seconds <= 10 else False
        return f"{colors['RED'] if seconds <= 10 else colors['WHTE']}{total_seconds:.2f} secs {tag if seconds <= 10 else 'elapsed'}"
    elif total_seconds < 3600:
        # Minutes + seconds
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        return f"{colors['WHTE']}{minutes} min {seconds} sec{'s' if seconds != 1 else ''} ago"
    elif total_seconds < 86400:
        # Hours + minutes
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        return f"{colors['WHTE']}{hours} hr {minutes} min{'s' if minutes != 1 else ''} ago"
    else:
        # Days + hours
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        return f"{colors['WHTE']}{days} day{'s' if days != 1 else ''} {hours} hr{'s' if hours != 1 else ''} ago"

def avg_interval_seconds(winners_data, game_name, sample=5):
    times = []

    for w in winners_data:
        if w.get("game", "").lower() == game_name.lower():
            ts = datetime.strptime(w["time"], "%Y-%m-%d %H:%M:%S")
            times.append(ts)

    if len(times) < 2:
        return None, None

    times.sort(reverse=False)

    diffs = [
        (times[i] - times[i+1]).total_seconds()
        for i in range(min(sample, len(times) - 1))
    ]

    avg_sec = sum(diffs) / len(diffs)
    return avg_sec, times[0]  # average, last hit

def trend_countdown(last_hit, avg_sec):
    eta = last_hit + timedelta(seconds=avg_sec)
    diff = (eta - datetime.now()).total_seconds()

    tag = f"{colors['BLNK']}🔥{colors['RES']}"

    if diff <= 0:
        state.hit_win = True
        return f"{colors['RED']}Due Now {tag}{colors['RES']}"

    if diff < 10:
        state.hit_win = True
        return f"{colors['BLNK']}{diff:.1f}s {tag}{colors['RES']}"

    if diff < 60:
        return f"{int(diff)}s"

    minutes = int(diff // 60)
    seconds = int(diff % 60)
    return f"{minutes}m {seconds}s"

def str_to_float(s):
    # Keep digits and decimal points only
    cleaned = re.sub(r"[^\d.]", "", s)
    return float(cleaned) if cleaned else 0.0

def banner(game: dict, providers: dict):
    while not stop_event.is_set():
        try:
            border = "-" * 44
            content_width = len(border) + 8
            title_text = (
                f"{colors['LGRY']}"
                f"{re.sub(r'\\s*\\(.*?\\)', '', game["name"]).upper()}"
                f"{colors['RES']} ("
                f"{colors[providers.get('color')]}{providers['initial']}{colors['RES']})"
            )
            slot_mode = "dual" if state.dual_slots else "split screen" if state.split_screen else "left" if state.left_slot else "right" if state.right_slot else "single"
            
            slot_mode_colored = (
                f"{colors['RED']}dual{colors['RES']}" if slot_mode == "dual"
                else f"{colors['LBLU']}split screen{colors['RES']}" if slot_mode == "split screen"
                else f"{colors['BLU']}left{colors['RES']}" if slot_mode == "left"
                else f"{colors['MAG']}right{colors['RES']}" if slot_mode == "right"
                else f"{colors['DGRY']}single{colors['RES']}"
            )
            
            slot_text = f"{colors['BLGRE']}Slot{colors['RES']}: {slot_mode_colored}"
            auto_mode_text = f"{colors['BLGRE']}Mode{colors['RES']}: {colors['BLCYN'] if state.auto_mode else colors['CYN']}{'auto' if state.auto_mode else 'manual'}, {'slow' if state.slow_mode else 'normal'}{colors['RES']}"
            scatter_mode_text = f"{colors['BLGRE']}Scatter Mode{colors['RES']}: {colors['BLCYN'] if state.scatter_mode else colors['CYN']}{'ON' if state.scatter_mode else 'OFF'}{colors['RES']}"
            
            def visible_length(s):
                return len(re.sub(r"\x1b\[[0-9;]*m", "", s))

            def center_text(text, width):
                pad_total = max(width - visible_length(text), 0)
                pad_left = pad_total // 2
                pad_right = pad_total - pad_left
                return " " * pad_left + text + " " * pad_right
            
            icons_len = (visible_length("🃏") + visible_length("🎰")) * 2
            space_for_text = (content_width - 1) - icons_len
            
            slot_text_centered = center_text(slot_text, space_for_text)
            slot_line = f"🃏{slot_text_centered}🎰"

            time_line = f"\n\n\n\t\t{colors['LMAG']}[{colors['DGRY']}{f"{timer().second}.{timer().microsecond // 10000:02d}"} ms{colors['WHTE']}]{colors['RES']}  ⏰  {colors['BYEL']}{timer().strftime('%I')}{colors['BWHTE']}:{colors['BYEL']}{timer().strftime('%M')}{colors['BWHTE']}:{colors['BLYEL']}{timer().strftime('%S')} {colors['LBLU']}{timer().strftime('%p')} {colors['MAG']}{timer().strftime('%a')}{colors['RES']}"
            time_line_centered = center_text(time_line, content_width)
            
            banner_lines = [
                f"♦️  {border}  ♠️",
                center_text(title_text, content_width),
                slot_line,
                center_text(auto_mode_text, content_width - 1),
                center_text(scatter_mode_text, content_width - 1),
                f"♣️  {border}  ♥️",
            ]

            banner_lines.insert(0, time_line_centered)
            banner = "\n\t".join(banner_lines)
            banner = "\t" + banner
            
            log_message("info", banner, overwrite=True, _overlay_key="banner")
            
            # if state.scatter_mode:
            #     # alert_queue.put(f"scatter spin ON")
            #     countdown = (10 - timer().second % 10)
            #     if countdown not in already_alerted  and countdown <= 3:
            #         alert_queue.put(f"{countdown}")
            #         already_alerted.add(countdown)
            stop_event.wait(0.5)
        except Exception as e:
            log_message("error", f"[banner] {e}", overwrite=True, _overlay_key="banner")
            time.sleep(0.5)
    
# -------------------------
# Threads
# -------------------------
def fetch_hs_data():
    prev_jackpot = prev_10m = prev_1h = prev_3h = prev_6h = None
    prev_delta = prev_delta_10m = prev_delta_1h = prev_delta_3h = prev_delta_6h = None
    last_jackpot_value = last_10m_value = last_1h_value = last_3h_value = last_6h_value = None
    last_delta_value = last_delta_10m_value = last_delta_1h_value = last_delta_3h_value = last_delta_6h_value = None
    
    while not stop_event.is_set():
        try:
            game_data_raw = r.get("game_data")
            if not game_data_raw:
                time.sleep(0.5)
                continue

            game_data = json.loads(game_data_raw)
            current_jackpot = pct(game_data.get("jackpot_value"))
            meter_color = game_data.get("meter_color")
            hs_10m = game_data.get("10min")
            hs_1h = game_data.get("1hr")
            hs_3h = game_data.get("3hrs")
            hs_6h = game_data.get("6hrs")
            
            state.hs_jackpot = current_jackpot
            
            prev_jackpot = 0.0 if prev_jackpot is None else last_jackpot_value if (current_jackpot != last_jackpot_value) else prev_jackpot
            prev_10m = 0.0 if prev_10m is None else last_10m_value if (hs_10m != last_10m_value) else prev_10m
            prev_1h = 0.0 if prev_1h is None else last_1h_value if (hs_1h != last_1h_value) else prev_1h
            prev_3h = 0.0 if prev_3h is None else last_3h_value if (hs_3h != last_3h_value) else prev_3h
            prev_6h = 0.0 if prev_6h is None else last_6h_value if (hs_6h != last_6h_value) else prev_6h
            
            delta = round(current_jackpot - prev_jackpot, 2) if prev_jackpot is not None else 0.0
            delta_10m = round(hs_10m - prev_10m, 2) if prev_10m is not None else 0.0
            delta_1h = round(hs_1h - prev_1h, 2) if prev_1h is not None else 0.0
            delta_3h = round(hs_3h - prev_3h, 2) if prev_3h is not None else 0.0
            delta_6h = round(hs_6h - prev_6h, 2) if prev_6h is not None else 0.0
            
            prev_delta = 0.0 if prev_delta is None else last_delta_value if (delta != last_delta_value) else prev_delta
            prev_delta_10m = 0.0 if prev_delta_10m is None else last_delta_10m_value if (delta_10m != last_delta_10m_value) else prev_delta_10m
            prev_delta_1h = 0.0 if prev_delta_1h is None else last_delta_1h_value if (delta_1h != last_delta_1h_value) else prev_delta_1h
            prev_delta_3h = 0.0 if prev_delta_3h is None else last_delta_3h_value if (delta_3h != last_delta_3h_value) else prev_delta_3h
            prev_delta_6h = 0.0 if prev_delta_6h is None else last_delta_6h_value if (delta_6h != last_delta_6h_value) else prev_delta_6h
                
            hs_signal = f"{colors['LRED']}▼{colors['RES']}" if delta < prev_delta else f"{colors['LGRE']}▲{colors['RES']}" if delta > prev_delta else f"{colors['LCYN']}◆{colors['RES']}"
            hs_signal_10m = f"{colors['LRED']}▼{colors['RES']}" if delta_10m < prev_delta_10m else f"{colors['LGRE']}▲{colors['RES']}" if delta_10m > prev_delta_10m else f"{colors['LCYN']}◆{colors['RES']}"
            hs_signal_1h = f"{colors['LRED']}▼{colors['RES']}" if delta_1h < prev_delta_1h else f"{colors['LGRE']}▲{colors['RES']}" if delta_1h > prev_delta_1h else f"{colors['LCYN']}◆{colors['RES']}"
            hs_signal_3h = f"{colors['LRED']}▼{colors['RES']}" if delta_3h < prev_delta_3h else f"{colors['LGRE']}▲{colors['RES']}" if delta_3h > prev_delta_3h else f"{colors['LCYN']}◆{colors['RES']}"
            hs_signal_6h = f"{colors['LRED']}▼{colors['RES']}" if delta_6h < prev_delta_6h else f"{colors['LGRE']}▲{colors['RES']}" if delta_6h > prev_delta_6h else f"{colors['LCYN']}◆{colors['RES']}"
            hs_signal_future = f"{colors['LRED']}⬇{colors['RES']}" if delta < prev_delta else f"{colors['LGRE']}⬆{colors['RES']}" if delta > prev_delta else f"{colors['LCYN']}◉{colors['RES']}"
            
            hs_delta_signal = f"{colors['LRED']}➜{colors['RES']}" if delta < prev_delta else f"{colors['LGRE']}➜{colors['RES']}" if delta > prev_delta else f"{colors['LCYN']}➜{colors['RES']}"
            hs_delta_signal_10m = f"{colors['LRED']}➜{colors['RES']}" if delta_10m < prev_delta_10m else f"{colors['LGRE']}➜{colors['RES']}" if delta_10m > prev_delta_10m else f"{colors['LCYN']}➜{colors['RES']}"
            hs_delta_signal_1h = f"{colors['LRED']}➜{colors['RES']}" if delta_1h < prev_delta_1h else f"{colors['LGRE']}➜{colors['RES']}" if delta_1h > prev_delta_1h else f"{colors['LCYN']}➜{colors['RES']}"
            hs_delta_signal_3h = f"{colors['LRED']}➜{colors['RES']}" if delta_3h < prev_delta_3h else f"{colors['LGRE']}➜{colors['RES']}" if delta_3h > prev_delta_3h else f"{colors['LCYN']}➜{colors['RES']}"
            hs_delta_signal_6h = f"{colors['LRED']}➜{colors['RES']}" if delta_6h < prev_delta_6h else f"{colors['LGRE']}➜{colors['RES']}" if delta_6h > prev_delta_6h else f"{colors['LCYN']}➜{colors['RES']}"
            
            # hs_sign_10m = f"{colors['GRE']}+{colors['RES']}" if delta_10m > 0 else ""
            
            colored_hs_10m = f"{colors['RED'] if hs_10m < 0 else colors['GRE'] if hs_10m > 0 else colors['LCYN']}{hs_10m:.2f}{colors['RES']}"
            colored_hs_1h = f"{colors['RED'] if hs_1h < 0 else colors['GRE'] if hs_1h > 0 else colors['LCYN']}{hs_1h:.2f}{colors['RES']}"
            colored_hs_3h = f"{colors['RED'] if hs_3h < 0 else colors['GRE'] if hs_3h > 0 else colors['LCYN']}{hs_3h:.2f}{colors['RES']}"
            colored_hs_6h = f"{colors['RED'] if hs_6h < 0 else colors['GRE'] if hs_6h > 0 else colors['LCYN']}{hs_6h:.2f}{colors['RES']}"
            
            colored_current = f"{colors['RED'] if current_jackpot < prev_jackpot else colors['GRE']}{current_jackpot:.2f}{colors['RES']}"            
            colored_prev = f"{colors['RED'] if prev_jackpot < current_jackpot else colors['GRE']}{prev_jackpot:.2f}{colors['RES']}"
            colored_prev_10m = f"{colors['RED'] if prev_10m < 0 else colors['GRE'] if prev_10m > 0 else colors['LCYN']}{prev_10m:.2f}{colors['RES']}"
            colored_prev_1h = f"{colors['RED'] if prev_1h < 0 else colors['GRE'] if prev_1h > 0 else colors['LCYN']}{prev_1h:.2f}{colors['RES']}"
            colored_prev_3h = f"{colors['RED'] if prev_3h < 0 else colors['GRE'] if prev_3h > 0 else colors['LCYN']}{prev_3h:.2f}{colors['RES']}"
            colored_prev_6h = f"{colors['RED'] if prev_6h < 0 else colors['GRE'] if prev_6h > 0 else colors['LCYN']}{prev_6h:.2f}{colors['RES']}"
            
            colored_prev_delta = f"{colors['RED'] if prev_delta < 0 else colors['GRE'] if prev_delta > 0 else colors['CYN']}{prev_delta:+.2f}{colors['RES']}"
            colored_prev_delta_10m = f"{colors['RED'] if prev_delta_10m < 0 else colors['GRE'] if prev_delta_10m > 0 else colors['CYN']}{prev_delta_10m:+.2f}{colors['RES']}"
            colored_prev_delta_1h = f"{colors['RED'] if prev_delta_1h < 0 else colors['GRE'] if prev_delta_1h > 0 else colors['CYN']}{prev_delta_1h:+.2f}{colors['RES']}"
            colored_prev_delta_3h = f"{colors['RED'] if prev_delta_3h < 0 else colors['GRE'] if prev_delta_3h > 0 else colors['CYN']}{prev_delta_3h:+.2f}{colors['RES']}"
            colored_prev_delta_6h = f"{colors['RED'] if prev_delta_6h < 0 else colors['GRE'] if prev_delta_6h > 0 else colors['CYN']}{prev_delta_6h:+.2f}{colors['RES']}"
            
            colored_delta = f"{colors['RED'] if delta < 0 else colors['GRE'] if delta > 0 else colors['CYN']}{delta:+.2f}{colors['RES']}"
            colored_delta_10m = f"{colors['RED'] if delta_10m < 0 else colors['GRE'] if delta_10m > 0 else colors['CYN']}{delta_10m:+.2f}{colors['RES']}"
            colored_delta_1h = f"{colors['RED'] if delta_1h < 0 else colors['GRE'] if delta_1h > 0 else colors['CYN']}{delta_1h:+.2f}{colors['RES']}"
            colored_delta_3h = f"{colors['RED'] if delta_3h < 0 else colors['GRE'] if delta_3h > 0 else colors['CYN']}{delta_3h:+.2f}{colors['RES']}"
            colored_delta_6h = f"{colors['RED'] if delta_6h < 0 else colors['GRE'] if delta_6h > 0 else colors['CYN']}{delta_6h:+.2f}{colors['RES']}"

            jackpot_bar = get_jackpot_bar(current_jackpot, meter_color)
            percent = f"{colors['WHTE']}%{colors['RES']}"
            
            # diff = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev} {percent}{colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta} {percent})"
            # diff_10m = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev_10m} {percent} {colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta_10m} {percent})"
            # diff_1h = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev_1h} {percent}{colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta_1h} {percent})"
            # diff_3h = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev_3h} {percent}{colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta_3h} {percent})"
            # diff_6h = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev_6h} {percent}{colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta_6h} {percent})"
            
            diff = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta} {hs_delta_signal} {colored_delta})"
            diff_10m = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta_10m} {hs_delta_signal_10m} {colored_delta_10m})"
            diff_1h = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta_1h} {hs_delta_signal_1h} {colored_delta_1h})"
            diff_3h = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta_3h} {hs_delta_signal_3h} {colored_delta_3h})"
            diff_6h = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta_6h} {hs_delta_signal_6h} {colored_delta_6h})"
            
            message = (
                f"\n\t🎰 {colors['ORA']}Jackpot Meter{colors['RES']}: {colored_current} {percent} {diff} {hs_signal}\n"
                f"\n\t{jackpot_bar} {f'{colors['WHTE']}Last Spin{colors['RES']}: {colors['BRED']}{state.last_spin.replace('_', ' ').title()} {colors['BLNK']}🌀{colors['RES']}' if state.last_spin and state.auto_mode else ''}\n"
                f"\n\t{colors['CYN']}⏱{colors['RES']} {colors['LYEL']}10m{colors['RES']}:  {colored_hs_10m} {percent} {diff_10m} {hs_signal_10m}"
                f"\n\t{colors['CYN']}⏱{colors['RES']} {colors['LYEL']}1hr{colors['RES']}:  {colored_hs_1h} {percent} {diff_1h} {hs_signal_1h}"
                f"\n\t{colors['CYN']}⏱{colors['RES']} {colors['LYEL']}3hr{colors['RES']}:  {colored_hs_3h} {percent} {diff_3h} {hs_signal_3h}"
                f"\n\t{colors['CYN']}⏱{colors['RES']} {colors['LYEL']}6hr{colors['RES']}:  {colored_hs_6h} {percent} {diff_6h} {hs_signal_6h}"
            )
            
            last_delta_value = delta
            last_delta_10m_value = delta_10m
            last_delta_1h_value = delta_1h
            last_delta_3h_value = delta_3h
            last_delta_6h_value = delta_6h
            
            last_jackpot_value = current_jackpot
            last_10m_value = hs_10m
            last_1h_value = hs_1h
            last_3h_value = hs_3h
            last_6h_value = hs_6h

            log_message("info", message, overwrite=True, _overlay_key="hs_data")
            stop_event.wait(0.5)
        except Exception as e:
            log_message("error", f"[fetch_hs_data] {e}", overwrite=True, _overlay_key="hs_data")
            time.sleep(0.5)

def fetch_api_data():
    prev_jackpot = prev_10m = prev_1h = prev_3h = prev_6h = None
    prev_delta = prev_delta_10m = prev_delta_1h = prev_delta_3h = prev_delta_6h = None
    last_jackpot_value = last_10m_value = last_1h_value = last_3h_value = last_6h_value = None
    last_delta_value = last_delta_10m_value = last_delta_1h_value = last_delta_3h_value = last_delta_6h_value = None

    last_api_vol = prev_api_vol = api_vol_delta = prev_api_vol_delta = last_api_vol_delta = None
    last_volatility = prev_volatility = volatility_delta = prev_volatility_delta = last_volatility_delta = None
    last_predicted_delta = prev_predicted_delta = predicted_delta_delta = prev_predicted_delta_delta = last_predicted_delta_delta = None
    
    # last_avg_volume_sec = prev_avg_volume_sec = avg_volume_sec = None
    last_avg_volatility_sec = prev_avg_volatility_sec = avg_volatility_sec = None
    last_avg_predicted_delta_sec = prev_avg_predicted_delta_sec = avg_predicted_delta_sec = None
    # last_avg_predicted_delta = prev_avg_predicted_delta = None
    
    # ema_api_vol = None
    # ema_volatility = None
    # ema_volatility_min = None

    new_signal = last_signal = None

    ema_vol_sec = None
    ema_volatility_sec = None
    # ema_predicted_delta = None
    ema_predicted_delta_sec = None
    # last_vol_min = None
    # last_vol_sec = None
    new_data_seconds = None
    # loaded = calm = relief = snap = 0
    EMA_ALPHA = 0.2
    DELTA_THRESHOLD = 10
    AVG_CHECK_INTERVAL = 300 # 5 mins

    vol_buffer = []
    rolling_avg_vol = 0.0
    lowest_vol = 0.0
    highest_vol = 0.0
    direction = None
    
    # init once
    hot_start = None
    hot_seconds = 0.0
    # bet_lvl = "Don't Bet"
    
    while not stop_event.is_set():
        try:
            BLINK = colors['BLNK'] if timer().second % 10 in (8, 9) else ''
            redis_key = f"api_data:{game['name']}:{provider['initial']}"
            api_data_raw = r.get(redis_key)
            if not api_data_raw:
                time.sleep(0.5)
                continue

            api_data = json.loads(api_data_raw)
            current_jackpot = pct(api_data.get("value"))
            meter_color = "green" if api_data.get("up") else "red"
            api_10m = api_data.get("min10")
            api_1h = api_data.get("hr1")
            api_3h = api_data.get("hr3")
            api_6h = api_data.get("hr6")

            state.api_jackpot = current_jackpot
            
            now = time.time()
            
            if current_jackpot != last_jackpot_value:
                # new_data_seconds = timer().second
                new_data_seconds = f"{colors['LYEL']}{timer().second}.{timer().microsecond // 10000:02d} {colors['CYN']}ms{colors['RES']}"
            
            prev_jackpot = 0.0 if prev_jackpot is None else last_jackpot_value if (current_jackpot != last_jackpot_value) else prev_jackpot
            prev_10m = 0.0 if prev_10m is None else last_10m_value if (api_10m != last_10m_value) else prev_10m
            prev_1h = 0.0 if prev_1h is None else last_1h_value if (api_1h != last_1h_value) else prev_1h
            prev_3h = 0.0 if prev_3h is None else last_3h_value if (api_3h != last_3h_value) else prev_3h
            prev_6h = 0.0 if prev_6h is None else last_6h_value if (api_6h != last_6h_value) else prev_6h
            
            # # PREDICTION MIN10 PULL
            # momentum_10m = delta_10m - prev_delta_10m

            # predicted_next_delta_10m = (
            #     delta_10m
            #     + momentum_10m * 0.5
            #     - delta_10m * 0.2
            # )

            # predicted_delta_10m = predicted_next_delta_10m
            
            # # predicted_next_10m = api_10m + (api_10m - prev_10m)
            # # predicted_delta_10m = (predicted_next_10m - prev_10m)
            # if state.auto_mode and abs(predicted_delta_10m) >= 150: # THRESHOLD
            #     state.fast_mode = True
            #     spin_in_progress.clear()
            #     # threading.Thread(target=spin, args=(False, False, True, False,), daemon=True).start()
            #     threading.Thread(target=spin, args=(False, False, False, False,), daemon=True).start()
            # elif state.auto_mode and  abs(predicted_delta_10m) >= 100: # THRESHOLD
            #     state.fast_mode = False
            #     threading.Thread(target=spin, args=(False, False, False, True,), daemon=True).start()
                
            # state.predicted_delta_10m = round(abs(predicted_delta_10m), 2)
            
            delta = round(current_jackpot - prev_jackpot, 2) if prev_jackpot is not None else 0.0
            delta_10m = round(api_10m - prev_10m, 2) if prev_10m is not None else 0.0
            delta_1h = round(api_1h - prev_1h, 2) if prev_1h is not None else 0.0
            delta_3h = round(api_3h - prev_3h, 2) if prev_3h is not None else 0.0
            delta_6h = round(api_6h - prev_6h, 2) if prev_6h is not None else 0.0
            
            prev_delta = 0.0 if prev_delta is None else last_delta_value if (delta != last_delta_value) else prev_delta
            prev_delta_10m = 0.0 if prev_delta_10m is None else last_delta_10m_value if (delta_10m != last_delta_10m_value) else prev_delta_10m
            prev_delta_1h = 0.0 if prev_delta_1h is None else last_delta_1h_value if (delta_1h != last_delta_1h_value) else prev_delta_1h
            prev_delta_3h = 0.0 if prev_delta_3h is None else last_delta_3h_value if (delta_3h != last_delta_3h_value) else prev_delta_3h
            prev_delta_6h = 0.0 if prev_delta_6h is None else last_delta_6h_value if (delta_6h != last_delta_6h_value) else prev_delta_6h
                
            delta_shift = round(delta - prev_delta, 2)
            delta_shift_10m = round(delta_10m - prev_delta_10m, 2)
            delta_shift_1h = round(delta_1h - prev_delta_1h, 2)
            delta_shift_3h = round(delta_3h - prev_delta_3h, 2)
            delta_shift_6h = round(delta_6h - prev_delta_6h, 2)
            
            # =========================
            # 2️⃣ VOLATILITY MEASURES
            # =========================
            api_vol = abs(delta_10m) + abs(delta_shift_10m)
            api_vol_delta = round(api_vol - prev_api_vol, 2) if prev_api_vol is not None else 0.0
            prev_api_vol = 0.0 if prev_api_vol is None else last_api_vol if (api_vol != last_api_vol) else prev_api_vol
            prev_api_vol_delta = 0.0 if prev_api_vol_delta is None else last_api_vol_delta if (api_vol_delta != last_api_vol_delta) else prev_api_vol_delta
            # jackpot deltas must already exist
            jackpot_pressure = abs(delta)

            if ema_vol_sec is None:
                ema_vol_sec = api_vol
            else:
                ema_vol_sec = (
                    EMA_ALPHA * api_vol
                    + (1 - EMA_ALPHA) * ema_vol_sec
                )

            # avg_volume_sec = round(ema_vol_sec, 2)
            # prev_avg_volume_sec = 0.0 if prev_avg_volume_sec is None else last_avg_volume_sec if (avg_volume_sec != last_avg_volume_sec) else prev_avg_volume_sec

            # =========================
            # 3️⃣ SESSION MODE
            # =========================
            # if jackpot_pressure < 1 and api_vol < 30:
            #     session_mode = "COLD"
            # elif jackpot_pressure < 2 and api_vol < 80:
            #     session_mode = "WARM"
            # elif jackpot_pressure >= 2 or api_vol >= 120:
            #     session_mode = "HOT"
                
                
            #     # if state.auto_mode:
            #     #     if state.last_spin is not None:
            #     #         if not any(
            #     #             spin_type in state.last_spin
            #     #             for spin_type in ("auto", "turbo", "spam", "hold", "scatter")
            #     #         ):
            #     #         # if not any([
            #     #         #     state.last_spin.startswith("auto"), 
            #     #         #     state.last_spin.__contains__("turbo"), 
            #     #         #     state.last_spin.__contains__("spam"),
            #     #         #     state.last_spin.__contains__("hold"), 
            #     #         #     state.last_spin.__contains__("scatter")
            #     #         # ]):
            #     #             # if random.random() < 0.4: # 40% only reset
            #     #             spin_in_progress.clear()
            #     #         threading.Thread(target=spin, args=(False, False, True, False,), daemon=False).start()
            #     #     else: 
            #     #         threading.Thread(target=spin, args=(False, False, True, False,), daemon=True).start()
            # else:
            #     session_mode = "DRAIN"
            
            # --- Predict next delta ---
            # predicted_delta_10m = delta_10m + delta_shift_10m * 0.5 - delta_10m * 0.2            
            polarity_flip = any([prev_delta_10m > 0 > delta_10m, prev_delta_10m < 0 < delta_10m]) # reversal
            explosion = abs(delta_shift_10m) >= 100 # strong acceleration

            volatility_score = (
                abs(delta_10m) * 0.6
                + abs(delta_shift_10m) * 0.3
                + (50 if polarity_flip else 0)
            )

            volatility_delta = round(volatility_score - prev_volatility, 2) if prev_volatility is not None else 0.0
            prev_volatility = 0.0 if prev_volatility is None else last_volatility if (volatility_score != last_volatility) else prev_volatility
            prev_volatility_delta = 0.0 if prev_volatility_delta is None else last_volatility_delta if (volatility_delta != last_volatility_delta) else prev_volatility_delta
            
            # volatility_score = min(volatility_score, MAX_VOL)
            
            # if last_vol_sec != timer().second:
            #     last_vol_sec = timer().second
            if ema_volatility_sec is None:
                ema_volatility_sec = volatility_score
            else:
                ema_volatility_sec = (
                    EMA_ALPHA * volatility_score
                    + (1 - EMA_ALPHA) * ema_volatility_sec
                )

            avg_volatility_sec = round(ema_volatility_sec, 2)
            prev_avg_volatility_sec = 0.0 if prev_avg_volatility_sec is None else last_avg_volatility_sec if (avg_volatility_sec != last_avg_volatility_sec) else prev_avg_volatility_sec

            predicted_delta_10m = (
                0.8 * delta_10m
                + 0.5 * delta_shift_10m
            ) / 1.7
            
            predicted_delta_delta = round(predicted_delta_10m - prev_predicted_delta, 2) if prev_predicted_delta is not None else 0.0
            prev_predicted_delta = 0.0 if prev_predicted_delta is None else last_predicted_delta if (predicted_delta_10m != last_predicted_delta) else prev_predicted_delta
            prev_predicted_delta_delta = 0.0 if predicted_delta_delta is None else last_predicted_delta_delta if (prev_predicted_delta_delta != last_predicted_delta_delta) else prev_predicted_delta_delta

            if ema_predicted_delta_sec is None:
                ema_predicted_delta_sec = predicted_delta_10m
            else:
                ema_predicted_delta_sec = (
                    EMA_ALPHA * predicted_delta_10m
                    + (1 - EMA_ALPHA) * ema_predicted_delta_sec
                )

            avg_predicted_delta_sec = round(ema_predicted_delta_sec, 2)
            # prev_avg_predicted_delta = 0.0 if prev_avg_predicted_delta is None else last_avg_predicted_delta if (avg_predicted_delta_sec != last_avg_predicted_delta) else prev_avg_predicted_delta
            prev_avg_predicted_delta_sec = 0.0 if prev_avg_predicted_delta_sec is None else last_avg_predicted_delta_sec if (avg_predicted_delta_sec != last_avg_predicted_delta_sec) else prev_avg_predicted_delta_sec
            # delta_avg_predicted_delta = round(prev_avg_predicted_delta - avg_predicted_delta, 2) if prev_avg_predicted_delta is not None else 0.0
            
            
            # if last_avg_predicted_delta_sec is not None:
            # if ema_volatility is None:
            #     ema_volatility = volatility_score
            # else:
            #     ema_volatility = (
            #         EMA_ALPHA * volatility_score
            #         + (1 - EMA_ALPHA) * ema_volatility
            #     )
                
            # if ema_predicted_delta is None:
            #     ema_predicted_delta = predicted_delta_10m
            # else:
            #     ema_predicted_delta = (
            #         EMA_ALPHA * predicted_delta_10m
            #         + (1 - EMA_ALPHA) * ema_predicted_delta
            #     )
        
            # if last_vol_min != timer().minute:
            #     last_vol_min = timer().minute
            #     if ema_volatility_min is None:
            #         ema_volatility_min = volatility_score
            #     else:
            #         ema_volatility_min = (
            #             EMA_ALPHA * volatility_score
            #             + (1 - EMA_ALPHA) * ema_volatility_min
            #         )
            

            
            # if avg_predicted_delta_sec != last_avg_predicted_delta_sec and any([
            # if (session_mode == "HOT") and any([
            #     # avg_volatility_sec >= 100,
            #     # avg_volatility_min >= 100,  
            #     # avg_volatility >= 100,
            #     # volatility_score >= 100
            #     # abs(predicted_delta_10m) >= 100 or abs(predicted_delta_10m) <= 5
                
            #     # math.floor(abs(predicted_delta_10m)) <= round(abs(avg_predicted_delta_sec)),
            #     # math.floor(volatility_score) >= round(abs(avg_volatility_sec)),
            #     round(predicted_delta_10m) == round(avg_predicted_delta_sec),
            #     abs(delta_avg_predicted_delta) > DELTA_THRESHOLD
                
            #     # round(abs(avg_predicted_delta)) >= round(abs(prev_avg_predicted_delta)) + 10,
            #     # round(abs(avg_predicted_delta)) <= round(abs(prev_avg_predicted_delta)) - 10
                
            #     # round(abs(avg_predicted_delta)) == round(abs(avg_predicted_delta_sec)),
            #     # round(abs(avg_predicted_delta_sec)) <= 0,
            #     # abs(avg_predicted_delta_sec) >= 100,
            # ]) and (
            #     any([
            #         avg_volatility_sec >= prev_avg_volatility_sec,
            #         abs(delta_avg_predicted_delta) > DELTA_THRESHOLD
            #     #     avg_volatility_sec >= prev_avg_volatility_sec,
            #     #     avg_predicted_delta_sec >= prev_avg_predicted_delta_sec,
            #     #     #  avg_volatility_sec >= avg_volatility,
            #     #     #  avg_predicted_delta_sec >= predicted_delta_10m
            #     ])
            #     # or timer().second % 10 in (9, 0)
            # ):
            
            # if (session_mode == "HOT" or state.hit_win) and any([

            if jackpot_pressure < 1 and api_vol < 30:
                session_mode = "COLD"
                if drain_start is not None:
                    drain_seconds = now - drain_start
                # reset HOT counter
                hot_start = None
                hot_seconds = 0.0
                # optionally reset DRAIN counter
                # drain_start = None
                # drain_seconds = 0.0
            elif jackpot_pressure < 2 and api_vol < 80:
                session_mode = "WARM"
                if drain_start is not None:
                    drain_seconds = now - drain_start
                # optionally reset HOT counter if you want only HOT mode counted
                hot_start = None
                hot_seconds = 0.0
                # optionally reset DRAIN counter
                # drain_start = None
                # drain_seconds = 0.0
            elif jackpot_pressure >= 2 or api_vol >= 120:
                session_mode = "HOT"
                # start timer if just entered HOT
                if hot_start is None:
                    hot_start = now
                hot_seconds = now - hot_start  # includes milliseconds
                # you can also trigger logic here, e.g.:
                # if hot_seconds > 5.0:  # example threshold
                # optionally reset DRAIN counter
                drain_start = None
                drain_seconds = 0.0
            else:
                session_mode = "DRAIN"
                if drain_start is None:
                    drain_start = now
                drain_seconds = now - drain_start
                # reset HOT counter
                hot_start = None
                hot_seconds = 0.0
                
            state.session_mode = session_mode

            # --- 3️⃣ Analyze trend for shock states ---
            abs_prev = abs(prev_delta_10m)
            abs_curr = abs(delta_10m)
            compression = abs_prev < 15 and abs_curr < 15  # quiet, low movement

            # new_signal = (
            #     "up" if api_vol > prev_api_vol
            #     else "down" if api_vol < prev_api_vol
            #     else None
            # )

            # prev_signal = last_signal
            # prev_signal = None if state.api_vol_signal is None else state.api_vol_signal  # store previous value

            # if api_vol != prev_api_vol:
                


                # state.api_vol_signal = new_signal

            if all([current_jackpot != last_jackpot_value, api_vol_delta != last_api_vol_delta]):
                new_signal = (
                    "up" if api_vol > prev_api_vol
                    else "down" if api_vol < prev_api_vol
                    else None
                )

                # last_signal = state.api_vol_signal
                
                if all([new_signal != last_signal, last_signal is not None]):
                    # if polarity_flip and explosion:
                    if  any([
                        # abs(api_vol_delta) >= 100, 
                        abs(api_vol_delta) >= 100 and explosion, 
                        abs(api_vol_delta) >= 100 and polarity_flip
                    ]):
                    # if abs(api_vol_delta) >= 100:
                        direction = "reversal"
                    else:
                        direction = "t r a p"
                else:
                    direction = "bullish" if new_signal == "up" else "bearish" if new_signal == "down" else None

                last_signal = new_signal

            if any([
                all([#api_vol > prev_api_vol,
                    # state.rtp,
                    # predicted_delta_10m > prev_predicted_delta or abs(round(avg_volatility_sec)) > abs(round(prev_avg_volatility_sec)),
                    predicted_delta_10m > prev_predicted_delta,
                    abs(round(avg_volatility_sec)) > abs(round(prev_avg_volatility_sec)),
                    # round(ema_volatility_sec, 2) <= math.floor(api_vol),
                    round(ema_vol_sec, 2) <= math.floor(api_vol) or round(avg_predicted_delta_sec) <= math.floor(predicted_delta_10m),
                    abs(round(avg_volatility_sec)) <= math.floor(volatility_score)]
                ),
                all([
                    # not state.rtp,
                    # predicted_delta_10m > prev_predicted_delta or abs(round(avg_volatility_sec)) < abs(round(prev_avg_volatility_sec)),
                    abs(round(avg_volatility_sec)) < abs(round(prev_avg_volatility_sec)),
                    # round(ema_volatility_sec, 2) >= math.floor(api_vol),
                    # round(ema_vol_sec, 2) >= math.floor(api_vol),
                    round(avg_predicted_delta_sec) <= math.floor(predicted_delta_10m),
                    abs(round(avg_volatility_sec)) >= math.floor(volatility_score)]
                ),
                all([
                    new_signal is not None,
                    new_signal != last_signal,
                    direction not in ["t r a p"],
                    round(avg_predicted_delta_sec) <= math.floor(predicted_delta_10m) or state.api_jackpot >= 99.66 and volatility_score > prev_volatility
                ])
                # all([api_vol < prev_api_vol, 
                #     abs(round(avg_volatility_sec)) < abs(round(prev_avg_volatility_sec)), 
                #     abs(round(avg_volatility_sec)) >= math.floor(volatility_score)]
                # ),
            ]):

            # if any([
            #     # math.floor(volatility_score) >= round(abs(avg_volatility_sec)),
            #     # avg_volatility_sec > prev_avg_volatility_sec,
                
            #     # state.hit_win,

            #     # (hot_seconds % 10) <= 5,
            #     # abs(delta_avg_predicted_delta) > DELTA_THRESHOLD,
            #     # math.floor(abs(predicted_delta_10m)) <= round(abs(avg_predicted_delta_sec)),

            #     # prev_api_vol_delta < 0 > api_vol_delta,
            #     # api_vol_delta > 0,
            #     # temp comment ---> replace with predict the lowest pull or before explosion or polarity_flip
            #     # abs(api_vol_delta) >= 100,
            #     # api_vol >= 150,
            #     # all([prev_api_vol < api_vol, api_vol_delta > 0]),
            #     # all([prev_api_vol_delta < api_vol_delta, api_vol_delta > 0]),
                
            #     # prev_api_vol_delta < 0 > api_vol_delta,
            #     # api_vol >= 150 or api_vol_delta > 0,

            #     # all([not polarity_flip, compression]),
            #     # # all([polarity_flip, any([abs(api_vol_delta) >= 100, api_vol >= 150, explosion])]),
            #     # all([api_vol >= 150, api_vol > prev_api_vol, api_vol_delta > prev_api_vol_delta, api_vol_delta > 0]),
            #     # all([api_vol >= 200, api_vol > prev_api_vol, api_vol_delta > prev_api_vol_delta, api_vol_delta > 0]),
            #     # abs(api_vol_delta) >= 100,
            #     # explosion
                

            #     # all([
            #     #     api_vol >= 120,
            #     #     api_vol_delta > 0,
            #     #     # api_vol_delta >= 120,
            #     #     api_vol_delta > prev_api_vol_delta,
            #     #     # api_vol > prev_api_vol,
            #     #     # avg_volatility_sec >= prev_avg_volatility_sec,
            #     #     math.floor(volatility_score) >= round(abs(avg_volatility_sec)),
            #     #     # math.floor(abs(predicted_delta_10m)) >= round(abs(avg_predicted_delta_sec))
            #     # ]),

                
            #     # all([
            #     #     # api_vol < 0,
            #     #     api_vol_delta < 0,
            #     #     api_vol < prev_api_vol,
            #     #     # avg_volatility_sec <= prev_avg_volatility_sec,
            #     #     math.floor(volatility_score) <= round(abs(avg_volatility_sec)),
            #     #     math.floor(abs(predicted_delta_10m)) <= round(abs(avg_predicted_delta_sec))
            #     # ]), 
            #     # neutral
            #     # all([
            #     #     # api_vol < 0,
            #     #     api_vol_delta < 0,
            #     #     api_vol  prev_api_vol,
            #     #     # avg_volatility_sec <= prev_avg_volatility_sec,
            #     #     math.floor(volatility_score) <= round(abs(avg_volatility_sec))
            #     # ])
                
            # ]) and (any([
            #         abs(round(avg_volatility_sec)) >= math.floor(volatility_score),
            #         # prev_api_vol < api_vol,
            #         # abs(api_vol_delta) >= 100,
            #         # all([api_vol > prev_api_vol, abs(round(avg_volatility_sec)) >= math.floor(volatility_score)]),
            #         # all([api_vol < prev_api_vol, abs(round(avg_volatility_sec)) <= math.floor(volatility_score)])
            #         # abs(round(avg_volatility_sec)) >= math.floor(volatility_score)

            #         # all([polarity_flip, abs(api_vol_delta) >= 100]),
            #         # all([polarity_flip, explosion]),

            #         # prev_api_vol_delta < 0 > api_vol_delta,
            #         # prev_api_vol_delta < 0 > api_vol_delta,
            #         # math.floor(abs(predicted_delta_10m)) <= round(abs(avg_predicted_delta_sec)),
            #         # (hot_seconds % 10) <= 5,
                    
            #         # math.floor(abs(predicted_delta_10m)) <= round(abs(avg_predicted_delta_sec)),
            #         # state.hit_win,
            #         # math.floor(volatility_score) > round(abs(avg_volatility_sec)),

            #         # all([
            #         #     # api_vol > 0,
            #         #     api_vol_delta > 0,
            #         #     api_vol >= prev_api_vol,
            #         #     # avg_volatility_sec >= prev_avg_volatility_sec,
            #         #     math.floor(volatility_score) >= round(abs(avg_volatility_sec))
            #         # ]),
                    
            #         # all([
            #         #     # api_vol < 0,
            #         #     api_vol_delta < 0,
            #         #     api_vol <= prev_api_vol,
            #         #     # avg_volatility_sec <= prev_avg_volatility_sec,
            #         #     math.floor(volatility_score) <= round(abs(avg_volatility_sec))
            #         # ])
                    
            #         # abs(delta_avg_predicted_delta) > DELTA_THRESHOLD,
                    
                    
            #         # avg_volatility >= 100 and avg_volatility_sec > prev_avg_volatility_sec,
            #         # math.floor(abs(predicted_delta_10m)) >= 100 and avg_volatility_sec > prev_avg_volatility_sec
                    
            #         # (avg_volatility_sec > prev_avg_volatility_sec and timer().second % 10) == random.choice((9, 0))
            #     ])
            # ):
            #  or#
            # if any([
            #     # prev_api_vol_delta < 0 > api_vol_delta, # Reversal
            #     # api_vol >= 150,
            #     # abs(api_vol_delta) >= 100,
            #     prev_api_vol_delta < 0 > api_vol_delta and math.floor(volatility_score) >= round(abs(avg_volatility_sec)),
            # ]):
                    
            #     # if state.scatter_mode: break
                
                # alert_queue.put(f"spin")
                state.fast_mode = True

                trigger = ((
                    state.rtp and any([
                        session_mode == "HOT" and direction in ["bullish", "reversal"],
                        # session_mode == "DRAIN" and any([drain_seconds <= 1, hot_seconds > 0.0]),
                        # session_mode not in ["HOT", "DRAIN"] and hot_seconds >= 0.0,
                        drain_seconds <= 1 or 0.0 < hot_seconds <= 7,
                        state.api_jackpot >= 99.66 and volatility_score > prev_volatility and direction in ["bullish", "reversal"],
                        api_vol_delta >= 120,
                        api_vol >= 200 and direction in ["bullish", "reversal"]
                        # abs(api_vol_delta) >= 100 or api_vol >= 200 or explosion
                    ]))
                or (not state.rtp and any([
                        session_mode == "DRAIN" and direction in ["bearish", "reversal"],
                        drain_seconds <= 1 or 0.0 < hot_seconds <= 7,
                        state.api_jackpot >= 99.66 and volatility_score > prev_volatility,
                        api_vol_delta <= -120,
                        api_vol >= 200 and direction in ["bearish", "reversal"]
                        # abs(api_vol_delta) >= 100 or api_vol >= 200
                    ])
                ))
                
                # if state.auto_mode and not state.wheel_mode and not state.quick_spin:
                if state.auto_mode and trigger and not state.wheel_mode and not state.quick_spin: #and abs(predicted_delta_10m) >= 100:
                    # threading.Thread(target=spin, args=(False, False, True, False,), daemon=True).start()
                    if state.last_spin is not None:
                        if not any(
                            spin_type in state.last_spin
                            for spin_type in ("auto", "turbo", "scatter", "spin_hold", "spin_slide")
                        ):
                            threading.Thread(target=spin, args=(False, False, True, False, False,), daemon=False).start() # non-turbo spin section
                        # if not any([
                        #     state.last_spin.startswith("auto"), 
                        #     state.last_spin.__contains__("turbo"), 
                        #     state.last_spin.__contains__("spam"),
                        #     state.last_spin.__contains__("hold"), 
                        #     state.last_spin.__contains__("scatter")
                        # ]):
                            # if random.random() < 0.4: # 40% only reset
                            if any(
                                spin_type in state.last_spin
                                for spin_type in ("normal", "spam", "board")
                            ) and all([
                                random.random() < 0.1,
                                predicted_delta_10m > prev_predicted_delta,
                                direction not in ["t r a p"],
                                abs(api_vol_delta) >= 100 or api_vol >= 200 or explosion or session_mode in ["HOT", "DRAIN"] or direction in ["reversal"]
                            ]):
                                # if state.slow_mode:
                                #     if any([
                                #         # state.hit_win,
                                #         explosion,
                                #         polarity_flip,
                                #         abs(api_vol_delta) >= 100,
                                #         api_vol >= 200,
                                #         api_vol >= 120 and any([prev_api_vol < api_vol, prev_api_vol_delta < api_vol_delta, api_vol_delta > 0])
                                #     ]):
                                #         spin_in_progress.clear()
                                # else:
                                spin_in_progress.clear()
                                alert_queue.put(f"clear")
                        # if state.slow_mode:
                        #     if session_mode == "HOT" and any([
                        #         # state.hit_win,
                        #         explosion,
                        #         polarity_flip,
                        #         abs(api_vol_delta) >= 100,
                        #         api_vol >= 200,
                        #         api_vol >= 120 and any([prev_api_vol < api_vol, prev_api_vol_delta < api_vol_delta, api_vol_delta > 0])
                        #     ]):
                            # if any([
                            #     session_mode == "HOT",
                            #     session_mode == "DRAIN" and drain_seconds <= 1, 
                            #     session_mode not in ["HOT", "DRAIN"] and hot_seconds >= 0.0,
                            #     state.api_jackpot >= 99 and volatility_score > prev_volatility
                            # ]):
                            # threading.Thread(target=spin, args=(False, False, True, False, False,), daemon=False).start() # non-turbo spin section
                            # alert_queue.put(f"false")
                        else:
                            # if any([
                            #     session_mode == "HOT",
                            #     session_mode == "DRAIN" and drain_seconds <= 1,
                            #     session_mode not in ["HOT", "DRAIN"] and hot_seconds >= 0.0,
                            #     state.api_jackpot >= 99 and volatility_score > prev_volatility
                            # ]):
                            threading.Thread(target=spin, args=(False, False, False, False, False,), daemon=True).start() # turbo spin section
                            # alert_queue.put(f"true")
                    else:
                        # threading.Thread(target=spin, args=(False, False, False, False, False,), daemon=True).start()
                        # alert_queue.put(f"first spin")
                        state.last_spin = "normal"


                            
                # state.last_trigger = f"{abs(predicted_delta_10m)} <= {math.floor(abs(avg_predicted_delta_sec))}"
                
                # if not any([state.scatter_mode, state.scatter_spin]):
                #     state.fast_mode = True
                #     if state.auto_mode: #and abs(predicted_delta_10m) >= 100:
                #         threading.Thread(target=spin, args=(False, False, True, False,), daemon=True).start()
                #         if state.last_spin is not None:
                #             if not any([state.last_spin.startswith("auto"), state.last_spin.__contains__("turbo"), state.last_spin.__contains__("hold"), state.last_spin.__contains__("scatter")]):
                #                 # if random.random() < 0.4: # 40% only reset
                #                 spin_in_progress.clear()
                # else:
                #     if not any([state.scatter_mode, state.widescreen, random.random() < 0.1]):
                #         state.extra_bet = not state.extra_bet
                #         threading.Thread(target=bet_switch, args=(False, state.extra_bet,), daemon=True).start()
            state.last_trigger = (
                f"{math.floor(abs(predicted_delta_10m))} <= {round(abs(avg_predicted_delta_sec))} "
                f"{colors['RED'] if math.floor(abs(predicted_delta_10m)) <= round(abs(avg_predicted_delta_sec)) else colors['RES']}"
                f"{math.floor(abs(predicted_delta_10m)) <= round(abs(avg_predicted_delta_sec))}"
                f"{colors['RES']}"
            )

            # PREDICTION MIN10 PULL
            # --- 1️⃣ Calculate current deltas ---
            # delta_10m = round(api_10m - prev_10m, 2) if prev_10m is not None else 0.0
            # momentum_10m = delta_10m - prev_delta_10m  # acceleration in the last 10 min

            if (avg_volatility_sec != prev_avg_volatility_sec):
                # --- 4️⃣ Decide shock state & fast_mode ---
                if compression:
                    # system is stable, no major change predicted
                    state.fast_mode = False
                    shock_state = "LOADED"
                    # loaded += 1
                    # if (avg_volatility_sec != prev_avg_volatility_sec): loaded += 1
                elif polarity_flip and explosion:
                    # sudden reversal predicted → high risk → immediate spin
                    state.fast_mode = True
                    # if state.auto_mode and all([session_mode == "HOT" and abs(predicted_delta_10m) >= 100]):
                    # if state.auto_mode and state.last_spin is not None:
                    #     if not any([state.last_spin.startswith("auto"), state.last_spin.__contains__("turbo"), state.last_spin.__contains__("hold")]):
                    #         # if random.random() < 0.4: # 40% only reset
                    #         spin_in_progress.clear()
                    #     threading.Thread(target=spin, args=(False, False, False, False,), daemon=True).start()
                            
                            
                    # if state.auto_mode and abs(predicted_delta_10m) >= 100:
                    #     threading.Thread(target=spin, args=(False, False, True, False,)).start()
                    #     if state.last_spin is not None:
                    #         if not any([state.last_spin.startswith("auto"), state.last_spin.__contains__("turbo"), state.last_spin.__contains__("hold")]):
                    #             if random.random() < 0.4: # 40% only reset
                    #                 spin_in_progress.clear()
                                    
                        # if state.fast_mode and state.last_spin is not None:
                        #     if not any([state.last_spin.startswith("auto"), state.last_spin.__contains__("turbo"), state.last_spin.__contains__("hold")]):
                        #         spin_in_progress.clear()
                                # alert_queue.put(f"{state.last_spin} CLEAR")
                        # threading.Thread(target=spin, args=(False, False, False, False,), daemon=True).start()
                        # if abs(predicted_delta_10m) >= 100: spin_in_progress.clear()
                    shock_state = "SNAP"
                    # snap += 1
                    # if (avg_volatility_sec != prev_avg_volatility_sec): snap += 1
                # elif abs_curr < abs_prev:
                elif abs_curr < abs_prev and 5 <= abs_curr <= 15 and abs(predicted_delta_10m) < 20:
                    # predicted delta is calming → safe moment to spin
                    # state.fast_mode = False
                    # if state.auto_mode:
                    #     threading.Thread(target=spin, args=(False, False, False, False,)).start()
                    shock_state = "RELIEF"
                    # relief += 1
                    # if (avg_volatility_sec != prev_avg_volatility_sec): relief += 1
                else:
                    # no special condition
                    state.fast_mode = False
                    shock_state = "CALM"
                    # calm += 1
                    # if (avg_volatility_sec != prev_avg_volatility_sec): calm += 1
                
            # # =========================
            # # 2️⃣ VOLATILITY MEASURES
            # # =========================
            # api_vol = abs(delta_10m) + abs(delta_shift_10m)
            # # jackpot deltas must already exist
            # jackpot_pressure = abs(delta)

            # # =========================
            # # 3️⃣ SESSION MODE
            # # =========================
            # if jackpot_pressure < 1 and api_vol < 30:
            #     session_mode = "COLD"
            # elif jackpot_pressure < 2 and api_vol < 80:
            #     session_mode = "WARM"
            # elif jackpot_pressure >= 2 or api_vol >= 120:
            #     session_mode = "HOT"
            # else:
            #     session_mode = "DRAIN"
                
            # state.predicted_delta_10m = round(abs(predicted_delta_10m), 2)
                
            # TEST SPIN
            # state.fast_mode = True                
            # if state.auto_mode:
            #     threading.Thread(target=spin, args=(False, False, True, False,), daemon=True).start()
            #     if state.fast_mode and state.last_spin is not None:
            #         if not any([state.last_spin.startswith("auto"), state.last_spin.__contains__("turbo"), state.last_spin.__contains__("hold")]):
            #             spin_in_progress.clear()
            
            # # predicted_next_10m = api_10m + (api_10m - prev_10m)
            # # predicted_delta_10m = (predicted_next_10m - prev_10m)
            # if state.auto_mode and abs(predicted_delta_10m) >= 150: # THRESHOLD
            #     state.fast_mode = True
            #     spin_in_progress.clear()
            #     # threading.Thread(target=spin, args=(False, False, True, False,), daemon=True).start()
            #     threading.Thread(target=spin, args=(False, False, False, False,), daemon=True).start()
            # elif state.auto_mode and  abs(predicted_delta_10m) >= 100: # THRESHOLD
            #     state.fast_mode = False
            #     threading.Thread(target=spin, args=(False, False, False, True,), daemon=True).start()
            
            api_signal = f"{colors['LRED']}▼{colors['RES']}" if delta < prev_delta else f"{colors['LGRE']}▲{colors['RES']}" if delta > prev_delta else f"{colors['LCYN']}◆{colors['RES']}"
            api_signal_10m = f"{colors['LRED']}▼{colors['RES']}" if delta_10m < prev_delta_10m else f"{colors['LGRE']}▲{colors['RES']}" if delta_10m > prev_delta_10m else f"{colors['LCYN']}◆{colors['RES']}"
            api_signal_1h = f"{colors['LRED']}▼{colors['RES']}" if delta_1h < prev_delta_1h else f"{colors['LGRE']}▲{colors['RES']}" if delta_1h > prev_delta_1h else f"{colors['LCYN']}◆{colors['RES']}"
            api_signal_3h = f"{colors['LRED']}▼{colors['RES']}" if delta_3h < prev_delta_3h else f"{colors['LGRE']}▲{colors['RES']}" if delta_3h > prev_delta_3h else f"{colors['LCYN']}◆{colors['RES']}"
            api_signal_6h = f"{colors['LRED']}▼{colors['RES']}" if delta_6h < prev_delta_6h else f"{colors['LGRE']}▲{colors['RES']}" if delta_6h > prev_delta_6h else f"{colors['LCYN']}◆{colors['RES']}"
            # api_signal_future = f"{colors['LRED']}⬇{colors['RES']}" if delta < prev_delta else f"{colors['LGRE']}⬆{colors['RES']}" if delta > prev_delta else f"{colors['LCYN']}◉{colors['RES']}"
            
            api_delta_signal = f"{colors['LRED']}➜{colors['RES']}" if delta < prev_delta else f"{colors['LGRE']}➜{colors['RES']}" if delta > prev_delta else f"{colors['LCYN']}➜{colors['RES']}"
            api_delta_signal_10m = f"{colors['LRED']}➜{colors['RES']}" if delta_10m < prev_delta_10m else f"{colors['LGRE']}➜{colors['RES']}" if delta_10m > prev_delta_10m else f"{colors['LCYN']}➜{colors['RES']}"
            api_delta_signal_1h = f"{colors['LRED']}➜{colors['RES']}" if delta_1h < prev_delta_1h else f"{colors['LGRE']}➜{colors['RES']}" if delta_1h > prev_delta_1h else f"{colors['LCYN']}➜{colors['RES']}"
            api_delta_signal_3h = f"{colors['LRED']}➜{colors['RES']}" if delta_3h < prev_delta_3h else f"{colors['LGRE']}➜{colors['RES']}" if delta_3h > prev_delta_3h else f"{colors['LCYN']}➜{colors['RES']}"
            api_delta_signal_6h = f"{colors['LRED']}➜{colors['RES']}" if delta_6h < prev_delta_6h else f"{colors['LGRE']}➜{colors['RES']}" if delta_6h > prev_delta_6h else f"{colors['LCYN']}➜{colors['RES']}"

            # colored_api_volume = f"{colors['BLGRE'] if (api_vol <= 30) else colors['BLCYN'] if (api_vol >= 60) else colors['BLYEL'] if (api_vol >= 90) else colors['ORA'] if (api_vol >= 120) else colors['BLRED'] if (api_vol >= 150) else colors['BLMAG'] if (api_vol >= 200) else colors['GRE']}{api_vol:.2f}{colors['RES']}"
            colored_api_volume = (
                f"{colors['BLMAG'] if api_vol >= 200 else
                   colors['BLRED'] if api_vol >= 150 else
                   colors['ORA'] if api_vol >= 120 else
                   colors['BLYEL'] if api_vol >= 90 else
                   colors['BLCYN'] if api_vol >= 50 else
                   colors['BLGRE'] if api_vol >= 10 else
                   colors['DGRY']}"
                f"{api_vol:.2f}{colors['RES']}"
            )

            # volume_signal = (
            #         f"{colors['LCYN']}◉{colors['RES']}" if round(abs(prev_api_vol) >= math.floor(abs(api_vol))) else
            #         f"{colors['LRED']}⬇{colors['RES']}" if (abs(api_vol) < abs(prev_api_vol)) else
            #         f"{colors['LGRE']}⬆{colors['RES']}" if (abs(api_vol) > abs(prev_api_vol)) else None
            #     )
            volume_signal = (
                    f"{colors['LCYN']}◉{colors['RES']}" if all([api_vol < prev_api_vol, compression, round(prev_api_vol) <= math.floor(api_vol)]) else
                    # f"{colors['LCYN']}◉{colors['RES']}" if all([api_vol > prev_api_vol, round(prev_api_vol) >= math.floor(api_vol)]) else
                    # f"{colors['LCYN']}◉{colors['RES']}" if all([api_vol < prev_api_vol, round(prev_api_vol) <= math.floor(api_vol)]) else
                    f"{colors['BLGRE']}⬆{colors['RES']}" if all([api_vol > prev_api_vol, round(ema_vol_sec, 2) >= math.floor(api_vol)]) else
                    f"{colors['BLRED']}⬇{colors['RES']}" if all([api_vol < prev_api_vol, round(ema_vol_sec, 2) <= math.floor(api_vol)]) else
                    f"{colors['GRE']}⬆{colors['RES']}" if (api_vol > prev_api_vol) else
                    f"{colors['RED']}⬇{colors['RES']}" if (api_vol < prev_api_vol) else None
                )
            
            colored_volume_sec = (
                    # f"{colors['BLGRE'] if math.floor(api_vol) > round(avg_volume_sec) else
                    #    colors['BLRED'] if math.floor(api_vol) < round(avg_volume_sec) else
                    f"{colors['BLGRE'] if all([api_vol > prev_api_vol, round(ema_vol_sec, 2) >= math.floor(api_vol)]) else
                       colors['BLRED'] if all([api_vol < prev_api_vol, round(ema_vol_sec, 2) <= math.floor(api_vol)]) else
                       colors['CYN']}"
                    f"{ema_vol_sec:.2f}{colors['RES']}"
                )
            
            blinking_volume_signal = f"{BLINK}{volume_signal}"

            # state.api_vol = f"{colored_api_volume}"
            state.api_vol = api_vol
            vol_buffer.append(ema_vol_sec)
            # if all([timer().minute % 1 == 0, timer().second == 0]):
            # if all([timer().second == 0, len(vol_buffer) >= 5, api_vol != prev_api_vol]):
            if all([timer().second == 0, current_jackpot != last_jackpot_value, len(vol_buffer) >= 5]):
                rolling_avg_vol = round(sum(vol_buffer) / len(vol_buffer), 2)
                lowest_vol = round(min(vol_buffer), 2)
                highest_vol = round(max(vol_buffer), 2)
                vol_buffer.clear()

            colored_delta_volume_signal = (
                    f"{colors['LRED']}▼{colors['RES']}" if (api_vol < prev_api_vol) else
                    f"{colors['LGRE']}▲{colors['RES']}" if (api_vol > prev_api_vol) else
                    f"{colors['LCYN']}◆{colors['RES']}"
                )
            
            colored_delta_volume = (
                    f"{colors['BLGRE'] if any([api_vol_delta >= 100 and explosion, api_vol_delta >= 100 and polarity_flip]) else
                       colors['BLRED'] if any([api_vol_delta <= -100 and explosion, api_vol_delta <= -100 and polarity_flip]) else
                       colors['LGRE'] if (api_vol_delta >= 100) else
                       colors['LRED'] if (api_vol_delta <= -100) else
                       colors['GRE'] if (api_vol_delta > 0) else
                       colors['RED'] if (api_vol_delta < 0) else
                       colors['CYN']}"
                    f"{api_vol_delta:+.2f}{colors['RES']}"
                )

            colored_low_volume = (
                f"{colors['BLMAG'] if lowest_vol >= 200 else
                   colors['BLRED'] if lowest_vol >= 150 else
                   colors['ORA'] if lowest_vol >= 120 else
                   colors['BLYEL'] if lowest_vol >= 90 else
                   colors['BLCYN'] if lowest_vol >= 50 else
                   colors['BLGRE'] if lowest_vol >= 10 else
                   colors['DGRY']}"
                f"{lowest_vol:.2f}{colors['RES']}"
            )

            colored_high_volume = (
                f"{colors['BLMAG'] if highest_vol >= 200 else
                   colors['BLRED'] if highest_vol >= 150 else
                   colors['ORA'] if highest_vol >= 120 else
                   colors['BLYEL'] if highest_vol >= 90 else
                   colors['BLCYN'] if highest_vol >= 50 else
                   colors['BLGRE'] if highest_vol >= 10 else
                   colors['DGRY']}"
                f"{highest_vol:.2f}{colors['RES']}"
            )

            colored_avg_volume = (
                f"{colors['BLMAG'] if rolling_avg_vol >= 200 else
                   colors['BLRED'] if rolling_avg_vol >= 150 else
                   colors['ORA'] if rolling_avg_vol >= 120 else
                   colors['BLYEL'] if rolling_avg_vol >= 90 else
                   colors['BLCYN'] if rolling_avg_vol >= 50 else
                   colors['BLGRE'] if rolling_avg_vol >= 10 else
                   colors['DGRY']}"
                f"{rolling_avg_vol:.2f}{colors['RES']}"
            )
            
            diff_delta_volume = f"{colors['WHTE']}({colors['LMAG']}Δ{colors['DGRY']}:{colored_delta_volume}{colors['WHTE']}) {colored_delta_volume_signal}"
            
            # colored_volatility_sec = f"{colors['YEL'] if (avg_volatility_sec <= 10) else colors['ORA'] if (avg_volatility_sec >= 80 and avg_volatility_sec < 100) else colors['RED'] if (avg_volatility_sec >= 100) else colors['GRE']}{avg_volatility_sec:.2f}{colors['RES']}"
            # colored_volatility_sec = (
            #         f"{colors['BLCYN'] if round(abs(avg_volatility_sec)) <= math.floor(volatility_score) else
            #            colors['YEL'] if (abs(avg_volatility_sec) <= 10) else
            #            colors['ORA'] if (abs(avg_volatility_sec) >= 80 and abs(avg_volatility_sec) < 100) else
            #            colors['RED'] if (abs(avg_volatility_sec) >= 100) else
            #            colors['GRE']}"
            #         f"{abs(avg_volatility_sec):.2f}{colors['RES']}"
            #     )
            
            colored_volatility_sec = (
                f"{colors['BLRED'] if all([volatility_score > prev_volatility, abs(round(avg_volatility_sec)) >= math.floor(volatility_score)]) else
                   colors['BLRED'] if all([volatility_score < prev_volatility, abs(round(avg_volatility_sec)) <= math.floor(volatility_score)]) else
                   colors['CYN']}"
                f"{abs(avg_volatility_sec):.2f}{colors['RES']}"
            )
            
            # colored_prev_volatility_sec = f"{colors['YEL'] if (prev_avg_volatility_sec <= 10) else colors['ORA'] if (prev_avg_volatility_sec >= 80 and prev_avg_volatility_sec < 100) else colors['RED'] if (prev_avg_volatility_sec >= 100) else colors['GRE']}{prev_avg_volatility_sec:.2f}{colors['RES']}"
            # volatility_sec_signal = f"{colors['LRED']}➜{colors['RES']}" if (avg_volatility_sec < prev_avg_volatility_sec) else f"{colors['LGRE']}➜{colors['RES']}" if (avg_volatility_sec > prev_avg_volatility_sec) else f"{colors['LCYN']}➜{colors['RES']}"
            # diff_volatility_sec = f"{colors['WHTE']}({colored_prev_volatility_sec} {volatility_sec_signal} {colored_volatility_sec}{colors['WHTE']}){colors['RES']}"
            # volatility_signal = f"{colors['LRED']}⬇{colors['RES']}" if (avg_volatility_sec < prev_avg_volatility_sec) else f"{colors['LGRE']}⬆{colors['RES']}" if (avg_volatility_sec > prev_avg_volatility_sec) else f"{colors['LCYN']}◉{colors['RES']}"

            # volatility_sec_diff_delta = f"{colors['RED'] if (prev_avg_volatility_sec - avg_volatility_sec) < 0 else colors['GRE'] if (prev_avg_volatility_sec - avg_volatility_sec) > 0 else colors['LCYN']}{(prev_avg_volatility_sec - avg_volatility_sec):+.2f}"            
            # diff_volatility_sec = f"{colors['WHTE']}({colors['LMAG']}Δ{colors['DGRY']}:{volatility_sec_diff_delta}{colors['WHTE']}){colors['RES']}"         

            # volatility_signal = (
            #         f"{colors['LCYN']}◉{colors['RES']}" if abs(round(avg_volatility_sec)) <= math.floor(volatility_score) else
            #         f"{colors['LRED']}⬇{colors['RES']}" if (abs(avg_volatility_sec) < abs(prev_avg_volatility_sec)) else
            #         f"{colors['LGRE']}⬆{colors['RES']}" if (abs(avg_volatility_sec) > abs(prev_avg_volatility_sec)) else None
            #     )
            
            volatility_signal = (
                f"{colors['LCYN']}◉{colors['RES']}" if all([volatility_score < prev_volatility, abs(round(avg_volatility_sec)) <= math.floor(volatility_score)]) else
                f"{colors['BLGRE']}⬆{colors['RES']}" if all([volatility_score > prev_volatility, abs(round(avg_volatility_sec)) >= math.floor(volatility_score)]) else
                f"{colors['BLRED']}⬇{colors['RES']}" if all([volatility_score < prev_volatility, abs(round(avg_volatility_sec)) <= math.floor(volatility_score)]) else
                f"{colors['GRE']}⬆{colors['RES']}" if (volatility_score > prev_volatility) else
                f"{colors['RED']}⬇{colors['RES']}" if (volatility_score < prev_volatility) else None
            )
            
            blinking_volatility_signal = f"{BLINK}{volatility_signal}"
            colored_delta_volatility_signal = f"{colors['LRED']}▼{colors['RES']}" if (volatility_score < prev_api_vol) else f"{colors['LGRE']}▲{colors['RES']}" if (volatility_score > prev_volatility) else f"{colors['LCYN']}◆{colors['RES']}"
            colored_delta_volatility = f"{colors['RED'] if (volatility_delta < 0) else colors['GRE'] if (volatility_delta > 0) else colors['CYN']}{volatility_delta:+.2f}{colors['RES']}"
            diff_delta_volatility = f"{colors['WHTE']}({colors['LMAG']}Δ{colors['DGRY']}:{colored_delta_volatility}{colors['WHTE']}) {colored_delta_volatility_signal}"
            colored_predicted_delta_sec = f"{colors['BLCYN'] if math.floor(abs(predicted_delta_10m)) <= round(abs(avg_predicted_delta_sec)) else colors['YEL'] if (abs(avg_predicted_delta_sec) <= 10) else colors['ORA'] if (abs(avg_predicted_delta_sec) >= 80 and abs(avg_predicted_delta_sec) < 100) else colors['RED'] if (abs(avg_predicted_delta_sec) >= 100) else colors['GRE']}{abs(avg_predicted_delta_sec):.2f}{colors['RES']}"
            # colored_prev_predicted_delta_sec = f"{colors['YEL'] if (abs(prev_avg_predicted_delta_sec) <= 10) else colors['ORA'] if (abs(prev_avg_predicted_delta_sec) >= 80 and abs(prev_avg_predicted_delta_sec) < 100) else colors['RED'] if (abs(prev_avg_predicted_delta_sec) >= 100) else colors['GRE']}{abs(prev_avg_predicted_delta_sec):.2f}{colors['RES']}"
            
            # predicted_delta_sec_signal = f"{colors['LRED']}➜{colors['RES']}" if (abs(avg_predicted_delta_sec) < abs(prev_avg_predicted_delta_sec)) else f"{colors['LGRE']}➜{colors['RES']}" if (abs(avg_predicted_delta_sec) > abs(prev_avg_predicted_delta_sec)) else f"{colors['LCYN']}➜{colors['RES']}"
            # predicted_delta_sec_diff_delta = f"{colors['RED'] if (prev_avg_predicted_delta_sec - avg_predicted_delta_sec) < 0 else colors['GRE'] if (prev_avg_predicted_delta_sec - avg_predicted_delta_sec) > 0 else colors['LCYN']}{(prev_avg_predicted_delta_sec - avg_predicted_delta_sec):+.2f}"
            # diff_predicted_delta_sec = f"{colors['WHTE']}({colored_prev_predicted_delta_sec} {predicted_delta_sec_signal} {colored_predicted_delta_sec}{colors['WHTE']}){colors['RES']}"
            # diff_predicted_delta_sec = f"{colors['WHTE']}({colors['LMAG']}Δ{colors['DGRY']}:{predicted_delta_sec_diff_delta}{colors['WHTE']}){colors['RES']}"

            predicted_signal = (
                f"{colors['LCYN']}◉{colors['RES']}" if all([predicted_delta_10m > prev_predicted_delta,abs(round(avg_predicted_delta_sec)) >= math.floor(predicted_delta_10m)]) else
                f"{colors['LCYN']}◉{colors['RES']}" if all([predicted_delta_10m < prev_predicted_delta,abs(round(avg_predicted_delta_sec)) <= math.floor(predicted_delta_10m)]) else
                # f"{colors['LCYN']}◉{colors['RES']}" if abs(round(avg_predicted_delta_sec)) >= math.floor(predicted_delta_10m) else
                f"{colors['LRED']}⬇{colors['RES']}" if (abs(avg_predicted_delta_sec) < abs(round(prev_avg_predicted_delta_sec))) else
                f"{colors['LGRE']}⬆{colors['RES']}" if (abs(avg_predicted_delta_sec) > abs(round(prev_avg_predicted_delta_sec))) else None
            )
            
            blinking_predicted_signal = f"{BLINK}{predicted_signal}"
            colored_delta_predicted_delta_signal = f"{colors['LRED']}▼{colors['RES']}" if (predicted_delta_10m < prev_predicted_delta) else f"{colors['LGRE']}▲{colors['RES']}" if (predicted_delta_10m > prev_predicted_delta) else f"{colors['LCYN']}◆{colors['RES']}"
            colored_delta_predicted_delta = f"{colors['RED'] if (predicted_delta_10m < 0) else colors['GRE'] if (predicted_delta_10m > 0) else colors['CYN']}{predicted_delta_10m:+.2f}{colors['RES']}"
            diff_delta_predicted_delta = f"{colors['WHTE']}({colors['LMAG']}Δ{colors['DGRY']}:{colored_delta_predicted_delta}{colors['WHTE']}) {colored_delta_predicted_delta_signal}"
            colored_predicted_delta_sec = (
                f"{colors['BLCYN'] if abs(round(avg_predicted_delta_sec)) >= math.floor(abs(predicted_delta_10m)) else
                    colors['YEL'] if (abs(avg_predicted_delta_sec) <= 10) else
                    colors['ORA'] if (abs(avg_predicted_delta_sec) >= 80 and abs(avg_predicted_delta_sec) < 100) else
                    colors['RED'] if (abs(avg_predicted_delta_sec) >= 100) else
                    colors['GRE']}"
                f"{abs(avg_predicted_delta_sec):.2f}{colors['RES']}"
            )
            
            # api_sign_10m = f"{colors['GRE']}+{colors['RES']}" if delta_10m > 0 else ""
            
            colored_api_10m = f"{colors['RED'] if api_10m < 0 else colors['GRE'] if api_10m > 0 else colors['LCYN']}{api_10m:.2f}{colors['RES']}"
            colored_api_1h = f"{colors['RED'] if api_1h < 0 else colors['GRE'] if api_1h > 0 else colors['LCYN']}{api_1h:.2f}{colors['RES']}"
            colored_api_3h = f"{colors['RED'] if api_3h < 0 else colors['GRE'] if api_3h > 0 else colors['LCYN']}{api_3h:.2f}{colors['RES']}"
            colored_api_6h = f"{colors['RED'] if api_6h < 0 else colors['GRE'] if api_6h > 0 else colors['LCYN']}{api_6h:.2f}{colors['RES']}"
            
            colored_current = f"{colors['RED'] if current_jackpot < prev_jackpot else colors['GRE']}{current_jackpot:.2f}{colors['RES']}"            
            # colored_prev = f"{colors['RED'] if prev_jackpot < current_jackpot else colors['GRE']}{prev_jackpot:.2f}{colors['RES']}"
            # colored_prev_10m = f"{colors['RED'] if prev_10m < 0 else colors['GRE'] if prev_10m > 0 else colors['LCYN']}{prev_10m:.2f}{colors['RES']}"
            # colored_prev_1h = f"{colors['RED'] if prev_1h < 0 else colors['GRE'] if prev_1h > 0 else colors['LCYN']}{prev_1h:.2f}{colors['RES']}"
            # colored_prev_3h = f"{colors['RED'] if prev_3h < 0 else colors['GRE'] if prev_3h > 0 else colors['LCYN']}{prev_3h:.2f}{colors['RES']}"
            # colored_prev_6h = f"{colors['RED'] if prev_6h < 0 else colors['GRE'] if prev_6h > 0 else colors['LCYN']}{prev_6h:.2f}{colors['RES']}"
            
            colored_prev_delta = f"{colors['RED'] if prev_delta < 0 else colors['GRE'] if prev_delta > 0 else colors['CYN']}{prev_delta:+.2f}{colors['RES']}"
            colored_prev_delta_10m = f"{colors['RED'] if prev_delta_10m < 0 else colors['GRE'] if prev_delta_10m > 0 else colors['CYN']}{prev_delta_10m:+.2f}{colors['RES']}"
            colored_prev_delta_1h = f"{colors['RED'] if prev_delta_1h < 0 else colors['GRE'] if prev_delta_1h > 0 else colors['CYN']}{prev_delta_1h:+.2f}{colors['RES']}"
            colored_prev_delta_3h = f"{colors['RED'] if prev_delta_3h < 0 else colors['GRE'] if prev_delta_3h > 0 else colors['CYN']}{prev_delta_3h:+.2f}{colors['RES']}"
            colored_prev_delta_6h = f"{colors['RED'] if prev_delta_6h < 0 else colors['GRE'] if prev_delta_6h > 0 else colors['CYN']}{prev_delta_6h:+.2f}{colors['RES']}"
            
            colored_delta = f"{colors['RED'] if delta < 0 else colors['GRE'] if delta > 0 else colors['CYN']}{delta:+.2f}{colors['RES']}"
            colored_delta_10m = f"{colors['RED'] if delta_10m < 0 else colors['GRE'] if delta_10m > 0 else colors['CYN']}{delta_10m:+.2f}{colors['RES']}"
            colored_delta_1h = f"{colors['RED'] if delta_1h < 0 else colors['GRE'] if delta_1h > 0 else colors['CYN']}{delta_1h:+.2f}{colors['RES']}"
            colored_delta_3h = f"{colors['RED'] if delta_3h < 0 else colors['GRE'] if delta_3h > 0 else colors['CYN']}{delta_3h:+.2f}{colors['RES']}"
            colored_delta_6h = f"{colors['RED'] if delta_6h < 0 else colors['GRE'] if delta_6h > 0 else colors['CYN']}{delta_6h:+.2f}{colors['RES']}"
            colored_delta_shift = f"{colors['RED'] if delta_shift < 0 else colors['GRE'] if delta_shift > 0 else colors['CYN']}{delta_shift:+.2f}{colors['RES']}"
            colored_delta_shift_10m = f"{colors['RED'] if delta_shift_10m < 0 else colors['GRE'] if delta_shift_10m > 0 else colors['CYN']}{delta_shift_10m:+.2f}{colors['RES']}"
            colored_delta_shift_1h = f"{colors['RED'] if delta_shift_1h < 0 else colors['GRE'] if delta_shift_1h > 0 else colors['CYN']}{delta_shift_1h:+.2f}{colors['RES']}"
            colored_delta_shift_3h = f"{colors['RED'] if delta_shift_3h < 0 else colors['GRE'] if delta_shift_3h > 0 else colors['CYN']}{delta_shift_3h:+.2f}{colors['RES']}"
            colored_delta_shift_6h = f"{colors['RED'] if delta_shift_6h < 0 else colors['GRE'] if delta_shift_6h > 0 else colors['CYN']}{delta_shift_6h:+.2f}{colors['RES']}"
            
            jackpot_bar = get_jackpot_bar(current_jackpot, meter_color)
            percent = f"{colors['WHTE']}%{colors['RES']}"
            
            # diff = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev} {percent}{colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta} {percent})"
            # diff_10m = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev_10m} {percent} {colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta_10m} {percent})"
            # diff_1h = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev_1h} {percent}{colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta_1h} {percent})"
            # diff_3h = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev_3h} {percent}{colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta_3h} {percent})"
            # diff_6h = f"({colors['YEL']}Prev{colors['DGRY']}: {colored_prev_6h} {percent}{colors['DGRY']}, {colors['LMAG']}Δ{colors['DGRY']}: {colored_delta_6h} {percent})"
            
            diff = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta} {api_delta_signal} {colored_delta})"
            diff_10m = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta_10m} {api_delta_signal_10m} {colored_delta_10m})"
            diff_1h = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta_1h} {api_delta_signal_1h} {colored_delta_1h})"
            diff_3h = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta_3h} {api_delta_signal_3h} {colored_delta_3h})"
            diff_6h = f"({colors['LMAG']}Δ{colors['DGRY']}:{colored_prev_delta_6h} {api_delta_signal_6h} {colored_delta_6h})"
            
            colored_session = f"{colors['ORA'] if session_mode == "HOT" else colors['YEL'] if session_mode == "WARM" else colors['LCYN'] if session_mode == "COLD" else colors['WHTE'] if session_mode == "DRAIN" else colors['GRE']}{session_mode}{colors['RES']}"
            colored_shocked = f"{colors['ORA'] if shock_state == "SNAP" else colors['YEL'] if shock_state == "RELIEF" else colors['LCYN'] if shock_state == "CALM" else colors['GRE']}{shock_state}{colors['RES']}"

            bet_lvl = (
                f"{colors['BLMAG']}HIGH{colors['RES']}" if all([api_vol >= 200, session_mode == "HOT"]) or all([api_vol >= 200, abs(api_vol_delta) >= 100]) else
                f"{colors['BLRED']}MID{colors['RES']}" if all([api_vol >= 120, session_mode == "HOT"]) or all([api_vol >= 120, abs(api_vol_delta) >= 100]) else
                f"{colors['BLYEL']}LOW{colors['RES']}" if all([api_vol >= 80, session_mode == "HOT"]) or all([api_vol >= 80, abs(api_vol_delta) >= 100]) else
                f"{colors['DGRY']}Don't Bet{colors['RES']}"
            )

            colored_predicted_delta = f"{colors['LMAG']}Δ{colors['WHTE']:<7}Predicted{colors['RES']:<6}:\t{colors['LYEL'] if (abs(predicted_delta_10m) <= 10) else colors['ORA'] if (abs(predicted_delta_10m) >= 80 and abs(predicted_delta_10m) < 100) else colors['LMAG'] if (abs(predicted_delta_10m) >= 100) else colors['LGRE']}{abs(predicted_delta_10m):.2f}{colors['RES']}\t{blinking_predicted_signal}   {colored_predicted_delta_sec:<10}   {diff_delta_predicted_delta}"
            colored_volatility = f"💤{colors['WHTE']:<6}Volatility{colors['RES']:<5}:\t{colors['LYEL'] if (volatility_score <= 10) else colors['ORA'] if (volatility_score >= 80 and volatility_score < 100) else colors['LRED'] if (volatility_score >= 100) else colors['LGRE']}{volatility_score:.2f}{colors['RES']}\t{blinking_volatility_signal}   {colored_volatility_sec:<9}   {diff_delta_volatility}"
            colored_volume = f"🧪{colors['WHTE']:<6}Volume{colors['RES']:<9}:\t{colored_api_volume}\t{blinking_volume_signal}   {colored_volume_sec:<7}   {diff_delta_volume}   {colors['DGRY']}Avg{colors['WHTE']}|{colors['DGRY']}Low{colors['WHTE']}|{colors['DGRY']}High{colors['RES']}: {colored_avg_volume}{colors['WHTE']}|{colored_low_volume}{colors['WHTE']}|{colored_high_volume}"

            colored_rtp = (
                f"{colors['BLGRE']}⬆ {state.rtp_val}{colors['RES']}" if state.rtp else
                f"{colors['BLRED']}⬇ {state.rtp_val}{colors['RES']}" if not state.rtp else
                f"{colors['LCYN']}◉ {state.rtp_val}{colors['RES']}"
            )

            # colored_delta_avg_predicted_delta_signal = f"{colors['LRED']}▼{colors['RES']}" if (abs(avg_predicted_delta) < abs(prev_avg_predicted_delta)) else f"{colors['LGRE']}▲{colors['RES']}" if (abs(avg_predicted_delta) > abs(prev_avg_predicted_delta)) else f"{colors['LCYN']}◆{colors['RES']}"
            # colored_delta_avg_predicted_delta = f"{colors['RED'] if (delta_avg_predicted_delta < 0) else colors['GRE'] if (delta_avg_predicted_delta > 0) else colors['CYN']}{delta_avg_predicted_delta:+.2f}{colors['RES']}"
            # diff_delta_avg_predicted_delta = f"{colors['WHTE']}({colors['LMAG']}Δ{colors['DGRY']}:{colored_delta_avg_predicted_delta}{colors['WHTE']}) {colored_delta_avg_predicted_delta_signal}"

            
            # volatility_trigger = (
            #     f"{math.floor(volatility_score)} >= {round(abs(avg_volatility_sec))} "
            #     f"{colors['RED'] if math.floor(volatility_score) >= round(abs(avg_volatility_sec)) else colors['RES']}"
            #     f"{math.floor(volatility_score) >= round(abs(avg_volatility_sec))}"
            #     f"{colors['RES']}"
            # )
            
            # volatility_check = (
            #     f"{avg_volatility_sec} > {prev_avg_volatility_sec} "
            #     f"{colors['RED'] if avg_volatility_sec > prev_avg_volatility_sec else colors['RES']}"
            #     f"{avg_volatility_sec > prev_avg_volatility_sec}"
            #     f"{colors['RES']}"
            # )
            
            # predicted_delta_check = (
            #     f"{abs(delta_avg_predicted_delta)} > {DELTA_THRESHOLD} "
            #     f"{colors['RED'] if abs(delta_avg_predicted_delta) > DELTA_THRESHOLD else colors['RES']}"
            #     f"{abs(delta_avg_predicted_delta) > DELTA_THRESHOLD}"
            #     f"{colors['RES']}"
            # )

            colored_direction = (
                f"{colors['BLGRE']}{direction.upper()}{colors['RES']}" if direction == "bullish" else
                f"{colors['BLRED']}{direction.upper()}{colors['RES']}" if direction == "bearish" else
                f"{colors['BLMAG']}{direction.upper()}{colors['RES']}" if direction == "reversal" else
                f"{colors['BLBLU']}{direction.upper()}{colors['RES']}"
            )
            
            message = (
                f"\n\t🎰 {colors['LMAG']}API Meter{colors['RES']}: {colored_current} {percent} {diff} {api_signal} {colored_delta_shift} {colored_session} {f"{colors['BLNK']}🔥🔥🔥{colors['RES']} {colors['YEL']}{hot_seconds:.2f}{colors['RES']}" if session_mode == "HOT" else ''}\n"
                f"\n\t{jackpot_bar} {colored_shocked} {f"({colors['WHTE']}Last Drain{colors['RES']}: {colors['YEL']}{drain_seconds:.0f}{colors['RES']}) {colors['DGRY']}secs elapsed{colors['RES']}" if session_mode != "HOT" and drain_seconds > 0 else ''}"
                f"{f'{colors['BLNK']}🌀{colors['RES']} ' if any(x in colored_shocked for x in ['SNAP', 'RELIEF']) else ''}\n"
                f"\n\t{colors['CYN']}⏱{colors['RES']} {colors['LYEL']}10m{colors['RES']}:  {colored_api_10m} {percent} {diff_10m} {api_signal_10m} {colored_delta_shift_10m}"
                f"\n\t{colors['CYN']}⏱{colors['RES']} {colors['LYEL']}1hr{colors['RES']}:  {colored_api_1h} {percent} {diff_1h} {api_signal_1h} {colored_delta_shift_1h}"
                f"\n\t{colors['CYN']}⏱{colors['RES']} {colors['LYEL']}3hr{colors['RES']}:  {colored_api_3h} {percent} {diff_3h} {api_signal_3h} {colored_delta_shift_3h}"
                f"\n\t{colors['CYN']}⏱{colors['RES']} {colors['LYEL']}6hr{colors['RES']}:  {colored_api_6h} {percent} {diff_6h} {api_signal_6h} {colored_delta_shift_6h}\n"
                f"\n\t{colored_predicted_delta}"
                f"\n\t{colored_volatility}"
                f"\n\t{colored_volume}\n"
                # f"\n\t{colors['WHTE']}Bet Level{colors['RES']}: {bet_lvl}{f'\t{colors['WHTE']}Last Spin{colors['RES']}: {f'{colors['BRED']}' + state.last_spin.replace('_', ' ').title() + f' {colors['BLNK']}🌀{colors['RES']}' if all([state.last_spin is not None, state.auto_mode]) else ''}'"
                f"\n\t{colors['WHTE']}Bet Level{colors['RES']}: {bet_lvl:<17} {colors['WHTE']}Avg Data/Sec{colors['RES']}: {new_data_seconds:<21}    {colors['WHTE']}RTP {colors['RES']}: {colored_rtp}  {colors['WHTE']}Direction{colors['RES']}: {colored_direction} {colors['RES']}"
                # f"\n\t{colors['WHTE']}Last Trigger{colors['RES']}: {state.last_trigger}\n"
                # f"\n\t{colors['WHTE']}Volatility Trigger{colors['RES']}: {volatility_trigger}\n"
                # f"\n\t{colors['WHTE']}Volatility Check{colors['RES']}: {volatility_check}\n"
                # f"\n\t{colors['WHTE']}Predicted Delta Check{colors['RES']}: {predicted_delta_check}\n"
                # f"\n\t{colors['WHTE']}Shock State Count (sec){colors['RES']}: {colors['GRE']}LOADED{colors['WHTE']}:{colors['MAG']}{loaded} {colors['LCYN']}CALM{colors['WHTE']}:{colors['MAG']}{calm} {colors['YEL']}RELIEF{colors['WHTE']}:{colors['MAG']}{relief} {colors['ORA']}SNAP{colors['WHTE']}:{colors['MAG']}{snap}{colors['RES']}"
            )

            # if current_jackpot != last_jackpot_value:
            # if all([api_vol != prev_api_vol, api_vol_delta != last_api_vol_delta]):
                # state.api_vol_signal = new_signal

            if all([state.rtp != state.last_rtp, state.rtp is not None]):
                if state.last_rtp is not None:
                    alert_queue.put(f"rtp {'up 'if state.rtp else 'down'}")
                    already_alerted.add(state.rtp)
                state.last_rtp = state.rtp

            if all([current_jackpot != last_jackpot_value, api_vol_delta != last_api_vol_delta]):
                if direction is not None:
                    alert_queue.put("tink") if direction == "bullish" else alert_queue.put("ping") if direction == "bearish" else alert_queue.put("reversal") if direction == "reversal" else alert_queue.put("trap")
                    already_alerted.add(new_signal)

                if session_mode in ["HOT", "DRAIN", "LOADED"]:
                    alert_queue.put(session_mode)
                    already_alerted.add(session_mode)
            
            last_delta_value = delta
            last_delta_10m_value = delta_10m
            last_delta_1h_value = delta_1h
            last_delta_3h_value = delta_3h
            last_delta_6h_value = delta_6h
            
            last_jackpot_value = current_jackpot
            last_10m_value = api_10m
            last_1h_value = api_1h
            last_3h_value = api_3h
            last_6h_value = api_6h
            
            last_api_vol = api_vol
            last_api_vol_delta = api_vol_delta
            last_volatility = volatility_score
            last_volatility_delta = volatility_delta
            last_predicted_delta = predicted_delta_10m
            last_predicted_delta_delta = predicted_delta_delta

            # last_avg_volume_sec = avg_volume_sec
            last_avg_volatility_sec = avg_volatility_sec
            # last_avg_predicted_delta = avg_predicted_delta
            last_avg_predicted_delta_sec = avg_predicted_delta_sec
            
            log_message("info", message, overwrite=True, _overlay_key="api_data")
            stop_event.wait(0.5)
        except Exception as e:
            log_message("error", f"[fetch_api_data] {e}", overwrite=True, _overlay_key="api_data")
            time.sleep(0.5)

def get_game_name(game_id):
    if not game_id:
        return "No ID"

    try:
        game = db["GAME"].find_one({"id": int(game_id)})
    except:
        game = None

    if not game:
        return f"Unknown ({game_id})"

    return game.get("name", f"Game {game_id}")

def fetch_rtp_data():
    prev_top_rtp_val = prev_top_rtp = prev_total_bet = None
    last_top_rtp_val = last_top_rtp = last_total_bet = None
    rtp_history = { "Hot": {}, "Recommended": {} }
    elapsed_tracker = {}
    active_condition_ids = set()

    while not stop_event.is_set():        
        try:
            rtp_data_raw = r.get("rtp_data")

            if not rtp_data_raw:
                time.sleep(0.5)
                continue

            rtp_data = json.loads(rtp_data_raw)

            # -------------------------
            # TOP
            # -------------------------
            top_now = time.time()
            top = rtp_data.get("top", {})
            top_id = top.get("game_id")
            top_name = get_game_name(top_id)
            top_rtp = top.get("up")
            top_rtp_val = str_to_float(top.get('rtp', '0'))

            if top_name.lower() == game["name"].lower():
                state.rtp = top_rtp
                state.rtp_val = top_rtp_val

            top_name_display = (
                f'{colors["BLNK"]}{colors["BLYEL"]}{top_name}{colors["RES"]}'
                if top_name.lower() == game["name"].lower()
                else (
                    f'{colors["ORA"]}{top_name}{colors["RES"]}'
                    if abs(top_rtp_val) >= 100
                    else f'{colors["YEL"]}{top_name}{colors["RES"]}'
                )
            )
            # top_rtp_display = (
            #     f"{colors['LGRE']}⬆ {colors['GRE']}{top.get('rtp', '')}{colors['RES']}"
            #     if top.get("up") is True
            #     else f"{colors['LRED']}⬇ {colors['RED'] if float(top.get('rtp','0').replace('RTP:','').replace('%','')) <= 100 else colors['BLNK']}{top.get('rtp','')}{colors['RES']}"
            # )
            total_bet = top.get("total_bet")

            prev_top_rtp_val = 0.0 if prev_top_rtp_val is None else last_top_rtp_val if (top_rtp_val != last_top_rtp_val) else prev_top_rtp_val
            prev_top_rtp = None if prev_top_rtp_val is None else last_top_rtp if (top_rtp_val != last_top_rtp_val) else prev_top_rtp
            prev_total_bet = None if prev_top_rtp_val is None else last_total_bet if (total_bet != last_total_bet) else prev_total_bet

            # if abs(top_rtp_val) >= 100:
            active_condition_ids.add(top_id)

            if top_id not in elapsed_tracker:
                elapsed_tracker[top_id] = top_now

            elapsed = int(top_now - elapsed_tracker[top_id])
            mins, secs = divmod(elapsed, 60)
            elapsed_str = f"{colors['BLU']}⏱ {colors['LGRE'] if top_rtp else colors['LRED']}{mins:02d}:{secs:02d}{colors['RES']}"

            # else:
            #     elapsed_str = None

            top_blinking = colors['BLNK'] if (top_rtp and top_rtp_val >= 99) else ""
            top_color = colors['RED'] if not top_rtp else colors['GRE']
            top_direction = f"{top_blinking}{colors['LRED']}⬇{colors['RES']}" if not top_rtp else f"{top_blinking}{colors['LGRE']}⬆{colors['RES']}"
            top_signal = f"{colors['LCYN']}◆{colors['RES']}" if prev_top_rtp is None else f"{colors['LRED']}▼{colors['RES']}" if top_rtp_val < prev_top_rtp_val else f"{colors['LGRE']}▲{colors['RES']}" if top_rtp_val > prev_top_rtp_val else f"{colors['LCYN']}◆{colors['RES']}"
            total_bet_signal = f"{colors['LCYN']}◆{colors['RES']}" if prev_total_bet is None else f"{colors['LRED']}▼{colors['RES']}" if total_bet < prev_total_bet else f"{colors['LGRE']}▲{colors['RES']}" if total_bet > prev_total_bet else f"{colors['LCYN']}◆{colors['RES']}"

            top_rtp_display = f"{top_blinking}{top_direction} {top_color}{top_rtp_val} {colors['WHTE']}%{colors['RES']}"

            # if elapsed_str:
            #     top_rtp_display = f"{top_blinking}{top_direction} {top_color}{top_rtp_val} {colors['WHTE']}%{colors['RES']} {colors['BLU']}⏱ {colors['ORA']}{elapsed_str}{colors['RES']}"
            # else:
            #     top_rtp_display = f"{top_blinking}{top_direction} {top_color}{top_rtp_val} {colors['WHTE']}%{colors['RES']}"

            prev_top_color =  colors['RED'] if (not prev_top_rtp and prev_top_rtp_val != 0.0) else colors['GRE'] if (prev_top_rtp and prev_top_rtp_val != 0.0) else colors['CYN']
            prev_top_direction = f"{colors['LRED']}⬇{colors['RES']}" if (not prev_top_rtp and prev_top_rtp_val != 0.0) else f"{colors['LGRE']}⬆{colors['RES']}" if (prev_top_rtp and prev_top_rtp_val != 0.0) else f"{colors['LCYN']}◉{colors['RES']}"
            prev_top_rtp_display = f"{colors['LYEL']}({prev_top_direction} {prev_top_color}{prev_top_rtp_val} {colors['WHTE']}%{colors['LYEL']}){colors['RES']} {elapsed_str}{colors['RES']}"

            # if top_rtp_num >= 100 and top.get("up") is True:
            #     active_condition_ids.add(top_id)

            # if top_id not in elapsed_tracker:
            #     elapsed_tracker[top_id] = top_now

            #     elapsed = int(top_now - elapsed_tracker[top_id])
            #     mins, secs = divmod(elapsed, 60)
            #     elapsed_str = f"{mins:02d}:{secs:02d}"
            # else:
            #     elapsed_str = None
                
            # if top.get("up") is False and elapsed_str:
            #     top_rtp_display += f" {colors['WHTE']}({colors['YEL']}{elapsed_str}{colors['WHTE']}){colors['RES']}"

            message = (
                f"\n{colors['WHTE']}RTP{colors['RES']}:"
                f"\t[{colors['LCYN']}Top{colors['RES']}]\t{colors['WHTE']}- {top_name_display} "
                f"{top_rtp_display} {top_signal} {prev_top_rtp_display} {colors['WHTE']}| {colors['BLGRE']}₱ {colors['BLMAG']}{total_bet} {total_bet_signal}{colors['RES']}\n"
            )

            # -------------------------
            # LISTS
            # -------------------------
            lists = rtp_data.get("lists", [])

            if not lists:
                message += f"\n\t\t\tNo lists found\n"

            for section in lists:
                title = section.get("title", "Unknown")
                games = section.get("games", [])

                message += f"\t[{colors['LCYN']}{title}{colors['RES']}]\n"

                if not games:
                    message += "\t\t\t  (empty)\n"
                    continue

                def format_game(g):
                    now = time.time()

                    try:
                        gid = g.get("game_id")
                        name = get_game_name(gid)

                        if not name:
                            log_message("error", f"Missing game name for gid={gid} {e}")
                        ...
                    except Exception as e:
                        log_message("error", f"format_game crash gid={g.get('game_id')} {e}")
                        raise

                    rtp_val = str_to_float(g.get("rtp", "").replace("RTP:", "").replace("%", ""))
                    section_history = rtp_history.setdefault(title, {})

                    # initialize game history
                    if gid not in section_history:
                        section_history[gid] = {
                            "last_rtp_val": None,
                            "prev_rtp_val": 0.0,
                            "last_rtp": None,
                            "prev_rtp": None,
                        }

                    hist = section_history[gid]
                    last_rtp_val = hist["last_rtp_val"]
                    prev_rtp_val = hist["prev_rtp_val"]
                    last_rtp = hist["last_rtp"]
                    prev_rtp = hist["prev_rtp"]

                    # only shift if changed
                    if last_rtp_val is not None and rtp_val != last_rtp_val:
                        prev_rtp_val = last_rtp_val
                        prev_rtp = last_rtp

                    # update current values
                    hist["last_rtp_val"] = rtp_val
                    hist["last_rtp"] = g.get("rtp")

                    hist["prev_rtp_val"] = prev_rtp_val
                    hist["prev_rtp"] = prev_rtp

                    # highlight selected game
                    if name.lower() == game["name"].lower():
                        if title == "Hot":
                            state.rtp = g.get("up")
                            state.rtp_val = rtp_val

                        if all([state.hit_win, state.session_mode == "HOT"]):
                            name_display = f"{colors['BLNK']}{colors['BLYEL']}{name}{colors['RES']}"
                        else:
                            name_display = f"{colors['BLYEL']}{name}{colors['RES']}"
                    else:
                        name_display = f"{colors['ORA'] if abs(rtp_val) >= 100 else colors['DGRY']}{name}{colors['RES']}"

                    # if abs(rtp_val) >= 100:
                    active_condition_ids.add(gid)

                    if gid not in elapsed_tracker:
                        elapsed_tracker[gid] = now

                    elapsed = int(now - elapsed_tracker[gid])
                    mins, secs = divmod(elapsed, 60)
                    elapsed_str = f"{colors['BLU']}⏱ {colors['LGRE'] if g.get('up') else colors['LRED']}{mins:02d}:{secs:02d}{colors['RES']}"
                    # else:
                    #     elapsed_str = None

                    blinking = colors['BLNK'] if (g.get("up") and rtp_val >= 99) else ""
                    color = colors['RED'] if not g.get("up") else colors['GRE']
                    direction = f"{blinking}{colors['LRED']}⬇{colors['RES']}" if not g.get("up") else f"{blinking}{colors['LGRE']}⬆{colors['RES']}"
                    signal = f"{colors['LCYN']}◆{colors['RES']}" if prev_rtp is None else f"{colors['LRED']}▼{colors['RES']}" if rtp_val < prev_rtp_val else f"{colors['LGRE']}▲{colors['RES']}" if rtp_val > prev_rtp_val else f"{colors['LCYN']}◆{colors['RES']}"

                    rtp_display = f"{blinking}{direction} {color}{rtp_val} {colors['WHTE']}%{colors['RES']}"

                    prev_color =  colors['RED'] if (not prev_rtp and prev_rtp_val != 0.0) else colors['GRE'] if (prev_rtp and prev_rtp_val != 0.0) else colors['CYN']
                    prev_direction = f"{colors['LRED']}⬇{colors['RES']}" if (not prev_rtp and prev_rtp_val != 0.0) else f"{colors['LGRE']}⬆{colors['RES']}" if (prev_rtp and prev_rtp_val != 0.0) else f"{colors['LCYN']}◉{colors['RES']}"
                    prev_rtp_display = f"{colors['LYEL']}({prev_direction} {prev_color}{prev_rtp_val} {colors['WHTE']}%{colors['LYEL']}) {elapsed_str}{colors['RES']}"

                    # if elapsed_str:
                    #     prev_rtp_display = f"{colors['LYEL']}({prev_direction} {prev_color}{prev_rtp_val} {colors['WHTE']}%{colors['LYEL']}) {colors['BLU']}⏱ {colors['ORA']}{elapsed_str}{colors['RES']}"
                    # else:
                    #     prev_rtp_display = f"{colors['LYEL']}({prev_direction} {prev_color}{prev_rtp_val} {colors['WHTE']}%{colors['LYEL']})"

                    return f"\t{colors['WHTE']}- {name_display} {rtp_display} {signal} {prev_rtp_display} {colors['RES']}"

                # 🔥 HOT section = 2 columns
                # helper: strip ANSI for accurate width
                ansi_escape = re.compile(r'\x1b\[[0-9;]*m')

                # def visible_len(s):
                #     return len(ansi_escape.sub('', s))

                # def pad_right(s, width):
                #     return s + ' ' * max(0, width - visible_len(s))
                
                # if title == "Hot":
                #     formatted = []
                    
                #     for g in games:
                #         try:
                #             formatted.append(format_game(g))
                #         except Exception as e:
                #             formatted.append(f"<error {g.get('game_id')}>")

                #     # split into two balanced columns (top-to-bottom)
                #     mid = (len(formatted) + 1) // 2
                #     left_col = formatted[:mid]
                #     right_col = formatted[mid:]
                #     # find max visible width of left column
                #     max_left_width = max(visible_len(x) for x in left_col)

                #     for i in range(mid):
                #         left = left_col[i]
                #         right = right_col[i] if i < len(right_col) else ""
                #         left_padded = pad_right(left, max_left_width + 1)
                        
                #         message += f"\t{left_padded}{right}\n"
                # else:
                #     # normal single column
                #     for g in games:
                #         try:
                #             message += f"\t{format_game(g)}\n"
                #         except Exception as e:
                #             message += f"\t<error rendering game {g.get('game_id')}: {e}>\n"

                for g in games:
                    try:
                        message += f"\t{format_game(g)}\n"
                    except Exception as e:
                        message += f"\t<error rendering game {g.get('game_id')}: {e}>\n"

            if top_id not in active_condition_ids:
                elapsed_tracker.pop(top_id, None)

            for gid in list(elapsed_tracker.keys()):
                if gid not in active_condition_ids:
                    elapsed_tracker.pop(gid, None)

            last_top_rtp_val = top_rtp_val
            last_top_rtp = top_rtp
            last_total_bet = total_bet

            log_message("info", message, overwrite=True, _overlay_key="rtp_data")
            stop_event.wait(0.5)
        except Exception as e:
            log_message("error", f"[fetch_rtp_data] {e}", overwrite=True, _overlay_key="rtp_data")
            time.sleep(0.5)

def fetch_winners_data():
    state.hit_win = False
    
    while not stop_event.is_set():
        try:
            winners_data_raw = r.get("winners_data")
            if not winners_data_raw:
                time.sleep(0.5)
                continue

            data_hash = hashlib.md5(winners_data_raw.encode()).hexdigest()
            winners_data = json.loads(winners_data_raw)

            if state.last_winners_hash != data_hash:
                state.last_winners_hash = data_hash
                state.api_vol_static = float(state.api_vol)
            
            avg_sec, last_hit = avg_interval_seconds(winners_data, game["name"])
            trend_timer = ""

            if avg_sec and last_hit:
                trend_timer = trend_countdown(last_hit, avg_sec)
                
            # message = f"\n\t{colors['WHTE']}Winners Data{colors['RES']}: {colors['LRED'] if state.hit_win else colors['BLU']}{state.hit_win}{colors['RES']}\n"

            # message = (
            #     f"\t{colors['WHTE']}Winners Data{colors['RES']}: {colors['LRED'] if state.hit_win else colors['BLU']}{state.hit_win}{colors['RES']}"
            #     f"\t{colors['WHTE']}Next Trend ETA{colors['RES']}: {colors['ORA']}{trend_timer}{colors['RES']}\n"
            # )
            message = ""

            game_counts = defaultdict(int)
            
            for winner in winners_data:
                # user = winner.get("user", "")
                timestamp = winner.get("time", "")
                game_name = winner.get("game", "")
                is_current_game = game_name.lower() == game["name"].lower()
                
                if any([
                    not is_current_game and game_counts[game_name] >= 2,
                    is_current_game and game_counts[game_name] >= 4
                ]): continue
                
                game_counts[game_name] += 1
                
                colored_ago = f"{colors['CYN'] if (is_current_game) else colors['DGRY']}⏱ {time_ago(timestamp) if (is_current_game) else timestamp}{colors['RES']}"
                colored_game = f"{colors['BLYEL']}{game_name}{colors['RES']}" if (is_current_game) else f"{colors['DGRY']}{game_name}{colors['RES']}"
                
                bet = winner.get("bet", "")
                multiplier = winner.get("multiplier", "")
                payout = f"{colors['LGRE'] if (is_current_game) else colors['DGRY']}₱{colors['ORA'] if (is_current_game) else colors['DGRY']}{round(str_to_float(bet) * str_to_float(multiplier), 2):,.2f}{colors['RES']}"
                
                colored_bet = f"{colors['LGRE'] if (is_current_game) else colors['DGRY']}₱{colors['BLCYN'] if (is_current_game) else colors['DGRY']}{round(str_to_float(bet)) if str_to_float(bet).is_integer() else str_to_float(bet)}{colors['RES']}"
                colored_multiplier = f"{colors['LYEL'] if (is_current_game) else colors['DGRY']}x{colors['BLMAG'] if (is_current_game) else colors['DGRY']}{str_to_float(multiplier)}{colors['RES']}"

                if state.api_vol_static != 0.0:
                    vol = state.api_vol_static

                    colored_api_volume = (
                        f"{colors['BLMAG'] if vol >= 200 else
                        colors['BLRED'] if vol >= 150 else
                        colors['ORA'] if vol >= 120 else
                        colors['BLYEL'] if vol >= 90 else
                        colors['BLCYN'] if vol >= 50 else
                        colors['BLGRE'] if vol >= 10 else
                        colors['DGRY']}"
                        f"{vol:.2f}{colors['RES']}"
                    )
                
                # message += f"\n\t[ {colored_game} ]{colors['WHTE']} - {colored_bet} {colored_multiplier} {colors['WHTE']}= {payout} {colored_ago}"
                message += (
                    f"\n\t[ {colored_game} ]{colors['WHTE']} - {colored_bet} {colored_multiplier} {colors['WHTE']}= {payout} {colored_ago}"
                    f"{f' | {colors['WHTE']}Volume Hit{colors['RES']}: {colored_api_volume}' if is_current_game and state.api_vol_static != 0.0 else ''}"
                )
                        
            log_message("info", message, overwrite=True, _overlay_key="winners_data")
            stop_event.wait(0.5)
        except Exception as e:
            log_message("error", f"[fetch_winners_data] {e}", overwrite=True, _overlay_key="winners_data")
            time.sleep(0.5)

def get_jackpot_bar(percentage: float, color: str, bar_length: int=20) -> str:
    filled_blocks = round((percentage / 100) * bar_length)
    empty_blocks = bar_length - filled_blocks
    filled_bar = '🟩' if color == 'green' else '🟥'
    empty_bar = '⬛'
    color_code = colors.get('LGRE') if color == 'green' else colors.get('LRED')

    return f"{color_code}{filled_bar * filled_blocks}{colors.get('RES')}{empty_bar * empty_blocks}"

def pct(p):
    if p is None:
        return 0.0
    if isinstance(p, str) and '%' in p:
        return float(p.strip('%'))
    try:
        return float(p)
    except (TypeError, ValueError):
        return 0.0
    
def start_listeners(stop_event):
    with KeyboardListener(on_press=on_key_press) as kb_listener:
        while not stop_event.is_set():
            kb_listener.join(0.1)

def on_key_press(key):
    if key == Key.esc:
        # state.running = False
        os._exit(0)
        
    if key == Key.right:
        bet_inc = [
            lambda: pyautogui.click(x=CENTER_X + 115, y=BTM_Y - 105, button='left'),
            lambda: pyautogui.click(x=CENTER_X + 115, y=BTM_Y - 105, button='right')
        ]
        random.choice(bet_inc)()
        
    if key == Key.left:
        bet_dec = [
            lambda: pyautogui.click(x=CENTER_X - 115, y=BTM_Y - 105, button='left'),
            lambda: pyautogui.click(x=CENTER_X - 115, y=BTM_Y - 105, button='right')
        ]
        random.choice(bet_dec)()
        
    if key == Key.up:
        state.extra_bet = not state.extra_bet
        threading.Thread(target=bet_switch, args=(False, state.extra_bet,), daemon=True).start()
        # status = "ON" if state.extra_bet else "OFF"
        # alert_queue.put(f"extra bet {status}")
        
    if key == Key.shift:
        state.auto_mode = not state.auto_mode
        spin_in_progress.clear()
        status = "ENABLED" if state.auto_mode else "DISABLED"
        # play_alert(say=f"auto mode {status}")
        
        alert_queue.put(f"auto mode {status}")
        # color = BLMAG if status == "ENABLED" else BLRED
        # log_message("info", f"\t\t{WHTE}Auto Mode{RES}: {color}{status}{RES}")
        
    if key == Key.ctrl:
        state.slow_mode = not state.slow_mode
        spin_in_progress.clear()
        status = "ENABLED" if state.slow_mode else "DISABLED"
        alert_queue.put(f"slow mode {status}")
        
    if key == Key.caps_lock:
        state.fast_mode = False
        state.scatter_mode = not state.scatter_mode
        spin_in_progress.clear()
        threading.Thread(target=spin, args=(False, True, False, False,), daemon=False).start()
        status = "ON" if state.scatter_mode else "DISABLED"
        # play_alert(say=f"auto mode {status}")
        # state.scatter_mode = False
        alert_queue.put(f"scatter mode {status}")
        
        # state.fast_mode = not state.fast_mode
        # status = "ENABLED" if state.fast_mode else "DISABLED"
        # # play_alert(say=f"auto mode {status}")
        # alert_queue.put(f"fast mode {status}")
        # color = BLMAG if status == "ENABLED" else BLRED
        # log_message("info", f"\t\t{WHTE}Fast Mode{RES}: {color}{status}{RES}")

    if hasattr(key, "char") and key.char and key.char.isdigit():
        state.wheel_sleep = int(key.char)
        
    if key == Key.shift_r:
        threading.Thread(target=spin, args=(False, False, True, False, False,), daemon=False).start()
        
    if key == Key.tab:
        # spammer = [
        #     lambda: (pyautogui.mouseDown(button='left'), time.sleep(random.uniform(*TIMEOUT_DELAY_RANGE)), pyautogui.mouseUp(button='left')),
        #     lambda: (pyautogui.mouseDown(button='right'), time.sleep(random.uniform(*TIMEOUT_DELAY_RANGE)),pyautogui.mouseUp(button='right')),
        #     lambda: (pyautogui.keyDown('space'), time.sleep(random.uniform(*TIMEOUT_DELAY_RANGE)), pyautogui.keyUp('space')),
        #     lambda: pyautogui.click(clicks=2, interval=random.uniform(*EXECUTION_TIME_RANGE), button="left"),
        #     lambda: pyautogui.click(clicks=2, interval=random.uniform(*EXECUTION_TIME_RANGE), button="right"),
        #     lambda: pyautogui.doubleClick(interval=random.uniform(*EXECUTION_TIME_RANGE), button="left"),
        #     lambda: pyautogui.doubleClick(interval=random.uniform(*EXECUTION_TIME_RANGE), button="right"),
        #     lambda: pyautogui.typewrite(['space'], interval=random.uniform(*TIMEOUT_DELAY_RANGE))
        # ]
        # for _ in range(3):
        #     random.choice(spammer)()
        #     # pyautogui.PAUSE = 0.1
        #     # pyautogui.FAILSAFE = True
        #     time.sleep(0.005)  # Super fast (200 actions per second)
        # alert_queue.put(f"scatter")
        # state.fast_mode = False
        # state.scatter_spin = True
        # spin_in_progress.clear()
        # threading.Thread(target=spin, args=(False, False, False, True,), daemon=True).start()
        # # play_alert(say=f"auto mode {status}")
        # # state.scatter_mode = False
        # alert_queue.put(f"scatter spin")
        
        
        state.fast_mode = False
        state.scatter_mode = False
        state.quick_spin = False
        state.wheel_mode = True
        spin_in_progress.clear()

        variation = state.wheel_sleep * 0.1  # 10%
        state.wheel_secs = random.uniform(state.wheel_sleep, state.wheel_sleep + variation)
        # state.wheel_secs = random.uniform(6.0, 7.7)

        threading.Thread(target=spin, args=(False, False, False, False, True, False,), daemon=True).start()
        alert_queue.put(f"wheel mode {round(state.wheel_secs, 2)}")

    if key == Key.cmd:
        state.fast_mode = False
        state.scatter_mode = False
        state.quick_spin = True
        state.wheel_mode = False
        spin_in_progress.clear()
        threading.Thread(target=spin, args=(False, False, False, False, False, True,), daemon=False).start()
        alert_queue.put(f"quick spin")
        

if __name__ == "__main__":
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True
    )

    try:
        r.ping()
        print("✅ Connected to Redis")
    except redis.exceptions.ConnectionError as e:
        print("❌ Redis connection failed:", e)
    
    stop_event = threading.Event()
    spin_in_progress = threading.Event()
    bet_in_progress = threading.Event()
    already_alerted = set()
    
    alert_queue = ThQueue()
    
    alert_thread = threading.Thread(target=play_alert)
    timer_thread = threading.Thread(target=timer)
    log_thread = threading.Thread(target=log_message)
    
    alert_thread.start()
    timer_thread.start()
    log_thread.start()
    
    providers_col = db["PROVIDER"]
    providers = list(providers_col.find({}, {"name": 1, "initial": 1, "color": 1, "_id": 0}))
    
    log_message("info", colors.get('CLEAR',''))
    log_message("info", render_providers(providers))
    
    provider = providers_list(providers)
    # play_alert(provider.get("name"))
    alert_queue.put(provider.get("name"))
    
    log_message("info", render_games(provider))
    
    game = games_list(provider)
    # play_alert(game.get("name"))
    alert_queue.put(game.get("name"))
    
    urls_env = os.getenv("URLS")
    URLS_LIST = [url.strip() for url in urls_env.split(",") if urls_env.strip()]
    URLS = {url: url for url in URLS_LIST}
    url = next((url for url in URLS if 'win' in url), None)    

    # # store current game in file
    # with open(GAME_FILE, "w", encoding="utf-8") as f:
    #     f.write(game)
    
    servers_env = os.getenv("WS_URL")
    SERVERS_LIST = [url.strip() for url in servers_env.split(",") if servers_env.strip()]
    API_SERVERS = {url: url for url in SERVERS_LIST}
    api_server = next((url for url in API_SERVERS if 'localhost' in url), None) # local
    # # api_server = f"wss://{VPS_DOMAIN}/ws" # vps
    
    r.set("game", json.dumps(game))
    r.set("provider", json.dumps(provider))
    r.set("url", url)
    r.set("api_server", api_server)
    
    user_input = input(f"\n\n\tDo you want to enable {colors.get('CYN')}Auto Mode{colors.get('RES')} ({colors.get('DGRY')}Y/n{colors.get('RES')}): ").strip().lower()
    auto_mode = user_input in ("", "y", "yes") # default to yes
    fast_mode = False
    # dual_slots = False
    # split_screen = False
    # left_slot = right_slot = False
    dual_slots = True 
    split_screen = True
    left_slot = False
    right_slot = True
    
    # optimize screen later
    if dual_slots and split_screen:# and slot_position is not None:
        # if slot_position == "left":
        if left_slot:
            CENTER_X, CENTER_Y = LEFT_SLOT_POS.get("center_x"), LEFT_SLOT_POS.get("center_y")
        # elif slot_position == "right":
        elif right_slot:
            CENTER_X, CENTER_Y = RIGHT_SLOT_POS.get("center_x"), RIGHT_SLOT_POS.get("center_y")
    else:
        CENTER_X, CENTER_Y = SCREEN_POS.get("center_x"), SCREEN_POS.get("center_y")
    LEFT_X, RIGHT_X, TOP_Y, BTM_Y = 0, SCREEN_POS.get("right_x"), 0, SCREEN_POS.get("bottom_y")
    # LEFT_X, RIGHT_X, TOP_Y, BTM_Y = 0, SCREEN_POS.get("right_x"), 0, SCREEN_POS.get("bottom_y") - 55 # DREAM CASINO
    
    # log_message("info", f"\n\n\t... {colors['WHTE']}Starting real-time jackpot monitor.\n\t    Press ({BLMAG}Ctrl+Ccolors.get('RES'){colors['WHTE']}) to stop.colors.get('RES')\n\n")
    
    # breakout = load_breakout_memory(game)
    state = AutoState()
    settings = configure_game(game, api_server, auto_mode, fast_mode, dual_slots, split_screen, left_slot, right_slot)#, forever_spin)
    
    # cx, cy = CENTER_X, CENTER_Y

    shrink_percentage = 60 if state.widescreen else 32
    width = int(max(RIGHT_X, BTM_Y) * (shrink_percentage / 100))
    height = int(min(RIGHT_X, BTM_Y) * (shrink_percentage / 100))
    # border_space_top = cy // 3 if state.widescreen else 0
    radius_x, radius_y = width // 2, height // 2 #if widescreen else width // 2
    # rand_x = cx + random.randint(-radius_x, radius_x)
    # rand_y = cy + random.randint(-radius_y, radius_y) + (border_space_top if radius_y <= 0 else -border_space_top)
    # rand_x2 = cx - random.randint(-radius_x, radius_x)
    # rand_y2 = cy - random.randint(-radius_y, radius_y) + (border_space_top if radius_y <= 0 else -border_space_top)
    
    # y_start = 200
    # y_end = cy
    y_start = 200
    y_end = BTM_Y - CENTER_Y

    if (
        provider.get("initial") == "JILI"
        and any(n in game.get("name", "") for n in ("Pirate Queen", "Golden Empire"))
    ):
        y_start *= 2

    threads = []
    
    threads.append(threading.Thread(target=banner, args=(game, provider,), daemon=True))
    threads.append(threading.Thread(target=fetch_hs_data, daemon=True))
    threads.append(threading.Thread(target=fetch_api_data, daemon=True))
    threads.append(threading.Thread(target=fetch_rtp_data, daemon=True))
    threads.append(threading.Thread(target=fetch_winners_data, daemon=True))
    threads.append(threading.Thread(target=start_listeners, args=(stop_event,), daemon=True))
    
    for t in threads:
        t.start()
        
    try:
        next_run = time.monotonic()
        while not stop_event.is_set():
            if state.scatter_mode:
                now = time.monotonic()
                if now >= next_run:
                    if state.session_mode == "HOT":
                        spin_in_progress.clear()
                        threading.Thread(target=spin, args=(False, True, False, False,), daemon=False).start()
                    next_run = now + random.uniform(5, 9)
                    # alert_queue.put("ping")
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_event.set()
        log_message("error", f"\n\n\t🤖❌  {colors.get('BLRED')}Main program interrupted.{colors.get('RES')}")
    finally:
        stop_event.set()
        
        # alert_queue.join()
        # alert_thread.join()
        # timer_thread.join()
        # log_thread.join()
        
        # stop_event.set()

        # 1️⃣ Stop queue workers
        alert_queue.put(None)

        # 2️⃣ Join NON-daemon workers only
        for t in (alert_thread, timer_thread, log_thread):
            t.join(timeout=2)

        for t in threads:
            if not t.daemon:
                t.join(timeout=2)

        # 3️⃣ Cleanup Redis
        try:
            r.delete("game", "provider", "url", "api_server", "game_data", "api_data", "rtp_data", "winners_data")
            r.close()
        except Exception:
            pass
        
        # for t in threads:
        #     t.join()
            
        # r.delete("game")
        # r.delete("provider")
        # r.delete("url")
        # r.delete("api_server")
        # r.delete("game_data")
        # r.delete("api_data")
        # r.close()
        
        log_message("warning", f"\n\n\t🤖❌  {colors.get('LYEL')}All threads shut down...{colors.get('RES')}")
        
        # stop_event.set()
        # alert_queue.join()
        # bet_queue.join()
        