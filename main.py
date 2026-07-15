import pyautogui
import time
import os

# Resolve asset paths relative to this script's location
_DIR = os.path.dirname(os.path.abspath(__file__))

NEXT_BATTLE_IMAGE = os.path.join(_DIR, "assets", "next_alt.png")
NEXT_EXP_IMAGE    = os.path.join(_DIR, "assets", "next.png")
RETRY_IMAGE       = os.path.join(_DIR, "assets", "retry.png")

TARGET_RETRIES = 8
retry_count = 0

screen_width, screen_height = pyautogui.size()
bottom_right_region = (screen_width // 2, screen_height // 2, screen_width // 2, screen_height // 2)

if not os.path.exists(NEXT_BATTLE_IMAGE):
    print("[WARNING] assets/next_alt.png not found!")
    print("  → Screenshot the Next button on the BATTLE REPORT screen and save it as assets/next_alt.png")
    print("  → The script will still run but may not detect the battle report Next button.\n")

print(f"Starting auto-farmer. Target runs: {TARGET_RETRIES}")
print("Press Ctrl+C to stop.")


def find_button(image_path, confidence=0.8):
    """Try to locate a button on screen. Returns center coords or None."""
    if not os.path.exists(image_path):
        return None
    try:
        return pyautogui.locateCenterOnScreen(
            image_path,
            confidence=confidence,
            region=bottom_right_region
        )
    except pyautogui.ImageNotFoundException:
        return None


def find_any_button(image_paths, confidence=0.8):
    """Try a list of images and return the first match found."""
    for path in image_paths:
        btn = find_button(path, confidence)
        if btn:
            return btn, path
    return None, None


while retry_count < TARGET_RETRIES:
    print("Scanning...")
    battle_next = find_button(NEXT_BATTLE_IMAGE)

    if battle_next:
        print("Battle report Next found! Clicking... [next_alt]")
        pyautogui.click(battle_next)
        time.sleep(3)

        print("Checking for EXP gain Next button...")
        exp_next = find_button(NEXT_EXP_IMAGE)
        if exp_next:
            print("EXP Next found! Clicking... [next]")
            pyautogui.click(exp_next)
            time.sleep(3)
        else:
            print("No EXP Next button — Path B, going straight to Retry.")

        print("Scanning for Retry button...")
        retry_btn = find_button(RETRY_IMAGE)
        if retry_btn:
            print("Retry found! Clicking...")
            pyautogui.click(retry_btn)
            retry_count += 1
            print(f"Run {retry_count}/{TARGET_RETRIES} started. Waiting 60 seconds...")
            time.sleep(60)
        else:
            print("Retry not found yet — will scan again next loop.")

    time.sleep(3)

print(f"Auto-farmer finished! Total runs: {retry_count}")