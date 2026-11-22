"""Measure Stage 6 with nested phase timers; import the simulator from the current checkout."""

import argparse
from collections import Counter
from functools import wraps
import json
from pathlib import Path
from resource import RUSAGE_SELF, getrusage
from time import perf_counter


def main():
    from simulator_v2.stage6 import __main__ as cli, runner, finance, finance_store, export, validation
    from simulator_v2.stage4 import close, ledger
    from simulator_v2.stage6.config import DIAGNOSTIC, load

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DIAGNOSTIC)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--comparison-manifest", type=Path,
                        help="Hold the run namespace fixed for an equivalence build from the same config")
    args = parser.parse_args()
    if args.comparison_manifest:
        baseline = json.loads(args.comparison_manifest.read_bytes())
        baseline_config = json.loads(args.comparison_manifest.with_name("config.json").read_bytes())
        if baseline_config != load(args.config, args.seed):
            parser.error("equivalence builds require the same config and seed as the reference")
        original_id = cli.stable_id
        cli.stable_id = lambda prefix, payload: baseline["run_id"] if prefix == "STAGE6-RUN" else original_id(prefix, payload)
    elapsed, exclusive, calls, peaks = Counter(), Counter(), Counter(), Counter()
    stack = []

    def instrument(owner, method, name):
        original = getattr(owner, method)

        @wraps(original)
        def timed(*args, **kwargs):
            start = perf_counter()
            nested = [0.0]
            stack.append(nested)
            try:
                return original(*args, **kwargs)
            finally:
                seconds = perf_counter() - start
                stack.pop()
                if stack:
                    stack[-1][0] += seconds
                elapsed[name] += seconds
                exclusive[name] += seconds - nested[0]
                calls[name] += 1
                peaks[name] = max(peaks[name], getrusage(RUSAGE_SELF).ru_maxrss)

        setattr(owner, method, timed)

    for owner, method, name in [
        (runner.Runner, "operations", "animal_scheduling_and_replay"),
        (runner.Yard, "finalize", "animal_ledger_finalize"),
        (runner, "calculate_soh", "operations_stock_replay"),
        (runner.Health, "day", "health"),
        (runner.Growth, "advance", "biology"),
        (runner.Feeding, "window", "feeding"),
        (runner.Supply, "day", "procurement"),
        (runner.Supply, "grams_for_dm", "fifo_dm_selection"),
        (runner.Supply, "apply", "fifo_transactions"),
        (runner.Supply, "finish", "warehouse_replay"),
        (finance.Finance, "__init__", "financial_source_expansion"),
        (ledger.Book, "run", "journal_posting"),
        (finance_store.FinanceStore, "write_journals", "journal_sqlite_write"),
        (finance, "close_month", "financial_close"),
        (close, "canonical", "close_canonical_serialization"),
        (close, "calculate_soh", "close_stock_replay"),
        (finance, "immediate_warehouse_closes", "close_warehouse_checkpoints"),
        (close, "_warehouse_rows", "close_warehouse_rows_iterable"),
        (export.Output, "flush", "parquet_serialization"),
        (export, "digest", "parquet_file_hashes"),
        (cli, "digest", "input_and_artifact_file_hashes"),
        (cli, "reconcile", "validation"),
        (validation, "audit_finance", "financial_validation"),
        (validation, "audit_feeding", "physical_validation"),
        (cli, "summarize", "report_diagnostics"),
    ]:
        if hasattr(owner, method) and not name.endswith("_iterable"):
            instrument(owner, method, name)
    if hasattr(finance, "CloseIndex"):
        instrument(finance.CloseIndex, "add", "journal_period_index")
        instrument(finance.CloseIndex, "add_fingerprints", "close_journal_fingerprints")
    started = perf_counter()
    cli.build(load(args.config, args.seed), args.output)
    result = {
        "wall_seconds_including_atomic_publish": round(perf_counter() - started, 4),
        "timings": {key: {"seconds": round(value, 4), "exclusive_seconds": round(exclusive[key], 4),
                          "calls": calls[key], "process_high_water_rss_kib_at_phase_end": peaks[key]}
                    for key, value in sorted(elapsed.items())},
    }
    result["performance"] = json.loads((args.output / "performance.json").read_bytes())
    args.metrics.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
