#!/usr/bin/env .venv/bin/python


import cv2, hashlib, glob, os, mss, pyautogui, re, redis, threading, time
import numpy as np
from collections import Counter, defaultdict
from wcwidth import wcswidth
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

VALID = {"P", "B", "T", "S", "X"}
ROWS = 6
COLS = 64
CELL_WIDTH = 3
VISIBLE_COLS = 20
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
MAIN_RESULTS = {"P", "B", "T"}
SIDE_RESULTS = {"S","X"}
ROIS = {
    "bigroad": (217, 695, 370, 88),
    "player1": (730, 695, 25, 35),
    "player2": (755, 695, 25, 35),
    "player3": (690, 700, 35, 25),
    "banker1": (920, 695, 25, 35),
    "banker2": (950, 695, 25, 35),
    "banker3": (975, 700, 35, 25)
}

TRAINING_HISTORIES = []

# def save_bigroad_dataset(bigroad_img, history):
#     """
#     Save both the image and extracted history.
#     Duplicate boards are ignored.
#     """
#     if not history: return

#     # Use history as fingerprint
#     fingerprint = hashlib.md5(history.encode()).hexdigest()

#     if r.exists(f"dataset:{fingerprint}"): return

#     timestamp = int(time.time() * 1000)

#     image_file = f"templates/screenshots/{timestamp}.png"
#     text_file = f"templates/screenshots/{timestamp}.txt"

#     cv2.imwrite(image_file, bigroad_img)

#     with open(text_file, "w") as f:
#         f.write(history)

#     r.set(f"dataset:{fingerprint}", 1)

#     print(f"[DATASET] Saved {image_file}")

def load_bigroad_data(folder):
    """
    Load every Big Road image/text into memory.

    Returns:
        list[str]
    """
    histories = []

    files = sorted(
        glob.glob(os.path.join(folder, "*.png")) +
        glob.glob(os.path.join(folder, "*.txt"))
    )

    print(f"Loading {len(files)} Big Road files...")

    for file in files:
        if file.endswith(".png"):
            history, _ = history_from_image(file)
        else:
            with open(file) as f:
                history = f.read()

        history = clean_prediction_history(history)

        if not history: continue

        histories.append(history)

        print(
            f"{os.path.basename(file):30} "
            f"{len(history):4} hands"
        )

    print(f"Loaded {len(histories)} histories.\n")

    return histories

# def load_all_histories():
#     permanent = load_bigroad_data(
#         "templates/bigroad",
#         "trained"
#     )

#     return permanent

def clean_history(history):
    history = history.upper()
    return "".join(c for c in history if c in VALID)

def clean_prediction_history(history):
    return "".join(
        x for x in history
        if x in "MAIN_RESULTS"
    )

def nearest_pattern_prediction(current_history, max_order=20):
    """
    Search every loaded history for the longest matching suffix.
    """
    current_history = clean_prediction_history(current_history)
    score = Counter()

    if not current_history: return score

    for history in TRAINING_HISTORIES:
        longest = min(
            max_order,
            len(current_history),
            len(history) - 1
        )

        for order in range(longest, 0, -1):
            pattern = current_history[-order:]
            start = 0

            while True:
                pos = history.find(pattern, start)

                if pos == -1: break

                next_pos = pos + order

                if next_pos < len(history): score[history[next_pos]] += 1

                start = pos + 1

            if sum(score.values()): break

    return score

def train_history(history, max_order=10):
    history = clean_prediction_history(history)

    for order in range(1, max_order + 1):
        if len(history) <= order:
            break

        for i in range(len(history) - order):
            pattern = history[i:i+order]
            nxt = history[i+order]

            r.hincrby(
                f"pattern:{pattern}",
                nxt,
                1
            )

def train_latest_transition(old_history, new_history):
    if len(new_history) <= len(old_history): return

    for order in range(1, 11):
        if len(new_history) <= order: break

        pattern = new_history[-order-1:-1]
        nxt = new_history[-1]

        if len(pattern) != order: continue

        r.hincrby(
            f"pattern:{pattern}",
            nxt,
            1
        )

