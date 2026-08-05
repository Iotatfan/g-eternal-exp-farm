# G Eternal EXP Farm

Auto-clicker script for farming EXP using image recognition.

## Install
```bash
pip install pyautogui opencv-python Pillow
```

## Usage
1. Make sure the game is visible, running at 1920 x 1080 resolution, and the Next/Retry buttons are in the **bottom-right** of your screen.
2. Run the stage manually and note your total energy and the energy cost per try.
3. Start the script with those values:
```bash
python main.py --total-energy 120 --energy-per-try 5
```

The script calculates complete runs as `total energy // energy per try`. Any
remaining energy that cannot fund a complete try is left unused.

*To stop the script at any time, press `Ctrl+C` in the terminal.
