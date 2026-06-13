import pyautogui
import time

NEXT_IMAGE = "assets/next.png"
RETRY_IMAGE = "assets/retry_campaign.png"

TARGET_RETRIES = 3
retry_count = 0

screen_width, screen_height = pyautogui.size()
bottom_right_region = (screen_width // 2, screen_height // 2, screen_width // 2, screen_height // 2)

print(f"Starting auto-farmer. Target runs: {TARGET_RETRIES}")
print("Press Ctrl+C to stop.")

while retry_count < TARGET_RETRIES:
    print("Scanning for Next button...")
    try:
        next_btn = pyautogui.locateCenterOnScreen(
            NEXT_IMAGE,
            confidence=0.9,
            region=bottom_right_region
        )
    except pyautogui.ImageNotFoundException:
        next_btn = None

    if next_btn:
        print("Next btn found! Clicking...")
        pyautogui.click(next_btn)

        time.sleep(5)

        print("Scanning for Retry button...")
        try:
            retry_btn = pyautogui.locateCenterOnScreen(
                RETRY_IMAGE,
                confidence=0.9,
                region=bottom_right_region
            )
        except pyautogui.ImageNotFoundException:
            retry_btn = None

        if retry_btn:
            print("Retry btn found! Clicking...")
            pyautogui.click(retry_btn)

            retry_count += 1

            print(f"Run {retry_count}/{TARGET_RETRIES} started. Waiting 60 seconds...")
            time.sleep(60)

    time.sleep(5)

print(f"Auto-farmer finished! Total runs: {retry_count}")