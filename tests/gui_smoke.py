"""Exercise real Tk controls with a simulated game and no desktop clicks.

Run: python tests/gui_smoke.py
The window closes automatically. A preview is saved to .cache/gui-preview.png.
"""
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from farm_engine import FarmEngine, GameWindow
from gui import FarmApp

window = GameWindow(0, 0, 1920, 1080, 'Mock game window', 7)

with patch('gui.load_settings', return_value={}), patch('gui.save_settings'), \
     patch('gui.list_game_windows', return_value=[window]), \
     patch.object(FarmApp, '_focus_target'), \
     patch.object(FarmEngine, 'get_game_window', return_value=window), \
     patch.object(FarmEngine, 'find_button', return_value=None), \
     patch('farm_engine.pyautogui.click') as clicks:
    app = FarmApp()
    def pump_until(condition, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= deadline:
                raise AssertionError('GUI condition timed out')
            app.update()
            time.sleep(0.01)
        app.update()
    try:
        app.update()
        app.total_energy.set('10')
        app.energy_per_try.set('5')
        app.window_choice.set('Mock game window [7]')
        app.refresh_button.invoke()
        assert app.run_count.get() == 'Target: 2 additional battles'
        app.start_button.invoke()
        pump_until(lambda: app._worker.is_alive())
        assert app.start_button.cget('state') == 'disabled'
        assert app.window_menu.cget('state') == 'disabled'
        worker = app._worker
        app._start()
        assert app._worker is worker
        app.pause_button.invoke()
        assert app._engine.is_paused
        assert app.pause_button.cget('text') == 'Resume'
        app.pause_button.invoke()
        assert not app._engine.is_paused
        app._engine._suspend('Smoke check: recoverable window condition')
        pump_until(lambda: 'Smoke check' in app.status_text.get())
        assert app.pause_button.cget('text') == 'Resume'
        app.lift()
        app.update()
        preview = Path(__file__).resolve().parents[1] / '.cache' / 'gui-preview.png'
        preview.parent.mkdir(exist_ok=True)
        x, y = app.winfo_rootx(), app.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height())).save(preview)
        app.stop_button.invoke()
        pump_until(lambda: not app._worker.is_alive() and not app._running)
        assert app.start_button.cget('state') == 'normal'
        assert app.status_text.get() == 'Stopped by user'
        app.total_energy.set('0')
        app.start_button.invoke()
        pump_until(lambda: not app._worker.is_alive() and not app._running)
        assert app.progress.get() == 1
        assert 'Finished' in app.status_text.get()
        app.total_energy.set('5')
        app.start_button.invoke()
        app._close()
        app.mainloop()
        assert not app._worker.is_alive()
        clicks.assert_not_called()
        print('GUI smoke passed: selection, Start, Pause, Resume, suspension, Stop, restart, zero budget, and close.')
        print(f'Preview: {preview}')
    finally:
        if not app._closing:
            app._close()
            app.mainloop()
