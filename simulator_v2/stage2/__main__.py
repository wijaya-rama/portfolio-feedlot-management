"""Build the Stage 2 Stage 1-linked synthetic fixture."""

import argparse
import json
import sys
from pathlib import Path

from .export import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new, dedicated output directory")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        run_id = build(args.output, args.seed)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"run_id": run_id, "status": "passed", "synthetic": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
