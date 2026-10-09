"""Settings and GUI lifecycle tests without creating visible windows."""
import json
import os
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from farm_engine import FarmConfig, FarmEngine, FarmStatus
from gui import FarmApp, load_settings, save_settings

class SettingsTests(unittest.TestCase):
    def test_malformed_settings_are_tolerated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'settings.json')
            self.assertEqual(load_settings(path), {})
            for value in ('[]', 'null', '5', '{', '{"total_energy": -1, "energy_per_try": 5}',
                          '{"total_energy": {}, "energy_per_try": 5}'):
                with self.subTest(value=value):
                    with open(path, 'w', encoding='utf-8') as target:
                        target.write(value)
                    self.assertEqual(load_settings(path), {})

    def test_atomic_roundtrip_and_failure_preserve_previous_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'settings.json')
            original = {'total_energy': '20', 'energy_per_try': '5', 'window_title': 'Game'}
            save_settings(path, original)
            self.assertEqual(load_settings(path), original)
            with patch('gui.os.replace', side_effect=OSError('blocked')):
                with self.assertRaises(OSError):
                    save_settings(path, {'total_energy': '10'})
            self.assertEqual(load_settings(path), original)
            self.assertEqual(os.listdir(folder), ['settings.json'])

class GuiLifecycleTests(unittest.TestCase):
    def app(self):
        engine = FarmEngine(FarmConfig(10, 5, window_handle=7))
        return SimpleNamespace(_closing=False, _running=True, _run_id=2, _events=queue.Queue(),
            _worker=SimpleNamespace(is_alive=Mock(return_value=True)), _engine=engine,
            status_text=Mock(), run_count=Mock(), progress=Mock(), pause_button=Mock(),
            _append_log=Mock(), _set_running=Mock(), _process_events=Mock(), after=Mock(),
            _save_settings=Mock(), _finish_close=Mock(), destroy=Mock())

    def test_stale_events_ignored_and_error_keeps_progress_until_worker_exits(self):
        app = self.app()
        app._events.put((1, FarmStatus('completed', 0, 0, 'stale')))
        app._events.put((2, FarmStatus('error', 1, 2, 'capture failed', 2, 1)))
        FarmApp._process_events(app)
        app.status_text.set.assert_called_once_with('capture failed')
        app.run_count.set.assert_called_once_with('Started: 2 | Completed: 1 / 2')
        app.progress.set.assert_called_once_with(0.5)
        app._set_running.assert_not_called()
        app._worker.is_alive.return_value = False
        FarmApp._process_events(app)
        app._set_running.assert_called_once_with(False)

    def test_start_rejected_while_previous_worker_alive(self):
        app = self.app()
        FarmApp._start(app)
        app._save_settings.assert_not_called()

    def test_close_requests_stop_and_waits_asynchronously(self):
        app = self.app()
        FarmApp._close(app)
        self.assertTrue(app._closing)
        self.assertTrue(app._engine._stop_event.is_set())
        app._finish_close.assert_called_once()
        FarmApp._finish_close(app)
        app.destroy.assert_not_called()
        app.after.assert_called_once_with(50, app._finish_close)
        app._worker.is_alive.return_value = False
        FarmApp._finish_close(app)
        app.destroy.assert_called_once()
        FarmApp._close(app)
        app._save_settings.assert_called_once()

    def test_controls_and_configuration_follow_worker_state(self):
        app = self.app()
        app.start_button = Mock()
        app.stop_button = Mock()
        app._config_widgets = [Mock(), Mock()]
        FarmApp._set_running(app, True)
        app.start_button.configure.assert_called_with(state='disabled')
        for widget in app._config_widgets:
            widget.configure.assert_called_with(state='disabled')
        FarmApp._set_running(app, False)
        app.start_button.configure.assert_called_with(state='normal')

    def test_suspend_updates_resume_control(self):
        app = self.app()
        app._engine.pause()
        app._events.put((2, app._engine.status('suspended', 'lost focus')))
        FarmApp._process_events(app)
        app.pause_button.configure.assert_called_with(text='Resume')
        app._set_running.assert_not_called()

    def test_log_is_bounded(self):
        app = SimpleNamespace(log_box=Mock(), _log_lines=1000)
        FarmApp._append_log(app, 'message')
        app.log_box.delete.assert_called_once_with('1.0', '2.0')
        self.assertEqual(app._log_lines, 1000)

    def test_worker_uses_passed_engine_and_preserves_failure_snapshot(self):
        app = self.app()
        original = FarmEngine(FarmConfig(10, 5, window_handle=7),
                              on_status=lambda status: app._events.put((2, status)))
        original.started_count, original.retry_count = 2, 1
        with patch.object(original, 'validate_startup', side_effect=RuntimeError('failure')):
            with self.assertLogs('farm_engine', level='ERROR'), self.assertLogs('gui', level='ERROR'):
                FarmApp._run_engine(app, original, 2)
        run_id, status = app._events.get_nowait()
        self.assertEqual((run_id, status.started_count, status.completed_count), (2, 2, 1))
        self.assertEqual(status.state, 'error')
        self.assertTrue(app._events.empty())