def history_from_image(source):
    if isinstance(source, str): img = cv2.imread(source)
    else: img = source.copy()

    if img is None: return "", []

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    hsv_colors = {
        "P": [
            (np.array([95,100,100]), np.array([135,255,255]))
        ],
        "B": [
            (np.array([0,120,120]), np.array([10,255,255])),
            (np.array([170,120,120]), np.array([180,255,255]))
        ],
        "T": [
            (np.array([40,80,80]), np.array([90,255,255]))
        ]
    }

    circles = []

    for symbol, ranges in hsv_colors.items():
        mask = None

        for lo, hi in ranges:
            m = cv2.inRange(hsv, lo, hi)
            mask = m if mask is None else (mask | m)

        cnts, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )

        for c in cnts:
            if cv2.contourArea(c) < 50: continue

            (x, y), _ = cv2.minEnclosingCircle(c)

            circles.append({
                "x": int(x),
                "y": int(y),
                "symbol": symbol
            })

    # ---------- HISTORY FOR REDIS ----------
    ordered = sorted(
        circles,
        key=lambda c: (c["x"], c["y"])
    )

    history = "".join(c["symbol"] for c in ordered)

    return history, circles

def history_from_circles(circles):
    """
    Convert detected Big Road circles into a history string.

    Returns:
        BBBPPPTBB...
    """

    if not circles: return ""

    # Unique X/Y positions
    xs = sorted(set(c["x"] for c in circles))
    ys = sorted(set(c["y"] for c in circles))

    xmap = {x: i for i, x in enumerate(xs)}
    ymap = {y: i for i, y in enumerate(ys)}

    rows = len(ys)
    cols = len(xs)

    # Build temporary grid
    grid = [[None for _ in range(cols)] for _ in range(rows)]

    for circle in circles:
        row = ymap[circle["y"]]
        col = xmap[circle["x"]]

        if row < rows and col < cols:
            grid[row][col] = circle["symbol"]

    # Reconstruct history
    history = []

    for col in range(cols):
        for row in range(rows):
            symbol = grid[row][col]

            if symbol is None: continue

            history.append(symbol)

    return "".join(history)

# PADDING
def pad(text, width):
    clean = ANSI_RE.sub("", text)
    visible = wcswidth(clean)
    return text + " " * max(0, width-visible)

# ============================================================
# TREND
# ============================================================
def redis_pattern_prediction(history):
    history = clean_prediction_history(history)
    counter = Counter()
    for order in range(
        min(10, len(history)),
        0,
        -1
    ):

        pattern = history[-order:]
        values = r.hgetall(
            f"pattern:{pattern}"
        )

        if values:
            for k, v in values.items(): counter[k] += int(v)
            break

    return counter

# def trend_prediction(history):
#     score = Counter()
#     results = [
#         x for x in history
#         if x in ("P","B","T")
#     ]

#     if len(results) < 2: return score

#     last = results[-1]

#     # count current streak
#     streak = 1
#     i = len(results) - 2

#     while i >= 0 and results[i] == last:
#         streak += 1
#         i -= 1


#     if last == "T":
#         score["T"] += 35
#         score["B"] += 32
#         score["P"] += 33

#     else:
#         other = "P" if last == "B" else "B"

#         if streak == 1:
#             score[last] += 50
#             score[other] += 30
#             score["T"] += 20
#         elif streak == 2:
#             score[last] += 45
#             score[other] += 30
#             score["T"] += 25
#         elif streak >= 3:
#             score[last] += 35
#             score[other] += 35
#             score["T"] += 30

#     return score

# ============================================================
# PATTERN SEARCH
# ============================================================

def pattern_prediction(history, window=7):
    if len(history) <= window: return Counter()
    
    pattern = redis_pattern_prediction(history)
    counter = Counter()

    for i in range(len(history) - window):
        if history[i:i+window] == pattern:
            # counter[history[i+window]] += 1
            pattern = history[-window:]

    return counter

