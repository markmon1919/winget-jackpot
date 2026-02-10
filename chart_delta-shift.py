#!/usr/bin/env .venv/bin/python

import json, os, platform, pyautogui, random, sys, threading, time, redis, pandas as pd, subprocess
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from collections import deque
from queue import Queue as ThQueue
from dotenv import load_dotenv
import warnings
import logging
import mplfinance as mpf
from config import (HOLD_DELAY_RANGE, SPIN_DELAY_RANGE, TIMEOUT_DELAY_RANGE, DEFAULT_GAME_CONFIG, SCREEN_POS, LEFT_SLOT_POS, RIGHT_SLOT_POS)
from decimal import Decimal


logging.getLogger('matplotlib.font_manager').setLevel(logging.WARNING)
warnings.filterwarnings("ignore", message="Attempting to set identical low and high ylims")

load_dotenv()

colors = {}
for key, value in os.environ.items():
    if key.isupper() and not key.startswith("DB_") and not key.startswith("PROVIDER_"):
        colors[key] = value.encode("utf-8").decode("unicode_escape")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
MAX_ROWS = 60
SMOOTH_WINDOW = 3  # Rolling window for slope smoothing

logging.basicConfig(level=(logging.DEBUG if LOG_LEVEL=="DEBUG" else logging.INFO))
logger = logging.getLogger("quic_redis_poller")


