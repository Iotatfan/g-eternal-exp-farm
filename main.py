"""Command-line entry point for the EXP farmer."""

import argparse
from dataclasses import replace
import logging

import pygetwindow as gw
from farm_engine import FarmConfig, FarmEngine, FarmValidationError, select_game_window


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Farm EXP using the available energy.")
    parser.add_argument(
        "--total-energy", type=int,
        help="Energy remaining after starting the initial battle manually.",
    )
    parser.add_argument(
        "--energy-per-try", type=int,
        help="Energy consumed by one try.",
    )
    parser.add_argument(
        "--gui", action="store_true", help="Launch the CustomTkinter interface."
    )
    parser.add_argument("--window-title", help="Unique, case-insensitive game window title substring.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    if args.gui:
        try:
            from gui import launch
        except ModuleNotFoundError as error:
            if error.name == "customtkinter":
                raise SystemExit(
                    "error: CustomTkinter is not installed; run 'pip install -r requirements.txt'"
                ) from error
            raise

        launch()
        return

    if args.total_energy is None or args.energy_per_try is None:
        raise SystemExit("error: --total-energy and --energy-per-try are required")

    try:
        config = FarmConfig(args.total_energy, args.energy_per_try)
        if config.target_retries:
            config = replace(config, window_handle=select_game_window(args.window_title).handle)
    except ValueError as error:
        raise SystemExit(f"error: {error}") from error

    def log_status(status) -> None:
        if status.message:
            print(status.message)
        if status.state == "suspended":
            input("Correct the condition, then press Enter to resume (Ctrl+C to stop): ")
            focus_target()
            engine.resume()

    def focus_target() -> None:
        window = next((w for w in gw.getAllWindows() if w._hWnd == config.window_handle), None)
        if window is not None and not window.isMinimized:
            try:
                window.activate()
            except Exception as error:
                logging.warning("Could not focus selected window: %s", error)

    engine = FarmEngine(config, on_status=log_status)
    try:
        engine.validate_startup()
    except FarmValidationError as error:
        raise SystemExit(f"error: {error}") from error
    print("Press Ctrl+C to stop.")
    try:
        if config.target_retries:
            focus_target()
        engine.run()
    except FarmValidationError as error:
        raise SystemExit(f"error: {error}") from error
    except KeyboardInterrupt:
        engine.stop()
        print("Stopping...")


if __name__ == "__main__":
    main()
