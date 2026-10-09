"""Workflow tests use simulated observations: no desktop clicks or captures."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import numpy as np
import farm_engine as f

WINDOW = f.GameWindow(0, 0, 1920, 1080, 'Game', 7)
B, E, R = f.NEXT_BATTLE_IMAGE, f.NEXT_EXP_IMAGE, f.RETRY_IMAGE

class WorkflowTests(unittest.TestCase):
    def run_script(self, observations, config=None, on_status=None):
        statuses, clock = [], [0.0]
        def emit(status):
            statuses.append(status)
            if on_status:
                on_status(engine, status)
        engine = f.FarmEngine(config or f.FarmConfig(5, 5, window_handle=7, poll_wait_seconds=0), emit)
        script = iter(observations)
        def find(path, region):
            expected, result = next(script)
            self.assertEqual(path, expected)
            if callable(result):
                return result(engine)
            return (1200, 800) if result else None
        def wait(seconds):
            clock[0] += 1
            return not engine._stop_event.is_set()
        with patch.object(engine, 'get_game_window', return_value=WINDOW), patch.object(engine, 'find_button', side_effect=find), patch.object(engine, '_wait', side_effect=wait), patch('farm_engine.time.monotonic', side_effect=lambda: clock[0]), patch('farm_engine.pyautogui.click') as click:
            engine.run()
        self.assertEqual(list(script), [])
        return engine, statuses, click

    def test_delayed_screens_and_final_results(self):
        observations = [(B, True), (E, False), (E, True), (R, False), (R, True),
                        (R, True), (R, False), (B, False), (B, True), (E, True), (R, True)]
        engine, statuses, clicks = self.run_script(observations)
        self.assertEqual((engine.started_count, engine.retry_count), (1, 1))
        self.assertEqual(clicks.call_count, 5)  # Both result screens, exactly one Retry.
        self.assertEqual(statuses[-1].state, 'completed')
        started = next(s for s in statuses if s.state == 'battle_started')
        self.assertEqual(started.completed_count, 0)

    def test_multiple_additional_battles_exclude_initial(self):
        engine, statuses, clicks = self.run_script(
            [(B, True), (E, True), (R, True), (R, False),
             (B, True), (E, True), (R, True), (R, False),
             (B, True), (E, True), (R, True)], f.FarmConfig(10, 5, window_handle=7))
        self.assertEqual((engine.started_count, engine.retry_count), (2, 2))
        self.assertEqual(clicks.call_count, 8)
        self.assertEqual(statuses[-1].state, 'completed')

    def test_ignored_retry_suspends_without_increment_or_reclick(self):
        def stop_suspended(engine, status):
            if status.state == 'suspended':
                engine.stop()
        engine, statuses, clicks = self.run_script(
            [(B, True), (E, True), (R, True), (R, True)],
            f.FarmConfig(5, 5, window_handle=7, transition_timeout_seconds=0), stop_suspended)
        self.assertEqual((engine.started_count, engine.retry_count), (0, 0))
        self.assertEqual(clicks.call_count, 3)
        self.assertTrue(any(s.state == 'suspended' and 'retry departure' in s.message for s in statuses))
        self.assertEqual(statuses[-1].state, 'stopped')

    def test_timeout_resume_keeps_expected_screen(self):
        def recover(engine, status):
            if status.state == 'suspended':
                engine.resume()
        engine, statuses, clicks = self.run_script(
            [(B, True), (E, False), (E, True), (R, True), (R, False), (B, True), (E, True), (R, True)],
            f.FarmConfig(5, 5, window_handle=7, transition_timeout_seconds=0), recover)
        self.assertEqual(clicks.call_count, 5)
        self.assertEqual(statuses[-1].state, 'completed')
        self.assertEqual(engine.retry_count, 1)

    def test_stop_during_matching_prevents_click(self):
        def stop(engine):
            engine.stop()
            return (1200, 800)
        _, statuses, clicks = self.run_script([(B, stop)])
        clicks.assert_not_called()
        self.assertEqual(statuses[-1].state, 'stopped')

    def test_pause_resume_during_matching_discards_coordinates(self):
        def pause_resume(engine):
            engine.pause()
            engine.resume()
            return (1, 1)
        _, _, clicks = self.run_script([(B, pause_resume), (B, True), (E, True), (R, True),
                                       (R, False), (B, True), (E, True), (R, True)])
        self.assertEqual(clicks.call_count, 5)
        self.assertNotIn(unittest.mock.call(1, 1), clicks.call_args_list)

    def test_window_move_discards_old_coordinates(self):
        engine = f.FarmEngine(f.FarmConfig(5, 5, window_handle=7))
        moved = replace(WINDOW, left=200)
        with patch.object(engine, 'get_game_window', return_value=moved), patch('farm_engine.pyautogui.click') as click:
            self.assertFalse(engine._click((1200, 800), WINDOW, 0))
            self.assertTrue(engine._click((1400, 800), moved, 0))
            click.assert_called_once_with(1400, 800)
        self.assertEqual(engine._region(moved)['left'], 1160)

    def test_focus_loss_before_click_suspends(self):
        engine = f.FarmEngine(f.FarmConfig(5, 5, window_handle=7))
        with patch.object(engine, 'get_game_window', side_effect=RuntimeError('Selected window lost focus')), patch('farm_engine.pyautogui.click') as click:
            with self.assertRaises(RuntimeError):
                engine._click((1, 1), WINDOW, 0)
            click.assert_not_called()

    def test_window_failure_suspends_workflow(self):
        statuses = []
        engine = f.FarmEngine(f.FarmConfig(5, 5, window_handle=7))
        def emit(status):
            statuses.append(status)
            if status.state == 'suspended':
                engine.stop()
        engine.on_status = emit
        with patch.object(engine, 'get_game_window', side_effect=RuntimeError('Selected window disappeared')), patch('farm_engine.pyautogui.click') as click:
            engine.run()
        click.assert_not_called()
        self.assertEqual(statuses[-2].suspension_reason, 'Selected window disappeared')
        self.assertEqual(statuses[-1].state, 'stopped')

    def test_pause_time_is_excluded_and_stop_interrupts_pause(self):
        clock = [10.0]
        engine = f.FarmEngine(f.FarmConfig(5, 5))
        with patch('farm_engine.time.monotonic', side_effect=lambda: clock[0]):
            engine.pause()
            clock[0] = 100.0
            self.assertEqual(engine._active_time(), 10.0)
            engine.resume()
            clock[0] = 105.0
            self.assertEqual(engine._active_time(), 15.0)
            engine.pause()
            engine.stop()
            self.assertFalse(engine._checkpoint())

    def test_template_variants_are_cached(self):
        engine = f.FarmEngine(f.FarmConfig(5, 5))
        template = np.random.default_rng(7).integers(0, 255, (20, 20), dtype=np.uint8)
        screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
        with patch('farm_engine.cv2.imread', return_value=template) as read, patch.object(engine, 'grab_window', return_value=screenshot), patch('farm_engine.cv2.resize', wraps=f.cv2.resize) as resize:
            engine.find_button(B, {'left': 0, 'top': 0, 'width': 100, 'height': 100})
            engine.find_button(B, {'left': 0, 'top': 0, 'width': 100, 'height': 100})
            read.assert_called_once()
            self.assertEqual(resize.call_count, len(engine.scales))

class SelectionAndConfigTests(unittest.TestCase):
    def test_invalid_timing_values(self):
        for name in ('battle_wait_seconds', 'transition_wait_seconds', 'poll_wait_seconds',
                     'transition_timeout_seconds', 'battle_timeout_seconds'):
            for value in (-1, float('nan'), float('inf')):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    f.FarmConfig(5, 5, **{name: value})
            f.FarmConfig(5, 5, **{name: 0})

    def test_ambiguous_window_requires_selection(self):
        windows = [WINDOW, replace(WINDOW, title='Other Game', handle=8)]
        with patch('farm_engine.list_game_windows', return_value=windows):
            with self.assertRaises(f.FarmValidationError):
                f.select_game_window('Game')
            self.assertEqual(f.select_game_window('Other').handle, 8)
            with self.assertRaises(f.FarmValidationError):
                f.select_game_window('Missing')

    def test_selected_handle_bounds_and_window_failures(self):
        window = SimpleNamespace(_hWnd=7, left=10, top=20, width=1920, height=1080,
                                 title='Game', isMinimized=False)
        engine = f.FarmEngine(f.FarmConfig(5, 5, window_handle=7))
        with patch('farm_engine.gw.getAllWindows', return_value=[window]) as all_windows, patch('farm_engine.gw.getActiveWindow', return_value=window) as active:
            self.assertEqual(engine.get_game_window().left, 10)
            window.left = 100
            self.assertEqual(engine.get_game_window().left, 100)
            window.isMinimized = True
            with self.assertRaisesRegex(RuntimeError, 'minimized'):
                engine.get_game_window()
            window.isMinimized = False
            active.return_value = SimpleNamespace(_hWnd=8)
            with self.assertRaisesRegex(RuntimeError, 'focus'):
                engine.get_game_window()
            all_windows.return_value = []
            with self.assertRaisesRegex(RuntimeError, 'disappeared'):
                engine.get_game_window()

    def test_native_window_race_is_recoverable(self):
        engine = f.FarmEngine(f.FarmConfig(5, 5, window_handle=7))
        with patch('farm_engine.gw.getAllWindows', side_effect=f.gw.PyGetWindowException('invalid handle')):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                engine.get_game_window()
