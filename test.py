#!/usr/bin/env .venv/bin/python

import cv2
import hashlib
import glob
import os
import math
import mss
import pyautogui
import re
import redis
import threading
import time

import numpy as np

from collections import Counter, defaultdict
from wcwidth import wcswidth
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# Prevent missing color variables from crashing the program.
colors = defaultdict(str)

for key, value in os.environ.items():
    if (
        key.isupper()
        and not key.startswith("DB_")
        and not key.startswith("PROVIDER_")
    ):
        try:
            colors[key] = value.encode("utf-8").decode("unicode_escape")
        except Exception:
            colors[key] = value


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")


# Redis connection is initialized in main().
r = None


# ============================================================
# CONSTANTS
# ============================================================

VALID = {"P", "B", "T", "S", "X"}

MAIN_RESULTS = {"P", "B", "T"}
SIDE_RESULTS = {"S", "X"}

ROWS = 6
COLS = 64

CELL_WIDTH = 3
VISIBLE_COLS = 20

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


ROIS = {
    "bigroad": (217, 695, 370, 88),

    "player1": (730, 695, 25, 35),
    "player2": (755, 695, 25, 35),
    "player3": (690, 700, 35, 25),

    "banker1": (920, 695, 25, 35),
    "banker2": (950, 695, 25, 35),
    "banker3": (975, 700, 35, 25),
}


TRAINING_HISTORIES = []


# ============================================================
# BIG ROAD IMAGE DETECTION
# ============================================================

def history_from_image(source):
    """
    Detect Big Road circles and return them in true Big Road order.

    IMPORTANT:
    Do NOT simply sort circles by raw (x, y).

    Big Road is organized as:
        column -> row

    Therefore we first cluster circles into approximate X columns,
    then sort circles vertically inside each column.

    Returns:
        history, circles
    """

    if isinstance(source, str):
        img = cv2.imread(source)
    else:
        img = source.copy()

    if img is None or img.size == 0:
        return "", []

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    hsv_colors = {
        "P": [
            (
                np.array([90, 60, 60]),
                np.array([140, 255, 255]),
            )
        ],

        "B": [
            (
                np.array([0, 70, 70]),
                np.array([15, 255, 255]),
            ),
            (
                np.array([165, 70, 70]),
                np.array([180, 255, 255]),
            ),
        ],

        "T": [
            (
                np.array([35, 50, 50]),
                np.array([95, 255, 255]),
            )
        ],
    }

    circles = []

    # ============================================================
    # DETECT CIRCLES
    # ============================================================

    for symbol, ranges in hsv_colors.items():

        mask = np.zeros(
            hsv.shape[:2],
            dtype=np.uint8,
        )

        for lo, hi in ranges:

            current = cv2.inRange(
                hsv,
                lo,
                hi,
            )

            mask = cv2.bitwise_or(
                mask,
                current,
            )

        kernel = np.ones(
            (2, 2),
            np.uint8,
        )

        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            kernel,
        )

        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        for contour in contours:

            area = cv2.contourArea(contour)

            if area < 15:
                continue

            if area > 1000:
                continue

            (x, y), radius = cv2.minEnclosingCircle(
                contour
            )

            if radius < 3:
                continue

            if radius > 15:
                continue

            circles.append({
                "x": float(x),
                "y": float(y),
                "radius": float(radius),
                "symbol": symbol,
            })

    # ============================================================
    # REMOVE DUPLICATES
    # ============================================================

    # Sort by position only for duplicate removal.
    circles.sort(
        key=lambda c: (
            c["x"],
            c["y"],
        )
    )

    unique = []

    for circle in circles:

        duplicate = False

        for existing in unique:

            dx = (
                circle["x"]
                - existing["x"]
            )

            dy = (
                circle["y"]
                - existing["y"]
            )

            distance = math.sqrt(
                dx * dx + dy * dy
            )

            if distance < 8:

                duplicate = True
                break

        if not duplicate:
            unique.append(circle)

    circles = unique

    if not circles:
        return "", []

    # ============================================================
    # CLUSTER INTO BIG ROAD COLUMNS
    # ============================================================
    #
    # THIS IS THE IMPORTANT FIX.
    #
    # Do not assume:
    #
    #     x1 == x2
    #
    # for circles in the same column.
    #
    # Instead, circles whose X positions are close together
    # are considered one Big Road column.
    #

    COLUMN_TOLERANCE = 9.0

    circles_by_x = sorted(
        circles,
        key=lambda c: c["x"],
    )

    columns = []

    for circle in circles_by_x:

        placed = False

        # Find the nearest existing column.
        best_column = None
        best_distance = float("inf")

        for column in columns:

            center_x = column["center_x"]

            distance = abs(
                circle["x"] - center_x
            )

            if (
                distance <= COLUMN_TOLERANCE
                and distance < best_distance
            ):

                best_column = column
                best_distance = distance

        if best_column is not None:

            best_column["circles"].append(
                circle
            )

            # Recalculate column center.
            best_column["center_x"] = (
                sum(
                    c["x"]
                    for c in best_column["circles"]
                )
                / len(best_column["circles"])
            )

            placed = True

        if not placed:

            columns.append({
                "center_x": circle["x"],
                "circles": [circle],
            })

    # ============================================================
    # SORT COLUMNS LEFT -> RIGHT
    # ============================================================

    columns.sort(
        key=lambda column: column["center_x"]
    )

    # ============================================================
    # SORT CIRCLES TOP -> BOTTOM INSIDE EACH COLUMN
    # ============================================================

    ordered_circles = []

    for column in columns:

        column["circles"].sort(
            key=lambda c: c["y"]
        )

        ordered_circles.extend(
            column["circles"]
        )

    # ============================================================
    # FINAL HISTORY
    # ============================================================

    history = "".join(
        circle["symbol"]
        for circle in ordered_circles
        if circle.get("symbol") in VALID
    )

    return history, ordered_circles


def history_from_circles(circles):
    """
    Convert detected Big Road circles into a history string.

    This assumes circles have already been detected and grouped
    into approximate columns/rows.
    """

    if not circles:
        return ""

    # Sort by X first.
    ordered = sorted(
        circles,
        key=lambda c: (
            c["x"],
            c["y"],
        )
    )

    return "".join(
        c["symbol"]
        for c in ordered
        if c.get("symbol") in VALID
    )


# ============================================================
# TEXT HELPERS
# ============================================================

def pad(text, width):
    clean = ANSI_RE.sub("", text)

    visible = wcswidth(clean)

    if visible < 0:
        visible = len(clean)

    return text + " " * max(
        0,
        width - visible,
    )


# ============================================================
# GAME STATE
# ============================================================

class GameState:

    def __init__(self):
        self.results = []

        self.lock = threading.Lock()

        self.stop_event = threading.Event()

    def add_result(self, result):

        with self.lock:

            for char in result:

                if char in VALID:
                    self.results.append(char)

    def set_results(self, result):

        result = clean_history(result)

        with self.lock:
            self.results = list(result)

    def get_results(self):

        with self.lock:
            return self.results.copy()

    def stop(self):
        self.stop_event.set()


# ============================================================
# BIG ROAD CELL
# ============================================================

class Cell:

    def __init__(self, winner, row, col):

        self.winner = winner

        self.row = row
        self.col = col

        self.tie = 0

        self.small = False
        self.big = False