def tie_prediction(history):
    score = Counter()

    ties = history.count("T")

    if len(history) < 20: return score

    rate = ties / len(history)
    # normal tie rate
    if rate < 0.05: score["T"] += 5
    elif rate < 0.10: score["T"] += 15
    else: score["T"] += 25
    # last tie distance
    last_tie = history.rfind("T")

    if last_tie != -1:
        gap = len(history)-last_tie-1
        if gap >= 15: score["T"] += 10
        elif gap >= 8: score["T"] += 5

    return score

# ============================================================
# MARKOV
# ============================================================
def markov_prediction(history, order=3):
    if len(history) <= order: return Counter()
    model = defaultdict(Counter)

    for i in range(len(history)-order):
        state = history[i:i+order]
        model[state][history[i+order]] += 1

    return model[history[-order:]]

# ============================================================
# FREQUENCY
# ============================================================
def frequency_prediction(history):
    recent = [
        x for x in history[-100:]
        if x in MAIN_RESULTS
    ]

    return Counter(recent)

# ============================================================
# COMBINE
# ============================================================
def combine(pattern, markov, frequency, trend):
    score = Counter()

    engines = [
        (pattern,40),
        (markov,30),
        (trend,20),
        (frequency,10)
    ]

    for engine, weight in engines:
        total = sum(max(v,0) for v in engine.values())

        if total == 0: continue

        for k,v in engine.items():
            if v > 0: score[k] += (v / total) * weight

    # tie_history = []

    # for k in frequency:
    #     if k == "T":
    #         tie_history.append(frequency[k])

    # baseline baccarat tie probability
    score["T"] += 8
    # recent tie clustering
    if frequency["T"] >= 5: score["T"] += 15
    elif frequency["T"] >= 3: score["T"] += 8

    return score

# def make_prediction(history):
#     history = clean_prediction_history(history)
#     pattern = pattern_prediction(history)

#     markov = Counter()

#     for order in (3,2,1):
#         markov = markov_prediction(
#             history,
#             order
#         )

#         if markov: break

#     freq = frequency_prediction(history)
#     trend = trend_prediction(history)
#     tie = tie_prediction(history)

#     score = combine(
#         pattern,
#         markov,
#         freq,
#         trend
#     )

#     for k,v in tie.items(): score[k] += v * 0.5

#     return score

# ============================================================
# PRINT PREDICTION
# ============================================================
def print_prediction(history, score, data_src, bar_length: int = 10):
    history = clean_prediction_history(history)
    total = sum(score.values())
    counts = Counter(history)

    if total == 0: total = 1

    title = f"{colors['LYEL']}{data_src.upper()}" if data_src == 'historical' else f"{colors['LMAG']}{data_src.upper()}"
    
    print(f"\n{title} {colors['ORA']}PREDICTIONS{colors['CYN']}")
    print("-" * 20)

    names = {
        "P": f"{colors['BLU']}PLAYER{colors['RES']}",
        "B": f"{colors['RED']}BANKER{colors['RES']}",
        "T": f"{colors['GRE']}Tie{colors['RES']}",
        "S": f"{colors['ORA']}Small Tiger{colors['RES']}",
        "X": f"{colors['MAG']}Big Tiger{colors['RES']}"
    }

    blocks = {
        "P": "🟦",
        "B": "🟥",
        "T": "🟩",
        "S": "🟧",
        "X": "🟪"
    }

    ranking = []

    for k in ["P", "B", "T"]:
        score[k] = max(score[k],0)
        percentage = score[k] / total * 100

        ranking.append((percentage, k))
        filled_blocks = round((percentage / 100) * bar_length)
        empty_blocks = bar_length - filled_blocks

        bar = (
            blocks[k] * filled_blocks +
            "⬛" * empty_blocks
        )

        print(
            f"{names[k]:20}"
            f"{colors['CYN']}{percentage:6.2f} {colors['WHTE']}%  "
            f"{bar}  {colors['LYEL']}{counts[k]}{colors['WHTE']}"
        )

    # confidence still uses highest two
    sorted_rank = sorted(
        ranking,
        reverse = True
    )

    confidence = 0

    if len(sorted_rank) >= 2: confidence = sorted_rank[0][0]-sorted_rank[1][0]

    print(
        f"\nTotal Hands :\t{colors['LYEL']}{sum(counts.values())}{colors['WHTE']}"
        # f"\nTotal Hands :\t{colors['LYEL']}{total}{colors['WHTE']}"
        f"\nConfidence :\t{colors['ORA']}{confidence:.2f} {colors['WHTE']}%"
    )

