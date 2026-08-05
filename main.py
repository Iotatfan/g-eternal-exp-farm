import cv2
import numpy as np
import pyautogui
import pygetwindow as gw
import mss
import time
import os
import argparse

# Resolve asset paths relative to this script's location
_DIR = os.path.dirname(os.path.abspath(__file__)) 

GAME_WINDOW_TITLE_KEYWORDS = [
    "SD Gundam G Generation ETERNAL",
    "BlueStacks",
    "NIKKE",
    "LDPlayer",
    "MuMu",
]


NEXT_BATTLE_IMAGE = os.path.join(_DIR, "assets", "next_alt.png")
NEXT_EXP_IMAGE    = os.path.join(_DIR, "assets", "next.png")
RETRY_IMAGE       = os.path.join(_DIR, "assets", "retry.png")

def get_target_retries():
    parser = argparse.ArgumentParser(
        description="Farm EXP using the available energy."
    )
    parser.add_argument(
        "--total-energy",
        type=int,
        required=True,
        help="Total energy available for farming.",
    )
    parser.add_argument(
        "--energy-per-try",
        type=int,
        required=True,
        help="Energy consumed by one try.",
    )
    args = parser.parse_args()

    if args.total_energy < 0:
        parser.error("--total-energy must be zero or greater")
    if args.energy_per_try <= 0:
        parser.error("--energy-per-try must be greater than zero")

    return args.total_energy // args.energy_per_try


TARGET_RETRIES = get_target_retries()
retry_count = 0

SCALES = np.arange(0.5, 1.6, 0.05)

MATCH_THRESHOLD = 0.82

screen_width, screen_height = pyautogui.size()
bottom_right_region = (screen_width // 2, screen_height // 2, screen_width // 2, screen_height // 2)

if not os.path.exists(NEXT_BATTLE_IMAGE):
    print("[WARNING] assets/next_alt.png not found!")
    print("  → Screenshot the Next button on the BATTLE REPORT screen and save it as assets/next_alt.png")
    print("  → The script will still run but may not detect the battle report Next button.\n")

print(f"Starting auto-farmer. Target runs: {TARGET_RETRIES}")
print("Press Ctrl+C to stop.")

def get_game_window():
    for window in gw.getAllWindows():
        title = window.title.lower()

        if any(keyword.lower() in title for keyword in GAME_WINDOW_TITLE_KEYWORDS):
            return {
                "left": window.left,
                "top": window.top,
                "width": window.width,
                "height": window.height,
                "title": window.title,
            }

    raise RuntimeError("Game window not found")

def grab_window(region):
    with mss.MSS() as sct:
        img = np.array(sct.grab(region))

    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


# ----------------------------
# Multi-scale Template Matching
# ----------------------------

def find_button(template_path, region):
    if not os.path.exists(template_path):
        return None

    print(f"Searching {os.path.basename(template_path)}")

    screenshot = grab_window(region)
    screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)

    best_score = 0
    best_location = None

    for scale in SCALES:

        resized = cv2.resize(
            template,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_LINEAR
        )

        h, w = resized.shape

        if h > screenshot_gray.shape[0] or w > screenshot_gray.shape[1]:
            continue

        result = cv2.matchTemplate(
            screenshot_gray,
            resized,
            cv2.TM_CCOEFF_NORMED
        )

        _, score, _, location = cv2.minMaxLoc(result)

        if score > best_score:
            best_score = score
            best_location = (
                location[0] + w // 2,
                location[1] + h // 2
            )

    if best_score >= MATCH_THRESHOLD:
        return (
            region["left"] + best_location[0],
            region["top"] + best_location[1]
        )

    return None


# ----------------------------
# Main
# ----------------------------

print(f"Starting auto-farmer ({TARGET_RETRIES} runs)")

while retry_count < TARGET_RETRIES:

    try:
        print("Finding window...")
        window = get_game_window()

    except RuntimeError as e:
        print(e)
        time.sleep(5)
        continue

    # Only search the lower-right quarter of the game window
    search_region = {
        "left": window["left"] + window["width"] // 2,
        "top": window["top"] + window["height"] // 2,
        "width": window["width"] // 2,
        "height": window["height"] // 2
    }
    print(search_region)

    print("Finding button...")
    battle_next = find_button(NEXT_BATTLE_IMAGE, search_region)

    if battle_next:
        print("First Next")
        pyautogui.click(*battle_next)

        time.sleep(3)

        exp_next = find_button(NEXT_EXP_IMAGE, search_region)

        if exp_next:
            print("Second Next")
            pyautogui.click(*exp_next)
            time.sleep(3)

        retry_btn = find_button(RETRY_IMAGE, search_region)

        if retry_btn:
            print("Retry")

            pyautogui.click(*retry_btn)

            retry_count += 1

            print(f"Run {retry_count}/{TARGET_RETRIES}")

            time.sleep(60)

    time.sleep(2)

print("Finished.")