class PredictionTracker:

    def __init__(self):

        self.lock = threading.Lock()

        self.correct = 0
        self.incorrect = 0
        self.pushes = 0

        # Primary prediction: P / B / T
        self.pending_prediction = None

        # Secondary P/B prediction.
        # Used when primary prediction is T
        # and actual result is P/B.
        self.pending_secondary = None

        self.pending_history = ""

        self.last_result = None

        self.evaluation_number = 0

    # ========================================================
    # STORE PREDICTION
    # ========================================================

    def set_prediction(
        self,
        prediction,
        secondary_prediction,
        history,
    ):

        history = clean_history(history)

        if prediction not in VALID:
            return False

        if secondary_prediction not in MAIN_RESULTS:
            return False

        if not history:
            return False

        with self.lock:

            # Never replace an existing pending prediction.
            if self.pending_prediction is not None:
                return False

            self.pending_prediction = prediction
            self.pending_secondary = secondary_prediction
            self.pending_history = history

            print(
                "\n[TRACKER] 🎯 PREDICTION STORED"
                f"\n  Primary   : {prediction}"
                f"\n  P/B Backup : {secondary_prediction}"
                f"\n  Based on  : {history}"
                f"\n  Waiting for result #{len(history) + 1}"
            )

            return True

    # ========================================================
    # EVALUATE NEW BIG ROAD RESULT
    # ========================================================

    def evaluate_bigroad(self, history):

        history = clean_history(history)

        if not history:
            return None

        with self.lock:

            if self.pending_prediction is None:
                return None

            prediction = self.pending_prediction
            secondary = self.pending_secondary
            prediction_history = self.pending_history

            # ------------------------------------------------
            # HISTORY MUST MATCH
            # ------------------------------------------------

            if not history.startswith(
                prediction_history
            ):

                # print(
                #     "\n[TRACKER] ⚠️ HISTORY MISMATCH"
                #     f"\n  Prediction history : "
                #     f"{prediction_history}"
                #     f"\n  Current history    : "
                #     f"{history}"
                # )

                return None

            # ------------------------------------------------
            # NO NEW RESULT
            # ------------------------------------------------

            if len(history) <= len(
                prediction_history
            ):
                return None

            new_results = history[
                len(prediction_history):
            ]

            # ------------------------------------------------
            # PROCESS NEW RESULTS
            # ------------------------------------------------

            for actual in new_results:

                # =================================================
                # TIE
                # =================================================

                if actual == "T":

                    # If T was the primary prediction,
                    # the prediction is immediately correct.
                    if prediction == "T":

                        self.correct += 1

                        status = "correct"

                        result = {
                            "status": status,
                            "prediction": prediction,
                            "secondary": secondary,
                            "actual": actual,
                            "correct": True,
                            "used_secondary": False,
                        }

                        self.last_result = result

                        self.evaluation_number += 1

                        result["number"] = (
                            self.evaluation_number
                        )

                        print(
                            "\n[TRACKER] ✅"
                            "\n  Primary    : T"
                            f"\n  Actual     : {actual}"
                            "\n  Reason     : T prediction hit"
                        )

                        # T prediction is settled.
                        self.pending_prediction = None
                        self.pending_secondary = None
                        self.pending_history = ""

                        return result

                    # ------------------------------------------------
                    # TIE WHEN PRIMARY WAS P/B
                    # ------------------------------------------------
                    #
                    # A T does NOT settle a P/B prediction.
                    #
                    # Keep waiting for the actual P/B result.
                    #
                    else:

                        self.pushes += 1

                        self.last_result = {
                            "status": "push",
                            "prediction": prediction,
                            "secondary": secondary,
                            "actual": "T",
                            "correct": None,
                            "used_secondary": False,
                        }

                        self.evaluation_number += 1

                        self.last_result["number"] = (
                            self.evaluation_number
                        )

                        print(
                            "\n[TRACKER] ⏸ TIE"
                            f"\n  Prediction : {prediction}"
                            "\n  Actual     : T"
                            "\n  P/B prediction remains PENDING"
                        )

                        # IMPORTANT:
                        # DO NOT CLEAR PENDING PREDICTION.
                        continue

                # =================================================
                # PLAYER / BANKER
                # =================================================

                if actual in MAIN_RESULTS:

                    # ------------------------------------------------
                    # PRIMARY P/B PREDICTION
                    # ------------------------------------------------

                    if prediction in MAIN_RESULTS:

                        used_secondary = False

                        correct = (
                            prediction == actual
                        )

                    # ------------------------------------------------
                    # PRIMARY WAS T
                    # FALL BACK TO SECONDARY P/B
                    # ------------------------------------------------

                    else:

                        used_secondary = True

                        correct = (
                            secondary == actual
                        )

                    # ------------------------------------------------
                    # CORRECT
                    # ------------------------------------------------

                    if correct:

                        self.correct += 1

                        status = "correct"

                        print(
                            "\n[TRACKER] ✅"
                            f"\n  Primary    : {prediction}"
                            f"\n  Secondary  : {secondary}"
                            f"\n  Actual     : {actual}"
                        )

                        if used_secondary:

                            print(
                                "  Used       : "
                                "SECONDARY P/B"
                            )

                    # ------------------------------------------------
                    # INCORRECT
                    # ------------------------------------------------

                    else:

                        self.incorrect += 1

                        status = "incorrect"

                        print(
                            "\n[TRACKER] ❌"
                            f"\n  Primary    : {prediction}"
                            f"\n  Secondary  : {secondary}"
                            f"\n  Actual     : {actual}"
                        )

                        if used_secondary:

                            print(
                                "  Used       : "
                                "SECONDARY P/B"
                            )

                    result = {
                        "status": status,
                        "prediction": prediction,
                        "secondary": secondary,
                        "actual": actual,
                        "correct": correct,
                        "used_secondary": used_secondary,
                    }

                    self.last_result = result

                    self.evaluation_number += 1

                    result["number"] = (
                        self.evaluation_number
                    )

                    # ------------------------------------------------
                    # P/B RESULT SETTLES THE PREDICTION
                    # ------------------------------------------------

                    self.pending_prediction = None
                    self.pending_secondary = None
                    self.pending_history = ""

                    return result

            # Only ties occurred.
            return None

    # ========================================================
    # STATS
    # ========================================================

    def stats(self):

        with self.lock:

            total = (
                self.correct
                + self.incorrect
            )

            accuracy = (
                self.correct
                / total
                * 100.0
                if total > 0
                else 0.0
            )

            return (
                self.correct,
                self.incorrect,
                self.pushes,
                accuracy,
                self.pending_prediction,
                self.pending_secondary,
                (
                    len(self.pending_history)
                    if self.pending_history
                    else None
                ),
                self.pending_history,
                self.last_result,
            )

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):

        with self.lock:

            self.correct = 0
            self.incorrect = 0
            self.pushes = 0

            self.pending_prediction = None
            self.pending_secondary = None
            self.pending_history = ""

            self.last_result = None
            self.evaluation_number = 0
        
# ============================================================
# SHOE
# ============================================================

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
            "T": 16 * self.decks,
        }


# ============================================================
# VISION
# ============================================================

