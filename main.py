"""Command-line entry point for the EXP farmer."""

import argparse

from farm_engine import FarmConfig, FarmEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Farm EXP using the available energy.")
    parser.add_argument(
        "--total-energy", type=int, required=True,
        help="Total energy available for farming.",
    )
    parser.add_argument(
        "--energy-per-try", type=int, required=True,
        help="Energy consumed by one try.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        config = FarmConfig(args.total_energy, args.energy_per_try)
    except ValueError as error:
        raise SystemExit(f"error: {error}") from error

    def log_status(status) -> None:
        print(status.message)

    engine = FarmEngine(config, on_status=log_status)
    print("Press Ctrl+C to stop.")
    try:
        engine.run()
    except KeyboardInterrupt:
        engine.stop()
        print("Stopping...")


if __name__ == "__main__":
    main()