class GameState:
    def __init__(self):
        self.results = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

    def add_result(self,result):
        with self.lock:
            for x in result:
                if x in VALID: self.results.append(x)

    def get_results(self):
        with self.lock:
            return self.results.copy()

    def stop(self):
        self.stop_event.set()

class Cell:
    def __init__(self, winner, row, col):
        self.winner = winner
        self.row = row
        self.col = col
        self.tie = 0
        self.small = False
        self.big = False

class Shoe:
    def __init__(self, decks=8):
        self.decks = decks
        self.reset()

    def reset(self):
        self.cards_seen = 0
        self.hands = 0

        self.cards = {
            "A": 4 * self.decks,
            "2": 4 * self.decks,
            "3": 4 * self.decks,
            "4": 4 * self.decks,
            "5": 4 * self.decks,
            "6": 4 * self.decks,
            "7": 4 * self.decks,
            "8": 4 * self.decks,
            "9": 4 * self.decks,
            "T": 16 * self.decks
        }

class Vision:
    def __init__(self, state):
        self.state = state
        self.sct = mss.MSS()
        self.initialized = False
        self.previous = {}
        self.cards = {}
        self.last_card_time = {}
        self.history = ""
        # self.hand_locked = False
        self.empty_frames = 0
        self.lock = threading.Lock()

        self.templates = {}

        for rank in (
            "A","2","3","4","5",
            "6","7","8","9","T"
        ):

            img = cv2.imread(
                f"templates/cards/{rank}.png",
                0
            )

            if img is None:
                continue

            img = cv2.threshold(
                img,
                150,
                255,
                cv2.THRESH_BINARY
            )[1]

            img = cv2.resize(
                img,
                (35,35)
            )

            self.templates[rank] = [
                img,
                cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE),
                cv2.rotate(img, cv2.ROTATE_180),
                cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE),
            ]

        # Change these later
        self.monitor = {
            "top": 0,
            "left": 0,
            "width": 1920,
            "height": 1080
        }

    def capture(self):
        frame = np.array(self.sct.grab(self.monitor))
        frame = cv2.cvtColor(
            frame,
            cv2.COLOR_BGRA2BGR
        )

        return frame

    def is_natural(self, cards):
        player = [
            cards.get("player1"),
            cards.get("player2")
        ]

        banker = [
            cards.get("banker1"),
            cards.get("banker2")
        ]

        player_total = sum(
            self.baccarat_value(c)
            for c in player
            if c
        ) % 10

        banker_total = sum(
            self.baccarat_value(c)
            for c in banker
            if c
        ) % 10

        return (
            player_total in (8,9)
            or
            banker_total in (8,9)
        )

    def hand_finished(self):
        required = [
            "player1",
            "player2",
            "banker1",
            "banker2"
        ]

        if not all(x in self.cards for x in required): return False

        player_cards = [
            self.cards.get("player1"),
            self.cards.get("player2"),
            self.cards.get("player3")
        ]

        banker_cards = [
            self.cards.get("banker1"),
            self.cards.get("banker2"),
            self.cards.get("banker3")
        ]

        player_total = sum(
            self.baccarat_value(x)
            for x in player_cards[:2]
        ) % 10

        banker_total = sum(
            self.baccarat_value(x)
            for x in banker_cards[:2]
        ) % 10

        # Natural
        if player_total >= 8 or banker_total >= 8: return True

        player_draw = False

        # Player rule
        if player_total <= 5: player_draw = True
        if player_draw and player_cards[2] is None: return False

        player3 = (
            self.baccarat_value(player_cards[2])
            if player_cards[2]
            else None
        )

        if player3 is None:
            if banker_total <= 5: return False
        else:
            rules = {
                3: lambda: player3 != 8,
                4: lambda: player3 in range(2,8),
                5: lambda: player3 in range(4,8),
                6: lambda: player3 in (6,7)
            }

            if banker_total <= 2: return False
            if banker_total in rules and rules[banker_total](): return False
            
        return True
    
    def run(self):
        while not self.state.stop_event.is_set():
            frame = self.capture()
            bigroad = self.crop(frame, ROIS["bigroad"])
            history, _ = history_from_image(bigroad)
            # ----------------------------------
            # Initial Big Road import
            # ----------------------------------
            if not self.initialized:
                if history != self.history:
                    cv2.imwrite(
                        "templates/screenshots/bigroad.png",
                        bigroad
                    )

                self.state.add_result(history)
                self.history = history
                # Train only once during startup
                train_history(history)
                self.initialized = True
                print(f"Initial history: {history}")

            x, y = pyautogui.position()
            print(f"\r{x}, {y}", end="", flush=True)

            cv2.putText(
                frame,
                f"{x},{y}",
                (20,40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0,255,0),
                2
            )

            self.draw_rois(frame)

            for name, roi in ROIS.items():
                if name == "bigroad": continue 

                card = self.crop(frame, roi)

                if not self.has_card(card): continue

                if self.is_new_card(name, card):
                    now = time.time()
                    last = self.last_card_time.get(name, 0)

                    if now - last < 1: continue

                    self.last_card_time[name] = now
                    corner = self.card_corner(card)

                    self.save_corner(corner)

                    rank = self.detect_rank(corner)

                    with self.lock: self.cards[name] = rank

                    # bigroad = self.crop(frame, ROIS["bigroad"])
                    # history, _ = history_from_image(bigroad)

                if history != self.history:
                    if history.startswith(self.history):
                        new_results = history[len(self.history):]

                        for winner in new_results: self.state.add_result(winner)
                        # Learn ONLY the newly appended transition.
                        # The initial history was already trained during startup.
                        train_latest_transition(
                            self.history,
                            history
                        )
                    else:
                        print("[SYNC] Big Road resynchronized.")
                        # History changed unexpectedly (shoe reset/manual correction).
                        # Retrain only if this exact history has never been imported.
                        fingerprint = hashlib.md5(history.encode()).hexdigest()

                        if not r.exists(f"trained:{fingerprint}"):
                            train_history(history)
                            r.set(f"trained:{fingerprint}", 1)

                    self.history = history

            if self.new_hand_detected(frame): self.reset_hand()

            if cv2.waitKey(1) == ord("q"):
                self.state.stop()
                break

        cv2.destroyAllWindows()
        time.sleep(0.05)

    def draw_rois(self, frame):
        for name, (x, y, w, h) in ROIS.items():
            cv2.rectangle(
                frame,
                (x, y),
                (x + w, y + h),
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                name,
                (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0,255,0),
                1
            )

    def crop(self, frame, roi):
        x, y, w, h = roi

        return frame[
            y:y+h,
            x:x+w
        ]

    def has_card(self, roi):
        if roi.size == 0: return False

        gray = cv2.cvtColor(
            roi,
            cv2.COLOR_BGR2GRAY
        )

        white = cv2.threshold(
            gray,
            180,
            255,
            cv2.THRESH_BINARY
        )[1]

        ratio = (
            cv2.countNonZero(white)
            /
            white.size
        )

        return ratio > 0.25

    def is_new_card(self, name, roi):
        gray=cv2.cvtColor(
            roi,
            cv2.COLOR_BGR2GRAY
        )

        gray=cv2.GaussianBlur(
            gray,
            (5,5),
            0
        )

        old = self.previous.get(name)
        self.previous[name] = gray

        if old is None: return True

        diff = cv2.absdiff(gray,old)
        score = np.mean(diff)

        return score > 25

    def has_any_cards(self, frame):
        for roi in ROIS.values():
            card = self.crop(frame, roi)

            if self.has_card(card): return True

        return False

    def card_corner(self, card):
        # return card[
        #     0:35,
        #     0:35
        # ]
        return card[0:16, 0:35]

    def save_corner(self, corner):
        filename = f"templates/screenshots/{int(time.time()*1000)}.png"
        # print("Saving: ", filename)

        cv2.imwrite(filename, corner)

    def detect_rank(self, corner):
        gray = cv2.cvtColor(
            corner,
            cv2.COLOR_BGR2GRAY
        )

        gray = cv2.GaussianBlur(
            gray,
            (3,3),
            0
        )

        gray = cv2.threshold(
            gray,
            150,
            255,
            cv2.THRESH_BINARY
        )[1]

        gray = cv2.resize(
            gray,
            (35,35)
        )

        best = None
        best_score = 0

        for rank, rotations in self.templates.items():
            for rotated in rotations:

                result = cv2.matchTemplate(
                    gray,
                    rotated,
                    cv2.TM_CCOEFF_NORMED
                )

                score = result.max()

                if score > best_score:
                    best_score = score
                    best = rank

        print(f"[MATCH] {best} ({best_score:.3f})")
        return best

    def baccarat_value(self, rank):
        if not rank or rank == "?": return 0
        if rank == "A": return 1
        if rank in ("T", "J", "Q", "K"): return 0

        try:
            return int(rank)
        except ValueError:
            return 0

    # def evaluate_hand(self, cards):
    #     player = [
    #         cards.get("player1"),
    #         cards.get("player2"),
    #         cards.get("player3")
    #     ]

    #     banker = [
    #         cards.get("banker1"),
    #         cards.get("banker2"),
    #         cards.get("banker3")
    #     ]

    #     # wait until all required cards are known
    #     all_cards = player[:2] + banker[:2]

    #     if any(
    #         c is None or c == "?"
    #         for c in all_cards
    #     ):
    #         return None

    #     player_total = sum(
    #         self.baccarat_value(c)
    #         for c in player
    #         if c not in (None, "?")
    #     ) % 10

    #     banker_total = sum(
    #         self.baccarat_value(c)
    #         for c in banker
    #         if c not in (None, "?")
    #     ) % 10

    #     print(
    #         f"Player {player} = {player_total}"
    #     )

    #     print(
    #         f"Banker {banker} = {banker_total}"
    #     )

    #     if player_total > banker_total: return "P"
    #     if banker_total > player_total: return "B"

    #     return "T"
    
    def new_hand_detected(self,frame):
        empty=0

        for roi in ROIS.values():
            card=self.crop(frame,roi)
            if not self.has_card(card): empty+=1

        if empty >= 6: self.empty_frames += 1
        else: self.empty_frames = 0

        return self.empty_frames > 15
    
    def reset_hand(self):
        self.cards = {}
        self.previous = {}
        # self.hand_locked = False

