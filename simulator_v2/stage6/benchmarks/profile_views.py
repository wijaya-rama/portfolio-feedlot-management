"""Add as-known and restatement book timings to the standard preflight profiler."""

from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from resource import RUSAGE_SELF, getrusage
import sys
from time import perf_counter


def main():
    from simulator_v2.stage6.finance import Finance

    profiler = Path(__file__).resolve().parents[1] / "benchmark_profile.py"
    spec = spec_from_file_location("stage6_preflight_profile", profiler)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    view_seconds, peaks, calls = Counter(), Counter(), Counter()
    original = Finance.books

    def profiled_books(self, cutoff):
        started = perf_counter()
        for view, close in original(self, cutoff):
            view_seconds[view] += perf_counter() - started
            peaks[view] = max(peaks[view], getrusage(RUSAGE_SELF).ru_maxrss)
            calls[view] += 1
            yield view, close
            started = perf_counter()

    Finance.books = profiled_books
    module.main()
    metrics = Path(sys.argv[sys.argv.index("--metrics") + 1])
    result = json.loads(metrics.read_bytes())
    result["book_view_profiles"] = {
        key: {"journal_posting_and_close_seconds": round(seconds, 4),
              "close_count": calls[key], "process_high_water_rss_kib_after_view": peaks[key]}
        for key, seconds in view_seconds.items()
    }
    metrics.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