class Vision:

    def __init__(self, state, tracker):

        self.state = state

        self.tracker = tracker

        self.sct = mss.mss()

        self.initialized = False

        self.previous = {}

        self.cards = {}

        self.last_card_time = {}

        self.history = ""

        self.last_detected_history = "" 
        self.detected_history_stable_count = 0 
        self.HISTORY_STABLE_FRAMES = 3

        self.empty_frames = 0

        self.lock = threading.Lock()

        self.templates = {}

        self.load_templates()

        self.monitor = {
            "top": 0,
            "left": 0,
            "width": 1920,
            "height": 1080,
        }


    def stable_bigroad_history(self, detected_history):
        """
        Require the same detected Big Road history for several
        consecutive frames before accepting it.

        This prevents temporary OCR/color detection failures from
        being treated as real Big Road changes.
        """

        detected_history = clean_history(
            detected_history
        )

        if not detected_history:
            self.last_detected_history = ""
            self.detected_history_stable_count = 0
            return ""

        if (
            detected_history
            == self.last_detected_history
        ):

            self.detected_history_stable_count += 1

        else:

            self.last_detected_history = (
                detected_history
            )

            self.detected_history_stable_count = 1

        if (
            self.detected_history_stable_count
            < self.HISTORY_STABLE_FRAMES
        ):

            return ""

        return detected_history

    # --------------------------------------------------------
    # TEMPLATE LOADING
    # --------------------------------------------------------

    def load_templates(self):

        for rank in (
            "A",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "T",
        ):

            path = f"templates/cards/{rank}.png"

            img = cv2.imread(
                path,
                cv2.IMREAD_GRAYSCALE,
            )

            if img is None:
                if LOG_LEVEL == "DEBUG":
                    print(
                        f"[TEMPLATE] Missing: {path}"
                    )

                continue

            _, img = cv2.threshold(
                img,
                150,
                255,
                cv2.THRESH_BINARY,
            )

            img = cv2.resize(
                img,
                (35, 35),
            )

            self.templates[rank] = [
                img,
                cv2.rotate(
                    img,
                    cv2.ROTATE_90_CLOCKWISE,
                ),
                cv2.rotate(
                    img,
                    cv2.ROTATE_180,
                ),
                cv2.rotate(
                    img,
                    cv2.ROTATE_90_COUNTERCLOCKWISE,
                ),
            ]

        print(
            f"Loaded {len(self.templates)} card templates."
        )


    # --------------------------------------------------------
    # SCREEN CAPTURE
    # --------------------------------------------------------

    def capture(self):

        frame = np.array(
            self.sct.grab(self.monitor)
        )

        return cv2.cvtColor(
            frame,
            cv2.COLOR_BGRA2BGR,
        )


    # --------------------------------------------------------
    # ROI
    # --------------------------------------------------------

    def crop(self, frame, roi):

        x, y, w, h = roi

        height, width = frame.shape[:2]

        x1 = max(0, x)
        y1 = max(0, y)

        x2 = min(width, x + w)
        y2 = min(height, y + h)

        if x1 >= x2 or y1 >= y2:
            return np.empty((0, 0, 3), dtype=np.uint8)

        return frame[
            y1:y2,
            x1:x2,
        ]


    # --------------------------------------------------------
    # CARD DETECTION
    # --------------------------------------------------------

    def has_card(self, roi):

        if roi is None or roi.size == 0:
            return False

        gray = cv2.cvtColor(
            roi,
            cv2.COLOR_BGR2GRAY,
        )

        white = cv2.threshold(
            gray,
            180,
            255,
            cv2.THRESH_BINARY,
        )[1]

        ratio = (
            cv2.countNonZero(white)
            / float(white.size)
        )

        return ratio > 0.25


    def is_new_card(self, name, roi):

        if roi is None or roi.size == 0:
            return False

        gray = cv2.cvtColor(
            roi,
            cv2.COLOR_BGR2GRAY,
        )

        gray = cv2.GaussianBlur(
            gray,
            (5, 5),
            0,
        )

        old = self.previous.get(name)

        self.previous[name] = gray

        if old is None:
            return True

        diff = cv2.absdiff(
            gray,
            old,
        )

        score = float(
            np.mean(diff)
        )

        return score > 25


    # --------------------------------------------------------
    # CARD CORNER
    # --------------------------------------------------------

    def card_corner(self, card):

        if card is None or card.size == 0:
            return None

        height, width = card.shape[:2]

        h = min(16, height)
        w = min(35, width)

        return card[
            0:h,
            0:w,
        ]


    def save_corner(self, corner):

        if corner is None or corner.size == 0:
            return

        os.makedirs(
            "templates/screenshots",
            exist_ok=True,
        )

        filename = (
            "templates/screenshots/"
            f"{int(time.time() * 1000)}.png"
        )

        cv2.imwrite(
            filename,
            corner,
        )


    # --------------------------------------------------------
    # CARD RANK
    # --------------------------------------------------------

    def detect_rank(self, corner):

        if corner is None or corner.size == 0:
            return "?"

        if not self.templates:
            return "?"

        gray = cv2.cvtColor(
            corner,
            cv2.COLOR_BGR2GRAY,
        )

        gray = cv2.GaussianBlur(
            gray,
            (3, 3),
            0,
        )

        gray = cv2.threshold(
            gray,
            150,
            255,
            cv2.THRESH_BINARY,
        )[1]

        gray = cv2.resize(
            gray,
            (35, 35),
        )

        best_rank = "?"
        best_score = -1.0

        for rank, rotations in self.templates.items():

            for template in rotations:

                if (
                    gray.shape[0] < template.shape[0]
                    or gray.shape[1] < template.shape[1]
                ):
                    continue

                result = cv2.matchTemplate(
                    gray,
                    template,
                    cv2.TM_CCOEFF_NORMED,
                )

                score = float(
                    result.max()
                )

                if score > best_score:
                    best_score = score
                    best_rank = rank

        print(
            f"\r[MATCH] {best_rank} "
            f"({best_score:.3f})"
        )

        # Reject extremely poor matches.
        if best_score < 0.35:
            return "?"

        return best_rank


    # --------------------------------------------------------
    # BACCARAT
    # --------------------------------------------------------

    def baccarat_value(self, rank):

        if not rank or rank == "?":
            return 0

        if rank == "A":
            return 1

        if rank in (
            "T",
            "J",
            "Q",
            "K",
        ):
            return 0

        try:
            return int(rank)

        except (ValueError, TypeError):
            return 0


    def is_natural(self, cards):

        player = [
            cards.get("player1"),
            cards.get("player2"),
        ]

        banker = [
            cards.get("banker1"),
            cards.get("banker2"),
        ]

        player_total = sum(
            self.baccarat_value(card)
            for card in player
            if card and card != "?"
        ) % 10

        banker_total = sum(
            self.baccarat_value(card)
            for card in banker
            if card and card != "?"
        ) % 10

        return (
            player_total in (8, 9)
            or banker_total in (8, 9)
        )


    def hand_finished(self):

        required = [
            "player1",
            "player2",
            "banker1",
            "banker2",
        ]

        if not all(
            self.cards.get(x)
            and self.cards.get(x) != "?"
            for x in required
        ):
            return False

        player_cards = [
            self.cards.get("player1"),
            self.cards.get("player2"),
            self.cards.get("player3"),
        ]

        banker_cards = [
            self.cards.get("banker1"),
            self.cards.get("banker2"),
            self.cards.get("banker3"),
        ]

        player_total = sum(
            self.baccarat_value(x)
            for x in player_cards[:2]
        ) % 10

        banker_total = sum(
            self.baccarat_value(x)
            for x in banker_cards[:2]
        ) % 10

        # Natural.
        if player_total >= 8 or banker_total >= 8:
            return True

        # Player draws on 0-5.
        player_draws = player_total <= 5

        # Player stands on 6-7.
        if not player_draws:
            return banker_total >= 0

        # Player must have third card if drawing.
        player3 = player_cards[2]

        if player3 is None or player3 == "?":
            return False

        player3_value = self.baccarat_value(
            player3
        )

        # Banker drawing rules.
        if banker_total <= 2:
            return True

        if banker_total == 3:
            return player3_value != 8

        if banker_total == 4:
            return 2 <= player3_value <= 7

        if banker_total == 5:
            return 4 <= player3_value <= 7

        if banker_total == 6:
            return player3_value in (6, 7)

        # Banker 7 stands.
        return True


    # --------------------------------------------------------
    # NEW HAND
    # --------------------------------------------------------

    def has_any_cards(self, frame):

        for name, roi in ROIS.items():

            if name == "bigroad":
                continue

            card = self.crop(
                frame,
                roi,
            )

            if self.has_card(card):
                return True

        return False


    def new_hand_detected(self, frame):

        empty = 0

        for name, roi in ROIS.items():

            if name == "bigroad":
                continue

            card = self.crop(
                frame,
                roi,
            )

            if not self.has_card(card):
                empty += 1

        if empty >= 6:
            self.empty_frames += 1
        else:
            self.empty_frames = 0

        return self.empty_frames > 15


    def reset_hand(self):

        with self.lock:
            self.cards = {}
            self.previous = {}
            self.last_card_time = {}

        self.empty_frames = 0


    # --------------------------------------------------------
    # DRAW ROIS
    # --------------------------------------------------------

    def draw_rois(self, frame):

        for name, (
            x,
            y,
            w,
            h,
        ) in ROIS.items():

            cv2.rectangle(
                frame,
                (x, y),
                (x + w, y + h),
                (0, 255, 0),
                2,
            )

            cv2.putText(
                frame,
                name,
                (x, max(15, y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
            )


    # --------------------------------------------------------
    # VISION LOOP
    # --------------------------------------------------------

    def run(self):

        print("Vision thread started.")

        # --------------------------------------------------------
        # BIG ROAD SCREENSHOT SETTINGS
        # --------------------------------------------------------

        screenshot_folder = os.path.abspath(
            "templates/screenshots"
        )

        os.makedirs(
            screenshot_folder,
            exist_ok=True,
        )

        bigroad_save_path = os.path.join(
            screenshot_folder,
            "bigroad.png",
        )

        # Save the current Big Road image at most once per second.
        last_bigroad_save = 0.0

        # --------------------------------------------------------
        # VISION LOOP
        # --------------------------------------------------------

        while not self.state.stop_event.is_set():

            # Define both values for the whole iteration. They are replaced
            # with the stable detector values below before any update logic.
            old_history = clean_history(self.history)
            new_history = ""

            try:

                frame = self.capture()

                # ====================================================
                # BIG ROAD
                # ====================================================

                bigroad_roi = self.crop(
                    frame,
                    ROIS["bigroad"],
                )

                # ----------------------------------------------------
                # ALWAYS KEEP bigroad.png UPDATED
                # ----------------------------------------------------
                #
                # This is intentionally independent of history
                # detection. Even if the color detector fails to
                # recognize a new circle, the screenshot itself
                # will still be updated.
                #
                now = time.time()

                if (
                    bigroad_roi is not None
                    and bigroad_roi.size > 0
                    and now - last_bigroad_save >= 1.0
                ):

                    cv2.imwrite(
                        bigroad_save_path,
                        bigroad_roi,
                    )

                    # if save_success:

                    #     print(
                    #         f"\n📸 BIG ROAD IMAGE UPDATED"
                    #         f"\n  Path : {bigroad_save_path}"
                    #         f"\n  Size : {bigroad_roi.shape[1]}x"
                    #         f"{bigroad_roi.shape[0]}"
                    #     )

                    # else:

                    #     print(
                    #         f"\n❌ BIG ROAD IMAGE SAVE FAILED"
                    #         f"\n  Path : {bigroad_save_path}"
                    #     )

                    last_bigroad_save = now

                # ----------------------------------------------------
                # DETECT BIG ROAD HISTORY
                # ----------------------------------------------------

                detected_history, circles = (
                    history_from_image(
                        bigroad_roi
                    )
                )

                detected_history = clean_history(
                    detected_history
                )

                # ----------------------------------------------------
                # REQUIRE MULTIPLE IDENTICAL FRAMES
                # ----------------------------------------------------

                stable_history = self.stable_bigroad_history(
                    detected_history
                )

                # Do not process unstable detector output.
                if not stable_history:

                    time.sleep(0.05)
                    continue

                detected_history = stable_history

                # ====================================================
                # PROCESS BIG ROAD UPDATE
                # ====================================================

                old_history = clean_history(
                    self.history
                )

                new_history = clean_history(
                    detected_history
                )

                # ----------------------------------------------------
                # Ignore empty detection
                # ----------------------------------------------------

                if not new_history:
                    pass

                # ----------------------------------------------------
                # No change
                # ----------------------------------------------------

                elif new_history == old_history:
                    pass

                # ----------------------------------------------------
                # Detector temporarily LOST circles
                # ----------------------------------------------------

                elif len(new_history) < len(old_history):

                    print(
                        "\n[TRACKER] ⚠️ Big Road detector temporarily "
                        "lost one or more circles."
                    )

                    print(
                        f"  Keeping : {old_history}"
                    )

                    print(
                        f"  Detected: {new_history}"
                    )

                # ----------------------------------------------------
                # Same length but changed
                # ----------------------------------------------------

                elif len(new_history) == len(old_history):

                    print(
                        "\n[TRACKER] ⚠️ Big Road detector changed "
                        "an existing result."
                    )

                    print(
                        f"  Keeping : {old_history}"
                    )

                    print(
                        f"  Detected: {new_history}"
                    )

                # ----------------------------------------------------
                # VALID APPEND
                # ----------------------------------------------------

                elif (
                    len(new_history) == len(old_history) + 1
                    and new_history.startswith(old_history)
                ):

                    new_results = new_history[
                        len(old_history):
                    ]

                    if new_results:

                        print(
                            f"\n📸 BIG ROAD APPEND"
                            f"\n  Old   : {old_history}"
                            f"\n  New   : {new_history}"
                            f"\n  Added : {new_results}"
                        )

                        # --------------------------------------------
                        # Add ONLY new results to GameState
                        # --------------------------------------------

                        for result in new_results:

                            if result in VALID:

                                self.state.add_result(
                                    result
                                )

                        # --------------------------------------------
                        # Evaluate pending prediction
                        # --------------------------------------------

                        evaluation = (
                            self.tracker.evaluate_bigroad(
                                new_history
                            )
                        )

                        if evaluation:

                            print()
                            print("=" * 30)
                            print(" 🔥 REAL-TIME ROUND RESULT")
                            print("=" * 30)

                            print(
                                f"Prediction : "
                                f"{evaluation['prediction']}"
                            )

                            print(
                                f"Actual     : "
                                f"{evaluation['actual']}"
                            )

                            print(
                                f"Status     : "
                                f"{evaluation['status'].upper()}"
                            )

                            print(
                                f"Round #    : "
                                f"{evaluation['number']}"
                            )

                            print("=" * 30)

                            print_prediction_stats(
                                self.tracker
                            )

                        # --------------------------------------------
                        # Train ONLY the new transition
                        # --------------------------------------------

                        train_latest_transition(
                            old_history,
                            new_history,
                        )

                        # --------------------------------------------
                        # IMPORTANT:
                        # Update history only after successful append
                        # --------------------------------------------

                        self.history = new_history

                        # --------------------------------------------
                        # Create prediction for NEXT round
                        # --------------------------------------------

                        prediction, combined_score = (
                            calculate_prediction(
                                new_history
                            )
                        )

                        if prediction:

                            if prediction == "T":

                                secondary_prediction = max(
                                    MAIN_RESULTS,
                                    key=lambda x:
                                        combined_score.get(
                                            x,
                                            0,
                                        ),
                                )

                            elif prediction == "P":

                                secondary_prediction = "B"

                            else:

                                secondary_prediction = "P"

                            created = (
                                self.tracker.set_prediction(
                                    prediction,
                                    secondary_prediction,
                                    new_history,
                                )
                            )

                            if created:

                                print(
                                    "\n🎯 NEW PREDICTION"
                                    f"\n  History   : {new_history}"
                                    f"\n  Primary   : {prediction}"
                                    f"\n  Secondary : {secondary_prediction}"
                                )

                # ----------------------------------------------------
                # NON-APPEND HISTORY
                # ----------------------------------------------------

                else:

                    print(
                        "\n[TRACKER] ⚠️ Big Road detector produced "
                        "a non-append history."
                    )

                    print(
                        f"  Old length: {len(old_history)}"
                    )

                    print(
                        f"  New length: {len(new_history)}"
                    )

                    print(
                        f"  Old       : {old_history}"
                    )

                    print(
                        f"  New       : {new_history}"
                    )

                    print(
                        "  Action    : IGNORING detector update."
                    )

                # ====================================================
                # INITIAL BIG ROAD IMPORT
                # ====================================================

                if not self.initialized:

                    self.history = detected_history

                    if detected_history:

                        self.state.set_results(
                            detected_history
                        )

                        train_history(
                            detected_history
                        )

                        mark_history_trained(
                            detected_history
                        )

                        # ============================================
                        # CREATE INITIAL PREDICTION
                        # ============================================

                        prediction, combined_score = (
                            calculate_prediction(
                                detected_history
                            )
                        )

                        if prediction:

                            # ------------------------------------------------
                            # PRIMARY = T
                            #
                            # Need a P/B backup.
                            # IMPORTANT: only P/B are allowed here.
                            # ------------------------------------------------

                            if prediction == "T":

                                secondary_prediction = max(
                                    MAIN_RESULTS,
                                    key=lambda x: (
                                        combined_score.get(
                                            x,
                                            0,
                                        )
                                    ),
                                )

                            # ------------------------------------------------
                            # PRIMARY = P
                            #
                            # Secondary is B.
                            # ------------------------------------------------

                            elif prediction == "P":

                                secondary_prediction = "B"

                            # ------------------------------------------------
                            # PRIMARY = B
                            #
                            # Secondary is P.
                            # ------------------------------------------------

                            else:

                                secondary_prediction = "P"

                            created = (
                                self.tracker.set_prediction(
                                    prediction,
                                    secondary_prediction,
                                    detected_history,
                                )
                            )

                            if created:

                                print(
                                    f"\n🎯 INITIAL PREDICTION"
                                    f"\n  Primary    : {prediction}"
                                    f"\n  Secondary  : {secondary_prediction}"
                                    f"\n  History    : {detected_history}"
                                )

                    self.initialized = True

                    print(
                        f"\nInitial history: "
                        f"{detected_history}"
                    )

                # ====================================================
                # CARD DETECTION
                # ====================================================

                for name, roi in ROIS.items():

                    if name == "bigroad":
                        continue

                    card = self.crop(
                        frame,
                        roi,
                    )

                    if not self.has_card(card):
                        continue

                    if not self.is_new_card(
                        name,
                        card,
                    ):
                        continue

                    now = time.time()

                    last = (
                        self.last_card_time.get(
                            name,
                            0,
                        )
                    )

                    if now - last < 1.0:
                        continue

                    self.last_card_time[name] = now

                    corner = self.card_corner(
                        card
                    )

                    if LOG_LEVEL == "DEBUG":

                        self.save_corner(
                            corner
                        )

                    rank = self.detect_rank(
                        corner
                    )

                    with self.lock:

                        self.cards[name] = rank

                    # ====================================================
                    # CHECK BIG ROAD FOR NEW RESULT
                    # ====================================================

                    # Big Road updates are handled once per stable frame above.
                    # Do not process them again when an individual card ROI
                    # changes: doing so lets the card path bypass the single-
                    # append guard and can duplicate training/state updates.
                    if False and detected_history != self.history:

                        old_history = clean_history(self.history)
                        new_history = clean_history(detected_history)

                        # --------------------------------------------------------
                        # IGNORE EMPTY DETECTION
                        # --------------------------------------------------------

                        if not new_history:
                            continue

                        # --------------------------------------------------------
                        # NO CHANGE
                        # --------------------------------------------------------

                        if new_history == old_history:
                            continue

                        # ========================================================
                        # IMPORTANT:
                        #
                        # Big Road image detection can temporarily LOSE circles.
                        #
                        # Example:
                        #
                        #   old = BPPBBBPBPBBPBBPPBBP
                        #   new = BPPBBBPBPBBPBBPPBB
                        #
                        # The detector simply failed to see the final P.
                        #
                        # NEVER treat a shorter history as a new result.
                        # NEVER update self.history to the shorter version.
                        # ========================================================

                        if len(new_history) < len(old_history):

                            print(
                                "\n[TRACKER] ⚠️ Big Road detector temporarily "
                                "lost one or more circles."
                            )

                            print(
                                f"  Keeping : {old_history}"
                            )

                            print(
                                f"  Detected: {new_history}"
                            )

                            continue

                        # --------------------------------------------------------
                        # SAME LENGTH BUT DIFFERENT
                        #
                        # This is detector noise / a color classification change.
                        # Do NOT let it corrupt prediction history.
                        # --------------------------------------------------------

                        if len(new_history) == len(old_history):

                            print(
                                "\n[TRACKER] ⚠️ Big Road detector changed "
                                "an existing result."
                            )

                            print(
                                f"  Keeping : {old_history}"
                            )

                            print(
                                f"  Detected: {new_history}"
                            )

                            continue

                        # ========================================================
                        # ONLY ACCEPT A NEW RESULT WHEN THE ENTIRE OLD HISTORY
                        # IS A PREFIX OF THE NEW HISTORY.
                        #
                        # This is the ONLY safe way to identify an appended result.
                        # ========================================================

                        if (
                            len(new_history) == len(old_history) + 1
                            and new_history.startswith(old_history)
                        ):

                            new_results = new_history[
                                len(old_history):
                            ]

                            # ----------------------------------------------------
                            # Sanity check
                            # ----------------------------------------------------

                            if not new_results:

                                continue

                            print(
                                f"\n📸 BIG ROAD APPEND"
                                f"\n  Old   : {old_history}"
                                f"\n  New   : {new_history}"
                                f"\n  Added : {new_results}"
                            )

                        else:

                            # ====================================================
                            # HISTORY IS LONGER BUT OLD HISTORY IS NOT A PREFIX.
                            #
                            # DO NOT pretend this is an appended result.
                            #
                            # This can happen when the vision detector reorders
                            # circles, misses a circle in the middle, or changes
                            # a color classification.
                            # ====================================================

                            print(
                                "\n[TRACKER] ⚠️ Big Road detector produced "
                                "a non-append history."
                            )

                            print(
                                f"  Old length: {len(old_history)}"
                            )

                            print(
                                f"  New length: {len(new_history)}"
                            )

                            print(
                                f"  Old       : {old_history}"
                            )

                            print(
                                f"  New       : {new_history}"
                            )

                            print(
                                "  Action    : IGNORING detector update."
                            )

                            # IMPORTANT:
                            #
                            # Do NOT change self.history.
                            #
                            # Do NOT train Redis.
                            #
                            # Do NOT evaluate the pending prediction.
                            #
                            # Do NOT create a new prediction.
                            #
                            # Wait for the detector to produce a clean append.
                            continue

                        # ========================================================
                        # FROM THIS POINT ON:
                        #
                        # new_history is guaranteed to be:
                        #
                        #     old_history + one or more new results
                        #
                        # ========================================================

                        # --------------------------------------------------------
                        # SAVE UPDATED BIG ROAD IMAGE
                        # --------------------------------------------------------

                        os.makedirs(
                            "templates/screenshots",
                            exist_ok=True,
                        )

                        saved = cv2.imwrite(
                            "templates/screenshots/bigroad.png",
                            bigroad_roi,
                        )

                        if saved:

                            print(
                                "\n📸 BIG ROAD IMAGE UPDATED"
                                f"\n  History: {new_history}"
                            )

                        else:

                            print(
                                "\n[TRACKER] ⚠️ Failed to save "
                                "bigroad.png"
                            )

                        # ========================================================
                        # ADD ONLY THE ACTUAL APPENDED RESULTS
                        # ========================================================

                        for result in new_results:

                            if result in VALID:

                                self.state.add_result(result)

                        # ========================================================
                        # EVALUATE PREVIOUS PREDICTION
                        # ========================================================

                        evaluation = (
                            self.tracker.evaluate_bigroad(
                                new_history
                            )
                        )

                        if evaluation:

                            print()
                            print("=" * 20)
                            print(" 🔥 REAL-TIME ROUND RESULT")
                            print("=" * 20)

                            print(
                                f"Prediction : "
                                f"{evaluation['prediction']}"
                            )

                            print(
                                f"Actual     : "
                                f"{evaluation['actual']}"
                            )

                            print(
                                f"Status     : "
                                f"{evaluation['status'].upper()}"
                            )

                            print(
                                f"Round #    : "
                                f"{evaluation['number']}"
                            )

                            print("=" * 20)

                            try:

                                print_prediction_stats(
                                    self.tracker
                                )

                            except ValueError as exc:

                                print(
                                    "\n[TRACKER] ⚠️ "
                                    "print_prediction_stats() "
                                    f"failed: {exc}"
                                )

                        # ========================================================
                        # TRAIN ONLY THE REAL APPENDED TRANSITION
                        # ========================================================

                        train_latest_transition(
                            old_history,
                            new_history,
                        )

                        # ========================================================
                        # NOW AND ONLY NOW UPDATE CURRENT HISTORY
                        # ========================================================

                        self.history = new_history

                        # ========================================================
                        # CREATE PREDICTION FOR THE NEW ROUND
                        # ========================================================

                        prediction, combined_score = (
                            calculate_prediction(
                                new_history
                            )
                        )

                        if prediction:

                            # ----------------------------------------------------
                            # Primary = T
                            # Pick strongest P/B backup.
                            # ----------------------------------------------------

                            if prediction == "T":

                                secondary_prediction = max(
                                    MAIN_RESULTS,
                                    key=lambda x:
                                        combined_score.get(
                                            x,
                                            0,
                                        ),
                                )

                            # ----------------------------------------------------
                            # Primary = P
                            # ----------------------------------------------------

                            elif prediction == "P":

                                secondary_prediction = "B"

                            # ----------------------------------------------------
                            # Primary = B
                            # ----------------------------------------------------

                            else:

                                secondary_prediction = "P"

                            created = (
                                self.tracker.set_prediction(
                                    prediction,
                                    secondary_prediction,
                                    new_history,
                                )
                            )

                            if created:

                                print(
                                    "\n🎯 NEW PREDICTION"
                                    f"\n  History   : {new_history}"
                                    f"\n  Primary   : {prediction}"
                                    f"\n  Secondary : {secondary_prediction}"
                                )

                # ====================================================
                # RESET CURRENT HAND
                # ====================================================

                if self.new_hand_detected(
                    frame
                ):

                    self.reset_hand()

                # ====================================================
                # DEBUG SCREEN
                # ====================================================

                if LOG_LEVEL == "DEBUG":

                    x, y = pyautogui.position()

                    print(
                        f"\rMouse: {x},{y}",
                        end="",
                        flush=True,
                    )

                    cv2.putText(
                        frame,
                        f"{x},{y}",
                        (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 255, 0),
                        2,
                    )

                    self.draw_rois(
                        frame
                    )

                    cv2.imshow(
                        "Vision",
                        frame,
                    )

                    if (
                        cv2.waitKey(1)
                        & 0xFF
                    ) == ord("q"):

                        self.state.stop()

                        break

                # ====================================================
                # LOOP DELAY
                # ====================================================

                time.sleep(
                    0.05
                )

            # ========================================================
            # ERROR HANDLING
            # ========================================================

            except Exception as exc:

                print(
                    f"\n[VISION ERROR] "
                    f"{type(exc).__name__}: {exc}"
                )

                if LOG_LEVEL == "DEBUG":

                    import traceback

                    traceback.print_exc()

                time.sleep(
                    0.5
                )

        # ============================================================
        # CLEANUP
        # ============================================================

        cv2.destroyAllWindows()

        print(
            "\nVision thread stopped."
        )


# ============================================================
# BIG ROAD ENGINE
# ============================================================

class BigRoad:

    def __init__(
        self,
        rows=ROWS,
        cols=COLS,
    ):

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

        if not result in MAIN_RESULTS:
            return

        cell = Cell(
            result,
            self.row,
            self.col,
        )

        self.grid[
            self.row
        ][
            self.col
        ] = cell

        self.cells.append(cell)

        self.max_col = max(
            self.max_col,
            self.col,
        )


    def add(self, result):

        if result in SIDE_RESULTS or result == "T":

            if self.current is not None:

                cell = self.grid[
                    self.row
                ][
                    self.col
                ]

                if cell:

                    if result == "T":
                        cell.tie += 1

                    elif result == "S":
                        cell.small = True

                    elif result == "X":
                        cell.big = True

            return


        if result not in MAIN_RESULTS:
            return


        # First result.
        if self.current is None:

            self.current = result

            self.row = 0
            self.col = 0
            self.base_col = 0

            self.place(result)

            return


        # Same side.
        if result == self.current:

            self.extend(result)

            return


        # Change side.
        self.current = result

        self.base_col += 1

        self.col = self.base_col

        self.row = 0

        # Find free column.
        while (
            self.col < self.cols
            and self.grid[0][self.col]
            is not None
        ):
            self.col += 1

        if self.col >= self.cols:

            self.shift_left()

            self.col = min(
                max(self.base_col, 0),
                self.cols - 1,
            )

            while (
                self.col < self.cols
                and self.grid[0][self.col]
                is not None
            ):
                self.col += 1

            if self.col >= self.cols:
                raise RuntimeError(
                    "Big Road full"
                )

        self.place(result)


    def extend(self, result):

        # Normal downward placement.
        if (
            self.row + 1 < self.rows
            and self.grid[
                self.row + 1
            ][
                self.col
            ] is None
        ):

            self.row += 1

            self.place(result)

            return


        # Bottom reached.
        # Move horizontally.
        c = self.col + 1

        while c < self.cols:

            if (
                self.grid[
                    self.rows - 1
                ][c] is None
            ):

                self.col = c
                self.row = self.rows - 1

                self.place(result)

                return

            c += 1


        # Need to scroll.
        self.shift_left()

        self.col = max(
            0,
            self.col - 1,
        )

        self.base_col = max(
            0,
            self.base_col - 1,
        )

        self.place(result)


    def shift_left(self):

        for row in range(self.rows):

            self.grid[row].pop(0)

            self.grid[row].append(None)


        # Update cell coordinates.
        valid_cells = []

        for cell in self.cells:

            cell.col -= 1

            if cell.col >= 0:
                valid_cells.append(cell)

        self.cells = valid_cells

        self.col -= 1

        self.base_col -= 1

        self.max_col -= 1

        self.col = max(
            self.col,
            0,
        )

        self.base_col = max(
            self.base_col,
            0,
        )

        self.max_col = max(
            self.max_col,
            0,
        )


    def validate(self):

        for cell in self.cells:

            if not (
                0 <= cell.row < self.rows
                and 0 <= cell.col < self.cols
            ):
                continue

            assert (
                self.grid[
                    cell.row
                ][
                    cell.col
                ] is cell
            )


    def debug(self):

        print(
            "\nMove Winner Row Col Tie"
        )

        print(
            "-" * 30
        )

        for i, cell in enumerate(
            self.cells,
            1,
        ):

            print(
                f"{i:4} "
                f"{cell.winner:^6} "
                f"{cell.row:3} "
                f"{cell.col:3} "
                f"{cell.tie:3}"
            )


# ============================================================
# DRAW BIG ROAD CELL
# ============================================================

def render_cell(cell):

    if cell is None:
        return " "

    circled = {
        1: "⬤",
        2: "②",
        3: "③",
        4: "④",
        5: "⑤",
        "S": "Ⓢ",
        "X": "Ⓑ",
    }

    # Ties.
    if cell.tie:

        if 1 <= cell.tie <= 5:
            symbol = circled[
                cell.tie
            ]
        else:
            symbol = str(
                cell.tie
            )

        return (
            f"{colors['BLGRE']}"
            f"{symbol}"
            f"{colors['RES']}"
        )


    # Small/Big Tiger.
    if cell.small or cell.big:

        symbol = (
            circled["X"]
            if cell.big
            else circled["S"]
        )

        return (
            f"{colors['LRED'] if cell.winner == 'B' else colors['LBLU']}"
            f"{symbol}"
            f"{colors['RES']}"
        )


    # Normal result.
    color = (
        colors["LRED"]
        if cell.winner == "B"
        else colors["LBLU"]
    )

    return (
        f"{color}"
        f"{circled[1]}"
        f"{colors['RES']}"
    )


# ============================================================
# DRAW DETECTED BIG ROAD
# ============================================================

def draw_detected_board(circles):

    print()
    print("=" * 65)
    print(" DETECTED BIG ROAD")
    print("=" * 65)

    grid = [
        [None for _ in range(COLS)]
        for _ in range(ROWS)
    ]

    if circles:

        # Group approximate X positions.
        xs = sorted(
            set(
                c["x"]
                for c in circles
            )
        )

        ys = sorted(
            set(
                c["y"]
                for c in circles
            )
        )

        xmap = {
            x: i
            for i, x in enumerate(xs)
        }

        ymap = {
            y: i
            for i, y in enumerate(ys)
        }

        for circle in circles:

            row = ymap[
                circle["y"]
            ]

            col = xmap[
                circle["x"]
            ]

            if (
                row < ROWS
                and col < COLS
            ):

                grid[row][col] = (
                    circle["symbol"]
                )


    max_col = 0

    if circles:
        max_col = min(
            len(xs) - 1,
            COLS - 1,
        )

    start_col = max(
        0,
        max_col - VISIBLE_COLS + 1,
    )

    end_col = min(
        COLS,
        max_col + 1,
    )

    if start_col > 0:

        print(
            f"{colors['YEL']}"
            f"... showing last "
            f"{VISIBLE_COLS} columns"
            f"{colors['RES']}"
        )


    # Column numbers.
    print(
        "\n    ",
        end="",
    )

    for col in range(
        start_col,
        end_col,
    ):

        print(
            f"{colors['CYN']}"
            f"{col + 1:^{CELL_WIDTH}}",
            end="",
        )

    print()


    symbol_map = {
        "P": (
            f"{colors['LBLU']}⬤"
            f"{colors['RES']}"
        ),

        "B": (
            f"{colors['LRED']}⬤"
            f"{colors['RES']}"
        ),

        "T": (
            f"{colors['BLGRE']}⬤"
            f"{colors['RES']}"
        ),
    }


    # Rows.
    for row in range(ROWS):

        line = (
            f"{colors['CYN']}"
            f"{row + 1} "
            f"{colors['YEL']}| "
            f"{colors['RES']}"
        )

        for col in range(
            start_col,
            end_col,
        ):

            symbol = grid[
                row
            ][
                col
            ]

            cell = symbol_map.get(
                symbol,
                " ",
            )

            line += pad(
                cell,
                CELL_WIDTH,
            )

        print(line)


# ============================================================
# DRAW GENERATED BIG ROAD
# ============================================================

def draw_bigroad(results):

    road = BigRoad(
        ROWS,
        COLS,
    )

    for char in results:
        road.add(char)

    road.validate()

    grid = road.grid

    print()
    print("=" * 65)
    print(" BIG ROAD")
    print("=" * 65)

    if LOG_LEVEL == "DEBUG":
        road.debug()

    start_col = max(
        0,
        road.max_col
        - VISIBLE_COLS
        + 1,
    )

    end_col = min(
        COLS,
        road.max_col + 1,
    )

    if start_col > 0:

        print(
            f"{colors['YEL']}"
            f"... showing last "
            f"{VISIBLE_COLS} columns"
            f"{colors['RES']}"
        )


    print(
        "\n    ",
        end="",
    )

    for col in range(
        start_col,
        end_col,
    ):

        print(
            f"{colors['CYN']}"
            f"{col + 1:^{CELL_WIDTH}}",
            end="",
        )

    print()


    for row in range(ROWS):

        line = (
            f"{colors['CYN']}"
            f"{row + 1} "
            f"{colors['YEL']}| "
            f"{colors['RES']}"
        )

        for col in range(
            start_col,
            end_col,
        ):

            cell = render_cell(
                grid[row][col]
            )

            line += pad(
                cell,
                CELL_WIDTH,
            )

        print(line)


# ============================================================
# HISTORY CLEANING
# ============================================================

def clean_history(history):

    if not history:
        return ""

    history = str(
        history
    ).upper()

    return "".join(
        char
        for char in history
        if char in VALID
    )


def history_fingerprint(history):

    history = clean_history(
        history
    )

    return hashlib.md5(
        history.encode()
    ).hexdigest()


def mark_history_trained(history):

    if r is None:
        return

    fingerprint = (
        history_fingerprint(
            history
        )
    )

    r.set(
        f"trained:{fingerprint}",
        1,
    )


# ============================================================
# LOAD HISTORICAL BIG ROAD DATA
# ============================================================

def load_bigroad_data(folder):

    histories = []

    files = sorted(
        glob.glob(
            os.path.join(
                folder,
                "*.png",
            )
        )
        +
        glob.glob(
            os.path.join(
                folder,
                "*.txt",
            )
        )
    )

    print(
        f"Loading {len(files)} "
        f"Big Road files..."
    )

    for file in files:

        try:

            if file.lower().endswith(
                ".png"
            ):

                history, _ = (
                    history_from_image(
                        file
                    )
                )

            else:

                with open(
                    file,
                    "r",
                    encoding="utf-8",
                ) as f:

                    history = f.read()


            history = clean_history(
                history
            )

            if not history:
                continue

            histories.append(
                history
            )

            print(
                f"{os.path.basename(file):30} "
                f"{len(history):4} hands"
            )

        except Exception as exc:

            print(
                f"[LOAD ERROR] "
                f"{os.path.basename(file)}: "
                f"{exc}"
            )


    print(
        f"\nLoaded "
        f"{len(histories)} "
        f"histories.\n"
    )

    return histories


# ============================================================
# REDIS TRAINING
# ============================================================

def train_history(
    history,
    max_order=10,
):

    history = clean_history(
        history
    )

    if r is None:
        raise RuntimeError(
            "Redis is not initialized."
        )

    if len(history) < 2:
        return


    for order in range(
        1,
        max_order + 1,
    ):

        if len(history) <= order:
            break

        for i in range(
            len(history) - order
        ):

            pattern = history[
                i:i + order
            ]

            nxt = history[
                i + order
            ]

            if nxt not in VALID:
                continue

            r.hincrby(
                f"pattern:{pattern}",
                nxt,
                1,
            )


def train_latest_transition(
    old_history,
    new_history,
    max_order=10,
):

    old_history = clean_history(
        old_history
    )

    new_history = clean_history(
        new_history
    )

    if len(new_history) <= len(
        old_history
    ):
        return

    if not new_history.startswith(
        old_history
    ):
        return

    nxt = new_history[-1]

    for order in range(
        1,
        max_order + 1,
    ):

        if len(new_history) <= order:
            break

        pattern = new_history[
            -order - 1:-1
        ]

        if len(pattern) != order:
            continue

        r.hincrby(
            f"pattern:{pattern}",
            nxt,
            1,
        )


# ============================================================
# REDIS PATTERN PREDICTION
# ============================================================

def redis_pattern_prediction(
    history,
    max_order=10,
):

    history = clean_history(
        history
    )

    score = Counter()

    if not history or r is None:
        return score

    max_order = min(
        max_order,
        len(history),
    )


    for order in range(
        max_order,
        0,
        -1,
    ):

        pattern = history[
            -order:
        ]

        values = r.hgetall(
            f"pattern:{pattern}"
        )

        if not values:
            continue


        for key, value in values.items():

            if key in VALID:

                try:
                    score[key] += int(
                        value
                    )
                except (
                    ValueError,
                    TypeError,
                ):
                    pass


        # Longest available pattern only.
        if score:
            break


    return score


# ============================================================
# NEAREST HISTORICAL PREDICTION
# ============================================================

def nearest_pattern_prediction(
    current_history,
    max_order=20,
):

    current_history = clean_history(
        current_history
    )

    score = Counter()

    if not current_history:
        return score


    longest = min(
        max_order,
        len(current_history),
    )


    for order in range(
        longest,
        0,
        -1,
    ):

        pattern = current_history[
            -order:
        ]

        matches = 0


        for history in TRAINING_HISTORIES:

            start = 0

            while True:

                pos = history.find(
                    pattern,
                    start,
                )

                if pos == -1:
                    break


                next_pos = (
                    pos + order
                )

                if next_pos < len(
                    history
                ):

                    nxt = history[
                        next_pos
                    ]

                    if nxt in VALID:

                        score[nxt] += 1

                        matches += 1


                start = pos + 1


        if matches > 0:
            break


    return score


# ============================================================
# MARKOV
# ============================================================

def markov_prediction(
    history,
    order=3,
):

    history = clean_history(
        history
    )

    if len(history) <= order:
        return Counter()

    model = {}


    for i in range(
        len(history) - order
    ):

        state = history[
            i:i + order
        ]

        nxt = history[
            i + order
        ]

        if state not in model:
            model[state] = Counter()

        model[state][nxt] += 1


    return model.get(
        history[-order:],
        Counter(),
    )


# ============================================================
# FREQUENCY
# ============================================================

def frequency_prediction(history):

    history = clean_history(
        history
    )

    recent = [
        x
        for x in history[-100:]
        if x in MAIN_RESULTS
    ]

    return Counter(recent)


# ============================================================
# TIE PREDICTION
# ============================================================

def tie_prediction(history):

    history = clean_history(
        history
    )

    score = Counter()

    if len(history) < 20:
        return score

    ties = history.count("T")

    rate = (
        ties
        / len(history)
    )


    if rate < 0.05:
        score["T"] += 5

    elif rate < 0.10:
        score["T"] += 15

    else:
        score["T"] += 25


    last_tie = history.rfind(
        "T"
    )

    if last_tie != -1:

        gap = (
            len(history)
            - last_tie
            - 1
        )

        if gap >= 15:
            score["T"] += 10

        elif gap >= 8:
            score["T"] += 5


    return score


# ============================================================
# COMBINE PREDICTIONS
# ============================================================

def combine(
    pattern,
    markov,
    frequency,
    trend=None,
):

    score = Counter()

    engines = [
        (pattern, 40),
        (markov, 30),
        (trend or Counter(), 20),
        (frequency, 10),
    ]


    for engine, weight in engines:

        total = sum(
            max(v, 0)
            for v in engine.values()
        )

        if total <= 0:
            continue


        for key, value in engine.items():

            if value > 0:

                score[key] += (
                    value
                    / total
                ) * weight


    # Tie baseline.
    score["T"] += 8


    if frequency.get("T", 0) >= 5:
        score["T"] += 15

    elif frequency.get("T", 0) >= 3:
        score["T"] += 8


    return score

def calculate_prediction(history):

    history = clean_history(history)

    if not history:
        return None, Counter()

    redis_score = redis_pattern_prediction(
        history
    )

    nearest_score = nearest_pattern_prediction(
        history
    )

    markov_score = markov_prediction(
        history,
        order=3,
    )

    frequency_score = frequency_prediction(
        history
    )

    tie_score = tie_prediction(
        history
    )

    combined_score = combine(
        redis_score,
        markov_score,
        frequency_score,
        # nearest_score,
    )

    combined_score.update(
        tie_score
    )

    prediction = max(
        MAIN_RESULTS,
        key=lambda x: combined_score.get(x, 0)
    )

    return prediction, combined_score


# ============================================================
# PREDICTION DISPLAY
# ============================================================

def print_prediction(
    history,
    score,
    data_src,
):

    history = clean_history(
        history
    )

    counts = Counter(
        history
    )


    display_score = Counter()

    for key in MAIN_RESULTS:

        display_score[key] = max(
            score.get(key, 0),
            0,
        )


    total = sum(
        display_score.values()
    )

    if total <= 0:
        total = 1


    if data_src == "historical":

        title = (
            f"{colors['LYEL']}"
            f"{data_src.upper()}"
        )

    else:

        title = (
            f"{colors['LMAG']}"
            f"{data_src.upper()}"
        )


    print(
        f"\n{title} "
        f"{colors['ORA']}PREDICTIONS"
        f"{colors['CYN']}"
    )

    print(
        "-" * 20
    )


    names = {

        "P": (
            f"{colors['BLU']}"
            f"PLAYER"
            f"{colors['RES']}"
        ),

        "B": (
            f"{colors['RED']}"
            f"BANKER"
            f"{colors['RES']}"
        ),

        "T": (
            f"{colors['GRE']}"
            f"Tie"
            f"{colors['RES']}"
        ),
    }


    blocks = {
        "P": "🟦",
        "B": "🟥",
        "T": "🟩",
    }


    ranking = []


    for key in (
        "P",
        "B",
        "T",
    ):

        percentage = (
            display_score[key]
            / total
            * 100
        )

        ranking.append(
            (
                percentage,
                key,
            )
        )


        bar_length = 7

        filled = round(
            percentage
            / 100
            * bar_length
        )

        empty = (
            bar_length
            - filled
        )


        bar = (
            blocks[key] * filled
            + "⬛" * empty
        )


        print(
            f"{names[key]:20}"
            f"{colors['CYN']}"
            f"{percentage:6.2f} "
            f"{colors['WHTE']}%  "
            f"{bar}  "
            f"{colors['LYEL']}"
            f"{counts[key]}"
            f"{colors['WHTE']}"
        )


    player_pct = (
        display_score["P"]
        / total
        * 100
    )

    banker_pct = (
        display_score["B"]
        / total
        * 100
    )

    confidence = abs(
        player_pct - banker_pct
    )

    if len(ranking) >= 2:

        confidence = (
            ranking[0][0]
            - ranking[1][0]
        )


    print(
        f"\nTotal Hands : "
        f"{colors['LYEL']}"
        f"{len(history)}"
        f"{colors['WHTE']}"
    )

    print(
        f"Confidence : "
        f"{colors['ORA']}"
        f"{confidence:.2f} "
        f"{colors['WHTE']}%"
    )


def print_prediction_stats(tracker):

    (
        correct,
        incorrect,
        pushes,
        accuracy,
        pending,
        pending_secondary,
        pending_history_length,
        pending_history,
        last_result,
    ) = tracker.stats()

    total = correct + incorrect

    print()
    print("=" * 20)
    print(" REAL-TIME PREDICTION TRACKER")
    print("=" * 20)

    print(
        f"Correct   : {correct}"
    )

    print(
        f"Incorrect : {incorrect}"
    )

    print(
        f"Pushes    : {pushes}"
    )

    print(
        f"Settled   : {total}"
    )

    print(
        f"Accuracy  : {accuracy:.2f}%"
    )

    # --------------------------------------------------------
    # LAST RESULT
    # --------------------------------------------------------

    if last_result:

        status = last_result["status"]

        prediction = last_result["prediction"]
        actual = last_result["actual"]

        if status == "correct":

            icon = "✅"

        elif status == "incorrect":

            icon = "❌"

        else:

            icon = "⏸"

        print()
        print(
            f"LAST RESULT : "
            f"{icon}"
        )

        print(
            f"Prediction  : {prediction}"
        )

        print(
            f"Actual      : {actual}"
        )

    else:

        print()
        print(
            "LAST RESULT : None"
        )

    # --------------------------------------------------------
    # CURRENT PENDING PREDICTION
    # --------------------------------------------------------

    print()

    if pending:

        print(
            f"PENDING     : 🎯 {pending}"
        )

        print(
            f"SECONDARY   : {pending_secondary}"
        )

        print(
            f"Based on    : {pending_history}"
        )

        print(
            f"Waiting for : "
            f"result #{pending_history_length + 1}"
        )

    else:

        print(
            "PENDING     : None"
        )

    print("=" * 20)

# ============================================================
# INITIAL HISTORICAL TRAINING
# ============================================================

def train_historical_data():

    if r is None:
        raise RuntimeError(
            "Redis is not initialized."
        )


    print(
        "Training historical datasets..."
    )

    trained = 0


    for history in TRAINING_HISTORIES:

        history = clean_history(
            history
        )

        if not history:
            continue


        fingerprint = (
            history_fingerprint(
                history
            )
        )

        key = (
            f"trained:{fingerprint}"
        )


        if r.exists(key):
            continue


        train_history(
            history
        )

        r.set(
            key,
            1,
        )

        trained += 1


    print(
        f"Historical datasets "
        f"trained: {trained}"
    )


# ============================================================
# REDIS
# ============================================================

def connect_redis():

    global r

    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    try:

        r.ping()

        print(
            "✅ Connected to Redis"
        )

    except redis.exceptions.RedisError as exc:

        print(
            f"❌ Redis connection failed: "
            f"{exc}"
        )

        raise SystemExit(1)


# ============================================================
# CLEAN SCREENSHOTS
# ============================================================

def clean_screenshot_directory(
    folder
):

    os.makedirs(
        folder,
        exist_ok=True,
    )

    try:

        for filename in os.listdir(
            folder
        ):

            file_path = os.path.join(
                folder,
                filename,
            )

            if os.path.isfile(
                file_path
            ):

                os.remove(
                    file_path
                )

    except PermissionError:

        print(
            f"Permission denied: "
            f"{folder}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    global TRAINING_HISTORIES


    # --------------------------------------------------------
    # REDIS
    # --------------------------------------------------------

    connect_redis()


    # --------------------------------------------------------
    # CLEAN SCREENSHOT DIRECTORY
    # --------------------------------------------------------

    screenshot_folder = (
        "templates/screenshots"
    )

    clean_screenshot_directory(
        screenshot_folder
    )


    # --------------------------------------------------------
    # LOAD HISTORICAL DATA
    # --------------------------------------------------------

    TRAINING_HISTORIES = (
        load_bigroad_data(
            "templates/bigroad"
        )
    )


    # --------------------------------------------------------
    # TRAIN HISTORICAL DATA
    # --------------------------------------------------------

    train_historical_data()


    # --------------------------------------------------------
    # START VISION
    # --------------------------------------------------------

    state = GameState()
    tracker = PredictionTracker()

    vision = Vision(
        state,
        tracker
    )


    vision_thread = threading.Thread(
        target=vision.run,
        daemon=True,
        name="VisionThread",
    )

    vision_thread.start()


    # --------------------------------------------------------
    # MAIN DISPLAY LOOP
    # --------------------------------------------------------

    try:

        while not state.stop_event.is_set():

            history = "".join(
                state.get_results()
            )

            history = clean_history(
                history
            )


            if history:

                os.system(
                    "cls"
                    if os.name == "nt"
                    else "clear"
                )


                # --------------------------------------------
                # Current detected Big Road
                # --------------------------------------------

                try:

                    frame = vision.capture()

                    bigroad = vision.crop(
                        frame,
                        ROIS["bigroad"],
                    )

                    detected_history, circles = (
                        history_from_image(
                            bigroad
                        )
                    )

                    # draw_detected_board(
                    #     circles
                    # )

                except Exception as exc:

                    print(
                        f"[DISPLAY] "
                        f"Big Road error: "
                        f"{exc}"
                    )


                # --------------------------------------------
                # Generated Big Road
                # --------------------------------------------

                # draw_bigroad(
                #     history
                # )


                # --------------------------------------------
                # Redis prediction
                # --------------------------------------------

                redis_score = (
                    redis_pattern_prediction(
                        history
                    )
                )


                # --------------------------------------------
                # Historical nearest prediction
                # --------------------------------------------

                nearest_score = (
                    nearest_pattern_prediction(
                        history
                    )
                )


                # --------------------------------------------
                # Markov
                # --------------------------------------------

                markov_score = (
                    markov_prediction(
                        history,
                        order=3,
                    )
                )


                # --------------------------------------------
                # Frequency
                # --------------------------------------------

                frequency_score = (
                    frequency_prediction(
                        history
                    )
                )


                # --------------------------------------------
                # Tie
                # --------------------------------------------

                tie_score = (
                    tie_prediction(
                        history
                    )
                )


                # --------------------------------------------
                # Redis display
                # --------------------------------------------

                # print_prediction(
                #     history,
                #     redis_score,
                #     "redis",
                # )


                # # --------------------------------------------
                # # Historical display
                # # --------------------------------------------

                # print_prediction(
                #     history,
                #     nearest_score,
                #     "nearest",
                # )


                # --------------------------------------------
                # Combined prediction
                # --------------------------------------------

                combined_score = combine(
                    # redis_score,
                    markov_score,
                    frequency_score,
                    nearest_score,
                )

                combined_score.update(
                    tie_score
                )

                # best_prediction = max(
                #     MAIN_RESULTS,
                #     key=lambda x: combined_score.get(x, 0)
                # )

                # --------------------------------------------
                # Create prediction ONLY once per history
                # --------------------------------------------

                # prediction_created = tracker.set_prediction(
                #     best_prediction,
                #     history,
                # )

                # if prediction_created:

                #     print(
                #         f"\n🎯 COMBINED PREDICTION "
                #         f"FOR NEXT ROUND: "
                #         f"{best_prediction}"
                #     )

                # else:

                #     print(
                #         f"\n[TRACKER] "
                #         f"Pending prediction: "
                #         f"{tracker.pending_prediction}"
                #     )

                # --------------------------------------------
                # Prediction display
                # --------------------------------------------

                print_prediction(
                    history,
                    combined_score,
                    "combined",
                )

                # --------------------------------------------
                # ALWAYS show tracker
                # --------------------------------------------

                print_prediction_stats(
                    tracker
                )

            time.sleep(
                0.5
            )


    except KeyboardInterrupt:

        print(
            "\nStopping..."
        )

        state.stop()


    finally:

        state.stop()

        vision_thread.join(
            timeout=3
        )

        cv2.destroyAllWindows()

        print(
            "Exited."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
