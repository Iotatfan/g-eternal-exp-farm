# G Eternal EXP Farm

Windows desktop automation for farming EXP using image recognition.

## Install and launch

```powershell
pip install -r requirements.txt
python main.py --gui
```

Use a visible game window at 1920 x 1080, with Next and Retry in its bottom-right quadrant. Existing button templates and the 0.82 match threshold are retained; other layouts or resolutions may require new templates.

1. Start the initial stage manually.
2. Enter the energy **remaining after that start** and the energy cost of one additional battle.
3. Refresh the window list and select the game window. Window labels include their handles to distinguish duplicate titles.
4. Select Start. The GUI requests focus for the selected window. Keep it visible and unobstructed while automation runs.

For example, 120 remaining energy at 5 per battle funds 24 additional battles. The manually started battle is excluded. Leftover energy stays unused. Zero additional battles completes immediately without screen capture or clicks.

## Progress and recovery

Started counts increase when Retry disappears after an automated click. Completed counts increase when the next battle report is observed. The final battle's report and EXP screens are processed, then automation stops at Retry without starting another battle.

Pause suspends actions; Resume captures the screen again. Stop interrupts polling and paused waits. Configuration stays locked until the worker exits. Closing the GUI requests Stop and waits asynchronously for the worker before closing.

Missing/minimized windows, focus loss, a 30-second transition timeout, or a 10-minute battle timeout suspend automation with an explanation. Paused time is excluded from timeouts. Correct the condition, then select Resume; it requests focus and rechecks the expected screen with a fresh timeout after a suspension. Pending clicks are not repeated automatically. If a Next click was ignored, advance that result screen manually before resuming. If Retry was ignored, stop and start a fresh session with the current remaining energy rather than advancing battles unseen by the engine.

Screen observations are completion evidence, not game telemetry: template mismatches, obstructing windows, and unsupported popups can require intervention. A disappeared window must be selected again in a new session.

Valid inputs and the selected window title are saved atomically in `settings.json`. Invalid settings are ignored. Handles are never persisted; the current window must still exist at Start. The activity log retains the latest 1,000 lines.

## Command line

```powershell
python main.py --total-energy 120 --energy-per-try 5 --window-title "SD Gundam"
```

`--window-title` is a case-insensitive substring and must match exactly one window. Without it, exactly one supported game/emulator title must match. Ambiguity or absence produces an error. Start and recovery request focus for the selected window. On suspension, correct the condition and press Enter in the terminal to resume, or Ctrl+C to stop.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m py_compile main.py farm_engine.py gui.py
```

To exercise the actual desktop controls with a simulated game (no desktop clicks):

```powershell
python tests/gui_smoke.py
```

This briefly opens the interface, verifies its controls and shutdown, saves `.cache/gui-preview.png`, and closes automatically.

The tests simulate screen detections and window APIs without clicking the desktop. They cover delayed screens, ignored clicks, completion accounting, pause/stop, timeout recovery, window changes, template caching, malformed settings, stale GUI events, and shutdown. Live gameplay remains an acceptance check with the game running.