class ChartWatcher:
    def __init__(self, header="value", chart_title="Jackpot Chart"):
        self.header = header
        self.chart_title = chart_title
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.history = deque(maxlen=MAX_ROWS*10)
        self.lock = threading.Lock()

        # Dual alert queues
        self.prealert_queue = ThQueue()  # priority ping
        self.alert_queue = ThQueue()     # normal TTS alerts

        self.stop_event = threading.Event()
        self.spin_in_progress = threading.Event()
        self.spin_triggered = False
        
        self.game_name = "Unknown"
        self.provider_name = "Unknown"
        self.epsilon = 1e-6
        self.already_alerted = set()

        # Countdown variables
        self.last_snapshot_time = None
        self.timer_start = None
        self.countdown_interval = 1
        self.last_value = None  # track last jackpot value

        # Figure & axes
        self.fig, self.ax_candle = plt.subplots(figsize=(12,6))
        self.fig.patch.set_facecolor("black")
        self.ax_candle.set_facecolor("black")
        self.ax_candle.set_ylabel("Jackpot Value", color="yellow", fontsize=10)
        
        self.ax_slope = self.ax_candle.twinx()
        self.ax_slope.set_ylabel("Slope", color="magenta")
        self.ax_slope.tick_params(axis="y", colors="magenta")
        self.ax_slope.yaxis.set_label_position("right")
        self.ax_slope.yaxis.tick_right()

        # Candle style (dark green up candles)
        mc = mpf.make_marketcolors(up="#006400", down="tomato", wick="white", edge="inherit")
        self.style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            facecolor="black",
            edgecolor="black",
            gridcolor="gray",
            rc={
                "axes.labelcolor":"white",
                "xtick.color":"white",
                "ytick.color":"white",
                "axes.edgecolor":"white",
                "grid.color":"gray",
                "grid.linestyle":"--"
            }
        )
        
    def spin(self, combo_spin: bool = False, spam_spin: bool = False, turbo_spin: bool = False, wait_before_spin: bool = False):
        # while not stop_event.is_set():
        if self.spin_in_progress.is_set():
            sys.stdout.write("\t⚠️  Spin still in action, skipping")
            return
        
        self.spin_in_progress.set()

        try:
            # cmd, combo_spin = spin_queue.get_nowait()
            # spin_in_progress, combo_spin = spin_queue.get(timeout=1)
            spin_types = [ "normal_spin", "spin_hold", "spin_delay", "spin_hold_delay", "turbo_spin", "super_turbo", "board_spin", "board_spin_hold", "board_spin_delay", "board_spin_hold_delay", "board_spin_turbo", "spin_slide", "auto_spin" ]
            
            if not combo_spin and "PG" in self.provider_name:
                spin_types = [s for s in spin_types if not s.startswith("board")]

            if combo_spin:
                spin_types = [s for s in spin_types if s.startswith("board")]
                spin_types.extend(["combo_spin", "spam_spin", "turbo_spin"])
                
            if turbo_spin:
                spin_types = [ "turbo_spin", "super_turbo", "spin_hold", "spam_spin", "combo_spin" ]
                    
            if "JILI" in self.provider_name:
                spin_types.extend([ "max_turbo" ])
                
            if not fast_mode and wait_before_spin:
                if random.random() < 0.6: # 60% use normal spin
                    spin_type = "normal_spin"
                else:
                    spin_type = random.choice(spin_types)
            else:
                spin_type = random.choice(spin_types) #if not spam_spin else "spam_spin"
                
            cx, cy = CENTER_X, CENTER_Y

            shrink_percentage = 60 if widescreen else 32
            width = int(max(RIGHT_X, BTM_Y) * (shrink_percentage / 100))
            height = int(min(RIGHT_X, BTM_Y) * (shrink_percentage / 100))
            border_space_top = cy // 3 if widescreen else 0
            radius_x, radius_y = width // 2, height // 2 #if widescreen else width // 2
            # rand_x = cx + random.randint(-radius_x, radius_x)
            # rand_y = cy + random.randint(-radius_y, radius_y) + (border_space_top if radius_y <= 0 else -border_space_top)
            # rand_x2 = cx - random.randint(-radius_x, radius_x)
            # rand_y2 = cy - random.randint(-radius_y, radius_y) + (border_space_top if radius_y <= 0 else -border_space_top)
            rand_x = cx - random.randint(-radius_x, radius_x)
            rand_y = random.randint(200, cy)
            # mystic = 100
            # cruise_royal = 100
            # queen of bounty = cy

            rand_x2 = cx - random.randint(-radius_x, radius_x)
            rand_y2 = random.randint(200, cy)

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
            # spin_delay = random.uniform(*SPIN_DELAY_RANGE)
            timeout_delay = random.uniform(*TIMEOUT_DELAY_RANGE)
            # print(f'widescreen: {widescreen}')
            # print(f'spin_btn: {spin_btn}')
            
            if spin_type == "normal_spin":
                if widescreen:
                    action.extend([
                        lambda: pyautogui.click(x=cx + 520, y=cy + 335, button='left'),
                        lambda: pyautogui.click(x=cx + 520, y=cy + 335, button='right'),
                        lambda: pyautogui.press('space'),
                        lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), pyautogui.mouseUp())
                    ])
                else:
                    # NO RIGHT CLICK FOR BUTTON IN PG (BUT MOUSEDOWN IS GOOD)
                    action.extend([
                        lambda: pyautogui.click(x=cx, y=BTM_Y - 105, button='left'),
                        # lambda: pyautogui.click(x=cx, y=BTM_Y - 105, button='right'),
                        lambda: pyautogui.press('space'),
                        lambda: (pyautogui.keyDown('space'), pyautogui.keyUp('space')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseUp())
                    ]) if not spin_btn else \
                    action.extend([
                        lambda: pyautogui.click(x=cx, y=BTM_Y - 105, button='left'),
                        lambda: pyautogui.click(x=cx, y=BTM_Y - 105, button='right'),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseUp())
                    ])
            elif spin_type == "spin_hold":
                if widescreen:
                    action.extend([
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                    ])
                else:
                    action.extend([
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.keyDown('space'), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.keyDown('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                    ]) if not spin_btn else \
                    action.extend([
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                    ])
            elif spin_type == "spin_delay":
                if widescreen:
                    action.extend([
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='left')),
                        # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='right')),
                        # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.keyUp('space')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
                    ])
                else:
                    action.extend([
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.press('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.keyUp('space')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
                    ]) if not spin_btn else \
                    action.extend([
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='left')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(button='right')),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
                    ])
            elif spin_type == "spin_hold_delay":
                if widescreen:
                    action.extend([
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.press('space')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),                       
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),                        
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right'))
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                    ])
                else:
                    action.extend([
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.press('space')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.keyDown('space'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),                       
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),                        
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right'))
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                    ]) if not spin_btn else \
                    action.extend([
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),                       
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right')),                        
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.click(x=rand_x, y=rand_y, button='right'))
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left')),
                        # lambda: (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'), time.sleep(hold_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'))
                    ])
            elif spin_type == "board_spin":
                if widescreen:
                    action.extend([
                        lambda: pyautogui.click(x=rand_x, y=rand_y, button='left'),
                        lambda: pyautogui.click(x=rand_x, y=rand_y, button='right'),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.mouseUp())
                    ])
                else:
                    action.extend([
                        lambda: pyautogui.click(x=rand_x, y=rand_y, button='left'),
                        # lambda: pyautogui.click(x=rand_x, y=rand_y, button='right'),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.mouseUp())
                    ]) if not spin_btn else \
                    action.extend([
                        lambda: pyautogui.click(x=rand_x, y=rand_y, button='left'),
                        lambda: pyautogui.click(x=rand_x, y=rand_y, button='right'),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.mouseUp())
                    ])
            elif spin_type == "board_spin_hold":
                if widescreen:
                    action.extend([
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(x=cx + 520, y=cy + 335, button='right'))
                    ])
                else:
                    action.extend([
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.mouseDown(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.mouseDown(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.mouseDown(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'))
                    ]) if not spin_btn else \
                    action.extend([
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y), pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button='right'))
                    ])
            elif spin_type == "board_spin_delay":
                if widescreen:
                    action.extend([
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
                    ])
                else:
                    action.extend([
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
                    ]) if not spin_btn else \
                    action.extend([
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.mouseUp())
                    ])
            elif spin_type == "board_spin_hold_delay":
                if widescreen:
                    action.extend([
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right'))
                    ])
                else:
                    action.extend([
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.press('space')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.press('space')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right'))
                    ]) if not spin_btn else \
                    action.extend([
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.click(button='right')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='left')),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.click(button='right'))
                    ])
            elif spin_type == "spin_slide":
                if widescreen:
                    action.extend([
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp())
                    ])
                else:
                    action.extend([
                        lambda: (pyautogui.press('space'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.press('space'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.press('space'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(timeout_delay), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                        # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp())
                    ]) if not spin_btn else \
                    action.extend([
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp())
                    ])
            elif spin_type == "board_spin_turbo":
                if widescreen:
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
                    action.extend([
                        lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='left'),
                        # lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, button='right'),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.press('space')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.keyDown('space')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        # lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'))
                    ]) if not spin_btn else \
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
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'))
                    ])
            elif spin_type == "turbo_spin": # add turbo-on + space then board stop and turbo-off soon; also auto_spin + board_stop..etc
                if widescreen:
                    if self.provider_name == "JILI": # Playtime
                        cx += 40
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
                        lambda: (pyautogui.press('space'), pyautogui.keyDown('space')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.press('space')),
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
                    if "PG" in self.provider_name:
                        action.extend([
                            lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left'),
                            # lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right'),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(button='right')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(button='left')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='left')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='right')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='left')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                            # lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                            
                            # # TURBO ENABLED
                            # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='right'), pyautogui.press('space'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # # TURBO ENABLED
                            
                            lambda: (pyautogui.press('space'), pyautogui.press('space')),
                            lambda: (pyautogui.press('space'), pyautogui.keyDown('space')),
                            
                            lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),

                            lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='left')),
                            # lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='right')),
                            # lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='left')),
                            # lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='right'))
                        ])
                    else:
                        action.extend([
                            lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left'),
                            lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right'),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.press('space')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.press('space')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.keyDown('space')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.keyDown('space')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                            lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                            lambda: (pyautogui.press('space'), pyautogui.press('space')),
                            lambda: (pyautogui.press('space'), pyautogui.keyDown('space')),
                            lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                            lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                            lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                            lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.press('space')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                            lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='right'))
                        ]) if not spin_btn else \
                        action.extend([
                            #
                        ])
            elif spin_type == "super_turbo": # 1 star if JILI
                if widescreen:
                    if self.provider_name == "JILI": # Playtime
                        cx += 40
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
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        # auto spin style
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='left'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='left')),
                        lambda: (pyautogui.click(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'))
                    ])
                else:
                    if "PG" in self.provider_name:
                        action.extend([
                            # TURBO ENABLED
                            lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='right'), pyautogui.press('space'), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left')),
                            # TURBO ENABLED
                            lambda: (pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx - 200, y=BTM_Y - 105, button='left'))
                        ])
                    else:
                        action.extend([
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            # auto spin style
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'))
                        ]) if not spin_btn else \
                        action.extend([
                            #
                        ])
            elif spin_type == "max_turbo": # 2 stars only JILI
                if widescreen:
                    if self.provider_name == "JILI": # Playtime
                        cx += 40
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
                        lambda: (pyautogui.doubleClick(x=cx + 240, y=cy + 325, button='right'), pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 240, y=cy + 325, button='right'))
                    ])
                else:
                    action.extend([
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.press('space'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x2, y=rand_y2, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        # auto spin style
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.doubleClick(x=cx + 152, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'), time.sleep(0.5), pyautogui.click(x=cx + 152, y=BTM_Y - 105, button='right'))
                    ])
            elif spin_type == "auto_spin":
                if widescreen:
                    if self.provider_name == "JILI": # Playtime
                        cx += 40
                        cy += 40
                    action.extend([
                        lambda: pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='left'),
                        lambda: pyautogui.doubleClick(x=cx + 380, y=cy + 325, button='right'),
                        lambda: (pyautogui.click(x=cx + 380, y=cy + 325, button='left'), pyautogui.click(x=cx + 380, y=cy + 325,button='left')),
                        lambda: (pyautogui.click(x=cx + 380, y=cy + 325, button='right'), pyautogui.click(x=cx + 380, y=cy + 325,button='right'))
                    ])
                else:
                    if "PG" in self.provider_name:
                        action.extend([
                            lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='left'), time.sleep(0.3), pyautogui.click(x=cx - 195, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='left'), time.sleep(0.3), pyautogui.click(x=cx - 100, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='left'), time.sleep(0.3), pyautogui.click(x=cx, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='left'), time.sleep(0.3), pyautogui.click(x=cx + 100, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='left'), time.sleep(0.3), pyautogui.click(x=cx + 195, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(1.5), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='right'), time.sleep(0.3), pyautogui.click(x=cx - 195, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='right'), time.sleep(0.3), pyautogui.click(x=cx - 100, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='right'), time.sleep(0.3), pyautogui.click(x=cx, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='right'), time.sleep(0.3), pyautogui.click(x=cx + 100, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                            # lambda: (pyautogui.click(x=cx + 195, y=BTM_Y - 105, button='right'), time.sleep(0.3), pyautogui.click(x=cx + 195, y=BTM_Y - 205, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), time.sleep(0.9), pyautogui.click(x=cx, y=BTM_Y - 105, button='left'))
                        ])
                    else:
                        action.extend([
                            lambda: pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='left'),
                            lambda: pyautogui.doubleClick(x=cx + 95, y=BTM_Y - 105, button='right'),
                            lambda: (pyautogui.click(x=cx + 95, y=BTM_Y - 105, button='left'), pyautogui.click(x=cx + 95, y=BTM_Y - 105, button='left')),
                            lambda: (pyautogui.click(x=cx + 95, y=BTM_Y - 105, button='right'), pyautogui.click(x=cx + 95, y=BTM_Y - 105, button='right'))
                        ]) if not spin_btn else \
                    action.extend([
                        #
                    ])
            elif spin_type == "combo_spin":
                action.extend([
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
                        lambda: (pyautogui.mouseDown(x=rand_x, y=rand_y, button='right'), pyautogui.moveTo(x=rand_x2, y=rand_y2), time.sleep(hold_delay), pyautogui.mouseUp()),
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
                action.extend([
                    lambda: [ pyautogui.typewrite(['space'] * 6, interval=0.01) for _ in range(3) ],
                    lambda: [ pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=0.01, button="left") for _ in range(3) ],
                    # lambda: pyautogui.doubleClick(x=rand_x, y=rand_y, clicks=3, interval=0.01, button="left"),
                    lambda: [ pyautogui.click(x=cx, y=BTM_Y - 105, clicks=6, interval=0.01, button="left") for _ in range(3) ],
                    # lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, clicks=3, interval=0.01, button="left"),
                    
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button='left'), time.sleep(hold_delay), pyautogui.moveTo(x=rand_x2, y=rand_y2), pyautogui.mouseUp()) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=cx, y=BTM_Y - 105, button="left"), pyautogui.typewrite(['space'] * 6, interval=0.01)) for _ in range(3) ],
                    lambda: [ (pyautogui.mouseDown(x=rand_x, y=rand_y, button="left"), pyautogui.typewrite(['space'] * 6, interval=0.01)) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, clicks=6, interval=0.01, button="left")) for _ in range(3) ],
                    lambda: [ (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=BTM_Y - 105, clicks=6, interval=0.01, button="left")) for _ in range(3) ],
                    
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=rand_x, y=rand_y, button="left"), time.sleep(0.01)) for _ in range(3) ],
                    # lambda: [ (pyautogui.press("space"), pyautogui.doubleClick(x=rand_x, y=rand_y, button="left")) for _ in range(3) ],
                    lambda: [ (pyautogui.press("space"), pyautogui.click(x=cx, y=BTM_Y - 105, button="left"), time.sleep(0.01)) for _ in range(3) ],
                    # lambda: [ (pyautogui.press("space"), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button="left")) for _ in range(3) ],
                    lambda: [ (pyautogui.click(x=cx, y=BTM_Y - 105, button="left"), pyautogui.click(x=rand_x, y=rand_y, button="left"), time.sleep(0.01)) for _ in range(3) ],
                ])
            elif spin_type == "quick_spin":
                if widescreen:
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
                        lambda: (pyautogui.press('space'), pyautogui.keyDown('space')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.press('space')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx + 520, y=cy + 335, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
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
                    action.extend([
                        lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left'),
                        lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right'),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.press('space')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.keyDown('space')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.press('space')),
                        lambda: (pyautogui.press('space'), pyautogui.keyDown('space')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.press('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.press('space')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.keyDown('space'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
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
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'))
                    ]) if not spin_btn else \
                    action.extend([
                        lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left'),
                        lambda: pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right'),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.doubleClick(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='left'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='left')),
                        lambda: (pyautogui.click(x=cx, y=BTM_Y - 105, button='right'), pyautogui.click(x=rand_x, y=rand_y, button='right')),
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
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.doubleClick(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='left'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='left')),
                        lambda: (pyautogui.click(x=rand_x, y=rand_y, button='right'), pyautogui.click(x=cx, y=BTM_Y - 105, button='right'))
                    ])

            if not action:
                logger.info("info", f"\t⚠️ No available spin actions for {spin_type}")
                return
            
            if not fast_mode:
                self.alert_queue.put(f"{spin_type}")
            
            # if not fast_mode and wait_before_spin:
            #     # interval_ms = Decimal(str(time.time())) - state.last_time
                
            #     if spin_type.startswith("auto") and "PG" in self.provider_name:
            #         reduce_ms = random.uniform(3.5, 4.5)
            #     elif spin_type.__contains__("turbo"):
            #         reduce_ms = random.uniform(0.0, 1.5)
            #     else:
            #         reduce_ms = random.uniform(2.5, 3.0) # avg: 1.79ms waiting time
                
            #     # waiting_time = float(interval_ms) - random.uniform(0.0, 3.0) # before this is 3
            #     waiting_time = float(self.countdown_interval) - reduce_ms
                
            #     if spin_type.endswith("delay"):# or spin_type.startswith("combo"):
            #         waiting_time = waiting_time - hold_delay
            #     elif spin_type.endswith("slide"):
            #         waiting_time = waiting_time - timeout_delay
            #     # elif spin_type.startswith("super"):
            #     #     if "PG" in self.provider_name:
            #     #         waiting_time = waiting_time - 0.3
            #     #     elif "JILI" in self.provider_name:
            #     #         waiting_time = waiting_time - 0.5
                
            #     # elif spin_type.startswith("auto") and "PG" in self.provider_name:
            #     #     waiting_time = 0
                    
            #     # sys.stdout.write(f"\t\t<{colors['BLNK']}🌀{colors['RES']} {colors['RED']}{spin_type.replace('_', ' ').upper()}{colors['RES']} Waiting Time: {colors['WHTE']}{waiting_time}{colors['RES']} Interval MS: {colors['WHTE']}{interval_ms}{colors['RES']} State-Interval: {colors['WHTE']}{state.interval}{colors['RES']}>\n")
                
            #     time.sleep(abs(waiting_time))
            # else:
            #     sys.stdout.write(f"\t\t<{colors['BLNK']}🌀{colors['RES']} {colors['RED']}SPIKE SPIN{colors['RES']}>\n")
                
            random.choice(action)()
        finally:
            self.spin_in_progress.clear()
            
    # --- Single alert thread for both queues ---
    def play_alert(self):
        voices_env = os.getenv("VOICES", "")
        VOICES_LIST = [v.strip() for v in voices_env.split(",") if v.strip()]
        VOICES = {name: name for name in VOICES_LIST}
        PING = os.getenv("PING")
        TINK = os.getenv("TINK")

        if platform.system() == "Darwin":
            while not self.stop_event.is_set():
                try:
                    # PreAlert has priority
                    if not self.prealert_queue.empty():
                        sound_file = self.prealert_queue.get()
                        if sound_file == "pre-alert":
                            subprocess.run(["afplay", TINK])
                        elif sound_file == "ping":
                            subprocess.run(["afplay", PING])
                        self.prealert_queue.task_done()
                        continue

                    # Normal alert queue (TTS)
                    if not self.alert_queue.empty():
                        sound_text = self.alert_queue.get()
                        voice = VOICES.get("Trinoids") if ("pull_score_spin" in sound_text or "bet max" in sound_text) else VOICES.get("Trinoids")
                        subprocess.run(["say", "-v", voice, "--", sound_text])
                        self.alert_queue.task_done()
                    else:
                        time.sleep(0.05)
                except Exception as e:
                    logger.info(f"[Alert Thread Error] {e}")

    # --- Data watcher with PreAlert priority ---
    def data_watcher(self):
        while not self.stop_event.is_set():
            try:
                game_json = self.redis.get("game")
                if not game_json:
                    time.sleep(0.1)
                    continue

                game_data = json.loads(game_json)
                game, provider = game_data.get("name"), game_data.get("provider")
                if not game or not provider:
                    time.sleep(0.1)
                    continue

                if self.game_name != game:
                    self.game_name = game
                    self.provider_name = provider
                    with self.lock:
                        self.history.clear()
                        self.already_alerted.clear()
                        self.last_snapshot_time = None
                        self.timer_start = None
                        self.last_value = None

                redis_key = f"api_data:{game}:{provider}"
                latest = self.redis.get(redis_key)
                if latest:
                    snapshot = json.loads(latest)
                    current_val = snapshot[self.header]
                    with self.lock:
                        # --- PreAlert detection first ---
                        if self.history:
                            last_val = self.history[-1][self.header]
                            predicted_next = current_val + (current_val - last_val)
                            predicted_delta = predicted_next - last_val
                            if abs(predicted_delta) >= 80:
                                self.alert_queue.put(str(int(abs(predicted_delta))))
                                # if not self.spin_triggered:
                                # self.spin(False, False, True, False,) # trending mode
                                # threading.Thread(target=self.spin, args=(False, False, True, False,), daemon=True)
                                # self.spin(False, False, False, True,) # normal mode
                                # self.spin(False, False, False, False,) # fast mode
                                    # self.spin_triggered = True
                                alert_id = f"{current_val}_{predicted_next:.4f}"
                                if alert_id not in self.already_alerted:
                                    snapshot["PreAlert"] = True
                                    snapshot["Predicted"] = predicted_next
                                    snapshot["PredictedTime"] = time.time() + 0.5
                                    self.prealert_queue.put("pre-alert")
                                    self.already_alerted.add(alert_id)
                                    logger.debug(f"[PreAlert Triggered] Snapshot: {snapshot}")
                                    
                                # self.alert_queue.put(str(int(abs(predicted_delta))))

                        # --- Then normal new-value alert ---
                        if self.last_value is None or current_val != self.last_value:
                             
                            # self.spin_triggered = False
                            # if not self.spin_triggered:
                            #     threading.Thread(target=self.spin, args=(False, False, False, True,), daemon=True).start()
                            #     # self.spin(False, False, True, False,) # trending mode
                            #     # self.spin(False, False, False, True,) # normal mode
                            #     # self.spin(False, False, False, False,) # fast mode
                            #     self.spin_triggered = True
                            
                            self.prealert_queue.put("ping")

                            now_time = time.time()
                            if self.last_snapshot_time:
                                self.countdown_interval = now_time - self.last_snapshot_time
                            else:
                                self.countdown_interval = 1
                            self.timer_start = now_time
                            self.last_snapshot_time = now_time
                            self.last_value = current_val
                            
                            # self.spin_triggered = False
                            # if not self.spin_triggered:
                            #     # self.spin(False, False, True, False,) # trending mode
                            #     self.spin(False, False, False, True,) # normal mode
                            #     # self.spin(False, False, False, False,) # fast mode
                            #     self.spin_triggered = True

                        self.history.append(snapshot)
                else:
                    with self.lock:
                        if self.history:
                            last_snapshot = self.history[-1].copy()
                            last_snapshot["last_updated"] = time.time()
                            self.history.append(last_snapshot)
                            
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Redis fetch error: {e}")
                time.sleep(1)

    # --- build_ohlc, draw remain unchanged ---
    def build_ohlc(self):
        with self.lock:
            if not self.history:
                return pd.DataFrame()
            df = pd.DataFrame(list(self.history))
            df["timestamp"] = pd.to_datetime(df["last_updated"].astype(float), unit="s")
            df = df.set_index("timestamp")
            df = df[[self.header] + [c for c in ["Predicted","PredictedTime"] if c in df.columns]]
            df = df[~df.index.duplicated(keep="last")]
            df["Open"] = df[self.header].shift(1)
            df["Close"] = df[self.header]
            df.loc[df.index[0], "Open"] = df.loc[df.index[0], "Close"]

            diffs = df[self.header].diff().abs().dropna()
            median_move = diffs.median() if not diffs.empty else 0
            self.epsilon = max(median_move*0.005, 1e-6)

            flat_mask = df["Open"] == df["Close"]
            df["High"] = df[["Open","Close"]].max(axis=1)
            df["Low"] = df[["Open","Close"]].min(axis=1)
            df.loc[flat_mask,"High"] += self.epsilon
            df.loc[flat_mask,"Low"] -= self.epsilon

            df["PreAlert"] = df.get("PreAlert", False)
            df["Slope"] = df["Close"].diff().fillna(0)
            df["SlopeSmooth"] = df["Slope"].rolling(SMOOTH_WINDOW, min_periods=1).mean()
            return df.tail(MAX_ROWS)

    def draw(self, _):
        df = self.build_ohlc()
        self.ax_candle.clear()
        self.ax_slope.clear()
        self.ax_candle.set_facecolor("black")
        self.ax_candle.tick_params(axis="y", colors="yellow")
        self.ax_candle.tick_params(axis="x", colors="white")
        self.ax_slope.tick_params(colors="magenta")
        self.ax_slope.yaxis.set_label_position("right")
        self.ax_slope.yaxis.tick_right()
        self.ax_candle.set_ylabel("Jackpot Value", color="yellow", fontsize=10)

        if df.empty:
            self.ax_candle.set_title(f"{self.chart_title} — Waiting for data", color="white")
            return

        # Candles
        mpf.plot(
            df[["Open","High","Low","Close"]],
            ax=self.ax_candle,
            type="candle",
            style=self.style,
            ylabel="Jackpot Value",
            datetime_format="%H:%M:%S.%f",
            show_nontrading=True,
            tight_layout=True
        )

        # Numeric close labels
        for idx, row in df.iterrows():
            close_val = row["Close"]
            open_val = row["Open"]
            y_pos = open_val + (close_val - open_val)*0.2 if close_val >= open_val else close_val + (open_val - close_val)*0.8
            self.ax_candle.text(idx, y_pos, f"{close_val:.2f}", color="yellow", fontsize=7, ha="center", va="center", zorder=20)

        # Last close line
        last_close = df["Close"].iloc[-1]
        self.ax_candle.axhline(last_close, color="yellow", linestyle="--", linewidth=1, zorder=5)
        self.ax_candle.text(0.01, 0.95, f"{last_close:.2f}", color="yellow",
                            fontsize=10, transform=self.ax_candle.transAxes,
                            verticalalignment="top", horizontalalignment="left",
                            zorder=20)

        # PreAlert markers with arrow and label
        pre_alerts = df[df["PreAlert"]]
        for idx in pre_alerts.index:
            predicted_val = df.loc[idx,"Predicted"] if "Predicted" in df.columns else df.loc[idx,"High"]
            marker_time = pd.to_datetime(df.loc[idx,"PredictedTime"], unit="s") if "PredictedTime" in df.columns else idx
            self.ax_candle.plot(marker_time, predicted_val+self.epsilon*2, marker="o", color="yellow", markersize=4, zorder=30)
            self.ax_candle.axvline(marker_time, color="yellow", linestyle=":", linewidth=0.8, alpha=0.3, zorder=3)
            self.ax_candle.annotate(
                f"{predicted_val:.2f}",
                xy=(marker_time, predicted_val+self.epsilon*2),
                xytext=(0,15),
                textcoords="offset points",
                arrowprops=dict(facecolor='yellow', shrink=0.05, width=1, headwidth=5),
                color="yellow",
                fontsize=8,
                ha="center"
            )

        # Slope line and dots
        slopes = df["SlopeSmooth"].values
        times = df.index
        for i in range(1, len(slopes)):
            self.ax_slope.plot(times[i-1:i+1], slopes[i-1:i+1], color="magenta", linewidth=1.5, zorder=40)
            dot_color = "lime" if slopes[i] >= 0 else "red"
            self.ax_slope.scatter(times[i], slopes[i], color=dot_color, s=15, zorder=45)
            self.ax_slope.annotate(f"{slopes[i]:.2f}", xy=(times[i], slopes[i]), xytext=(5,0),
                                   textcoords="offset points", color=dot_color, fontsize=7, ha="left", va="bottom", zorder=50)
        self.ax_slope.axhline(0, color="magenta", linestyle="--", linewidth=1, alpha=0.7, zorder=10)

        # Countdown in title
        if self.timer_start and self.countdown_interval:
            elapsed = time.time() - self.timer_start
            time_until_next = max(0, self.countdown_interval - elapsed)
            ratio = time_until_next / self.countdown_interval
        else:
            time_until_next = 0
            ratio = 0

        if ratio > 0.75:
            countdown_color = "lime"
        elif ratio > 0.50:
            countdown_color = "yellow"
        elif ratio > 0.25:
            countdown_color = "orange"
            # self.spin_triggered = False
        else:
            countdown_color = "red" if int(time.time()*2)%2==0 else "white"
            # if ratio < 0.10:
            #     if not self.spin_triggered:
            #         # threading.Thread(target=self.spin, args=(False, False, False, True,), daemon=True).start()
            #         # self.spin(False, False, True, False,) # trending mode
            #         self.spin(False, False, False, True,) # normal mode
            #         # self.spin(False, False, False, False,) # fast mode
            #         self.spin_triggered = True
                    
        self.ax_candle.set_title(
            f"{self.chart_title} — {self.game_name} | Next Iteration: {time_until_next:.2f}s",
            color=countdown_color
        )

        self.ax_slope.set_ylabel("Slope", color="magenta")
        self.ax_candle.set_xlabel("Time", color="white")
        self.ax_candle.grid(True, linestyle="--", alpha=0.3)

    def run(self):
        threading.Thread(target=self.play_alert, daemon=True).start()
        threading.Thread(target=self.data_watcher, daemon=True).start()
        
        self.alert_queue.put(f"{self.chart_title}")
        
        self.ani = FuncAnimation(
            self.fig, 
            self.draw, 
            interval=100, 
            cache_frame_data=False)
        
        plt.tight_layout()
        plt.show()
        self.stop_event.set()


if __name__ == "__main__":
    user_input = input(f"\n\n\tDo you want to enable {colors.get('CYN')}Auto Mode{colors.get('RES')} ({colors.get('DGRY')}Y/n{colors.get('RES')}): ").strip().lower()
    auto_mode = user_input in ("", "y", "yes") # default to yes
    fast_mode = False
    dual_slots = True
    split_screen = True
    left_slot = False
    right_slot = True
    
    # REVIEW CHANGE GAME CONFIG
    widescreen = False
    spin_btn = True
    
    if dual_slots and split_screen:
        if left_slot:
            CENTER_X, CENTER_Y = LEFT_SLOT_POS.get("center_x"), LEFT_SLOT_POS.get("center_y")
        elif right_slot:
            CENTER_X, CENTER_Y = RIGHT_SLOT_POS.get("center_x"), RIGHT_SLOT_POS.get("center_y")
    else:
        CENTER_X, CENTER_Y = SCREEN_POS.get("center_x"), SCREEN_POS.get("center_y")
    LEFT_X, RIGHT_X, TOP_Y, BTM_Y = 0, SCREEN_POS.get("right_x"), 0, SCREEN_POS.get("bottom_y")
    
    chart = ChartWatcher(
        header="value", 
        chart_title="Jackpot Pull Chart"
    ).run()
    