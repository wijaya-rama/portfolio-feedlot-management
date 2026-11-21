"""Build the analytical layer or acquire an explicit source snapshot."""

import argparse
from pathlib import Path

from .exports import write_build
from .pipeline import build
from .weather import fetch_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    core = commands.add_parser("build", help="Validate sources and write a deterministic build")
    core.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    core.add_argument("--output", type=Path, default=Path("work/phase2a"), help="build directory")
    core.add_argument("--weather-snapshot", type=Path, help="replay a saved verified weather snapshot")
    fetch = commands.add_parser("fetch-weather", help="Fetch the documented non-commercial ERA5 reference")
    fetch.add_argument("--output", type=Path, default=Path("work/weather"), help="parent of versioned snapshots")
    args = parser.parse_args()
    try:
        if args.command == "fetch-weather":
            print(fetch_snapshot(args.output))
            return
        result = build(args.root, weather_snapshot=args.weather_snapshot)
        write_build(result, args.output)
        checks = result.reconciliation["summary"]["checks_passed"]
        weather_status = result.transformation_manifest["weather"]["status"]
        print(f"Built {len(result.tables)} tables with {checks} passing controls; weather {weather_status}: {args.output}")
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