class BigRoad:
    def __init__(self, rows=ROWS, cols=COLS):
        self.cols = cols
        self.rows = rows

        self.grid = [
            [None for _ in range(cols)]
            for _ in range(rows)
        ]

        self.current = None
        self.row = 0
        self.col = 0
        self.base_col = 0
        self.max_col = 0
        self.cells = []

    def place(self, result):
        cell = Cell(result, self.row, self.col)
        self.grid[self.row][self.col] = cell
        self.cells.append(cell)

        self.max_col = max(
            self.max_col,
            self.col
        )

    def add(self,result):
        if result in ("T","S","X"):
            if self.current is not None:
                cell = self.grid[self.row][self.col]

                if cell:
                    if result == "T": cell.tie += 1
                    elif result == "S": cell.small = True
                    elif result == "X": cell.big = True

            return
        
        # first
        if self.current is None:            
            self.current = result
            self.row = 0
            self.col = 0
            self.base_col = 0

            self.place(result)
            return

        # same side
        if result == self.current:
            self.extend(result)
            return

        # change side
        self.current = result
        self.base_col += 1
        self.col = self.base_col
        self.row = 0

        # find free column
        while self.col < self.cols:
            if self.grid[0][self.col] is None: break

            self.col += 1

        if self.col >= self.cols:
            raise RuntimeError(
                "Big Road full"
            )
        
        self.place(result)

    def extend(self,result):
        # normal down
        if (
            self.row + 1 < self.rows
            and self.grid[self.row+1][self.col] is None
        ):
            self.row += 1
            self.place(result)
            return

        # bottom reached
        # dragon tail
        c = self.col + 1

        while c < self.cols:
            if self.grid[self.rows-1][c] is None:
                self.col = c
                self.row = self.rows - 1
                self.place(result)
                return

            c += 1

        self.shift_left()

    def shift_left(self):
        for r in range(self.rows):
            self.grid[r].pop(0)
            self.grid[r].append(None)

        for c in self.cells: c.col -= 1

        self.col -= 1
        self.base_col -= 1
        self.max_col -= 1

    def validate(self):
        for cell in self.cells: assert self.grid[cell.row][cell.col] is cell

    def debug(self):
        print("\nMove Winner Row Col Tie")
        print("-"*30)

        for i,c in enumerate(self.cells,1):
            print(
                f"{i:4} "
                f"{c.winner:^6} "
                f"{c.row:3} "
                f"{c.col:3} "
                f"{c.tie:3}"
            )

