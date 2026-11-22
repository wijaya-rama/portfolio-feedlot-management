"""Publish the Stage 4 financial control fixture."""

import argparse
import sys

from ..stage1.provenance import canonical
from ..stage1.validation import ValidationError
from .export import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="new dedicated directory")
    parser.add_argument("--seed", type=int, choices=(42,), default=42)
    args = parser.parse_args()
    try:
        run_id = build(args.output, args.seed)
    except (OSError, ValueError) as exc:
        error = {"status": "failed", "reason": str(exc), "synthetic": True}
        if isinstance(exc, ValidationError):
            error["checks"] = exc.checks
        sys.stderr.write(canonical(error).decode())
        return 1
    print(canonical({"run_id": run_id, "output": args.output, "status": "passed", "synthetic": True}).decode(),
          end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
