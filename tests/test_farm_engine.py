import unittest
from unittest.mock import patch

from farm_engine import FarmConfig, FarmEngine, FarmValidationError


class FarmConfigTests(unittest.TestCase):
    def test_target_retries_uses_only_complete_runs(self):
        self.assertEqual(FarmConfig(120, 5).target_retries, 24)
        self.assertEqual(FarmConfig(123, 5).target_retries, 24)

    def test_rejects_invalid_energy_values(self):
        with self.assertRaises(ValueError):
            FarmConfig(-1, 5)
        with self.assertRaises(ValueError):
            FarmConfig(100, 0)


class FarmEngineTests(unittest.TestCase):
    def test_required_assets_are_available(self):
        self.assertEqual(FarmEngine.validate_assets(), [])

    def test_startup_validation_reports_missing_assets(self):
        engine = FarmEngine(FarmConfig(10, 5))
        with patch("farm_engine.REQUIRED_ASSETS", {"Retry": "missing.png"}):
            with self.assertRaises(FarmValidationError):
                engine.validate_startup()

    def test_zero_target_runs_complete_without_screen_access(self):
        statuses = []
        engine = FarmEngine(FarmConfig(0, 5), on_status=statuses.append)
        engine.run()
        self.assertEqual(statuses[-1].state, "completed")
        self.assertEqual(statuses[-1].retry_count, 0)

    def test_stop_interrupts_wait(self):
        engine = FarmEngine(FarmConfig(10, 5))
        engine.stop()
        self.assertFalse(engine._wait(1))


if __name__ == "__main__":
    unittest.main()