# ============================================================
# DRAW BIG ROAD
# ============================================================
def render_cell(cell):
    if cell is None: return " "

    circled = {
        1: "⬤",
        2: "②",
        3: "③",
        4: "④",
        5: "⑤",
        "S": "Ⓢ",
        "X": "Ⓑ"
    }

    text = (
        f"{colors['LRED'] if cell.winner == 'B' else colors['LBLU']}"
        f"{circled[1]}"
        f"{colors['RES']}"
    )

    # if cell.tie:
    #     text = (
    #         f"{colors['BLGRE']}{circled.get(cell.tie, str(cell.tie))}{colors['RES']}"
    #     )
    if cell.tie:
        if 1 <= cell.tie <= 5: symbol = circled[cell.tie]
        else: symbol = str(cell.tie)

        text = (
            f"{colors['BLGRE']}"
            f"{symbol}"
            f"{colors['RES']}"
        )

    if cell.small or cell.big:
        # text = f"{colors['LRED'] if cell.winner == "B" else colors['LBLU']}{circled.get("X") if cell.big else circled.get("S")}{colors['RES']}"
        text = (
            f"{colors['LRED'] if cell.winner == 'B' else colors['LBLU']}"
            f"{circled['X'] if cell.big else circled['S']}"
            f"{colors['RES']}"
        )

    return text

