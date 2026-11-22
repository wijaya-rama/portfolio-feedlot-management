"""Build the corrected Stage 3.5 integrated fixture."""

import argparse
import json
import sys
from pathlib import Path

from ..stage1.provenance import canonical
from ..stage1.validation import Check, ValidationError
from .export import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new, dedicated output directory")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        run_id = build(args.output, args.seed)
    except (OSError, ValueError) as exc:
        checks = exc.checks if isinstance(exc, ValidationError) else (
            Check("STAGE35_BUILD", "run", "valid inputs and dedicated output", str(exc), 1),)
        print(canonical({"status": "failed", "synthetic": True, "checks": checks}).decode().rstrip(),
              file=sys.stderr)
        return 1
    print(json.dumps({"run_id": run_id, "output": str(args.output), "status": "passed", "synthetic": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