def draw_detected_board(circles):
    print()
    print("=" * 65)
    print(" DETECTED BIG ROAD")
    print("=" * 65)

    # Build empty board
    grid = [[None for _ in range(COLS)] for _ in range(ROWS)]

    if circles:
        xs = sorted(set(c["x"] for c in circles))
        ys = sorted(set(c["y"] for c in circles))

        xmap = {x: i for i, x in enumerate(xs)}
        ymap = {y: i for i, y in enumerate(ys)}

        for c in circles:
            row = ymap[c["y"]]
            col = xmap[c["x"]]
            
            if row < ROWS and col < COLS:
                grid[row][col] = c["symbol"]

    # Determine last visible columns (same as draw_big_road)
    max_col = 0
    
    if circles: max_col = min(len(xs) - 1, COLS - 1)

    start_col = max(0, max_col - VISIBLE_COLS + 1)
    end_col = max_col + 1

    if start_col > 0:
        print(f"{colors['YEL']}... showing last {VISIBLE_COLS} columns{colors['RES']}")

    # Column numbers
    print("\n    ", end="")
    for c in range(start_col, end_col):
        print(f"{colors['CYN']}{c + 1:^{CELL_WIDTH}}", end="")
    print()

    symbol_map = {
        "P": f"{colors['LBLU']}⬤{colors['RES']}",
        "B": f"{colors['LRED']}⬤{colors['RES']}",
        "T": f"{colors['BLGRE']}⬤{colors['RES']}",
    }

    # Draw rows (same formatting)
    for r in range(ROWS):
        line = f"{colors['CYN']}{r + 1} {colors['YEL']}| {colors['RES']}"

        for c in range(start_col, end_col):
            symbol = grid[r][c]
            cell = symbol_map.get(symbol, " ")
            line += pad(cell, CELL_WIDTH)

        print(line)

def draw_bigroad(results):
    road = BigRoad(
        ROWS,
        COLS
        # max(COLS,len(results)+10)
    )

    for ch in results: road.add(ch)

    road.validate()
    grid = road.grid

    print()
    print("=" * 65)
    print(" BIG ROAD")
    print("=" * 65)

    if LOG_LEVEL == "DEBUG": road.debug()

    # -----------------------------------
    # Show only the last VISIBLE_COLS
    # -----------------------------------
    start_col = max(0, road.max_col - VISIBLE_COLS + 1)
    end_col = road.max_col + 1

    if start_col > 0:
        print(f"{colors['YEL']}... showing last {VISIBLE_COLS} columns{colors['RES']}")

    # Column numbers
    print("\n    ", end="")

    for c in range(start_col, end_col):
        print(
            f"{colors['CYN']}{c + 1:^{CELL_WIDTH}}",
            end=""
        )

    print()

    # Grid
    for r in range(ROWS):
        line = f"{colors['CYN']}{r + 1} {colors['YEL']}| {colors['RES']}"

        for c in range(start_col, end_col):
            cell = render_cell(grid[r][c])
            line += pad(cell, CELL_WIDTH)

        print(line)

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True
    )

    try:
        r.ping()
        print("info", f"✅ Connected to Redis")
    except redis.exceptions.ConnectionError as e:
        print("error", f"🤖❌ Redis connection failed  {e}")
        raise SystemExit(1)

    try:
        folder = "templates/screenshots"

        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)

            if os.path.isfile(file_path):
                os.remove(file_path)
    except FileNotFoundError:
        print(f"Folder not found: {folder}")

    except PermissionError:
        print(f"Permission denied: {folder}")
    
    state = GameState()
    vision = Vision(state)
    # frame = vision.capture()
    # bigroad = vision.crop(
    #     frame,
    #     ROIS["bigroad"]
    # )

    # cv2.imwrite("debug_bigroad.png", bigroad)

    # history, circles = history_from_image(bigroad)
    # print(f"Initial history: {history}")
    # state.add_result(history)
    # draw_detected_board(circles)

    # IMPORT_VERSION = 1
    TRAINING_HISTORIES = load_bigroad_data("templates/bigroad")

    # if r.get("bigroad_version") != str(IMPORT_VERSION):
    #     load_bigroad_data(
    #         "templates/bigroad",
    #         "trained"
    #     )

    #     r.set(
    #         "bigroad_version",
    #         IMPORT_VERSION
    #     )

    vision_thread = threading.Thread(
        target = vision.run,
        daemon = True
    )

    vision_thread.start()

    try:
        while True:
            history = "".join(state.get_results())

            if history:
                os.system("cls" if os.name == "nt" else "clear")

                # circles = history_from_image(vision.crop(vision.capture(),ROIS["bigroad"]))[1]
                # history_from_circles(circles)

                # draw_detected_board(history_from_image(vision.crop(vision.capture(),ROIS["bigroad"]))[1])

                draw_detected_board(history_from_image(
                    vision.crop(
                        vision.capture(),
                        ROIS["bigroad"]
                    )
                )[1])
                
                redis_score = redis_pattern_prediction(history)
                nearest_score = nearest_pattern_prediction(history)

                # score = Counter()

                # score.update(redis_score)
                # score.update(nearest_score)

                # print_prediction(history, score, 'combined')

                print_prediction(history, redis_score, 'historical')
                print_prediction(history, nearest_score, 'game')

            time.sleep(0.5)
    except KeyboardInterrupt:
        state.stop()
    finally:
        vision_thread.join(timeout=3)
        print("Exited")
