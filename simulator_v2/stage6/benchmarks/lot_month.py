"""Measure a 12-month single-lot Parquet query using optional DuckDB."""

import argparse
import json
from math import ceil
import os
from pathlib import Path
from statistics import median
from time import perf_counter


SQL = """
    SELECT month, count(*) AS allocations, sum(g_dm) AS grams_dm, sum(cents) AS fifo_cents
    FROM read_parquet(?, hive_partitioning = true)
    WHERE month BETWEEN ? AND ? AND lot_id = ?
    GROUP BY month ORDER BY month
"""


def stats(samples):
    ordered = sorted(samples)
    return {"median_seconds": median(ordered), "p95_seconds": ordered[ceil(len(ordered) * .95) - 1],
            "samples_seconds": samples}


def measure(root, start, end, lot):
    import duckdb

    table = root / "accounting_feed_allocations"
    paths = sorted(table.glob("month=*/part.parquet"))
    files_in_range = [path for path in paths if start <= path.parent.name.split("=")[1] <= end]
    params = [str(table / "month=*" / "part.parquet"), start, end, lot]

    def new_connection():
        return duckdb.connect(config={"threads": "1"})

    def query(con):
        started = perf_counter()
        result = con.execute(SQL, params).fetchall()
        return perf_counter() - started, result

    cold, warm = [], []
    cached_results = None
    advised = hasattr(os, "posix_fadvise")
    for _ in range(5):
        if advised:
            for path in paths:
                with path.open("rb") as stream:
                    os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        with new_connection() as connection:
            seconds, result = query(connection)
            cold.append(seconds)
            if cached_results is not None and cached_results != result:
                raise ValueError("lot-month query changed across fresh connections")
            cached_results = result
    if not cached_results:
        raise ValueError("choose a lot with allocations in the requested months")
    with new_connection() as connection:
        query(connection)
        for _ in range(10):
            seconds, result = query(connection)
            if result != cached_results:
                raise ValueError("lot-month query changed on a warm connection")
            warm.append(seconds)
        plan = connection.execute("EXPLAIN ANALYZE " + SQL, params).fetchone()[1]
    return {"duckdb_version": duckdb.__version__, "threads": 1, "lot_id": lot, "first_month": start,
            "last_month": end, "cold_filesystem_eviction_advised": advised, "cold": stats(cold),
            "warm": stats(warm), "candidate_files": len(paths), "files_in_month_filter": len(files_in_range),
            "compressed_file_bytes_in_month_filter": sum(path.stat().st_size for path in files_in_range),
            "results": cached_results, "query_plan": plan.replace(str(root), "<dataset>")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--first", default="2024-01")
    parser.add_argument("--last", default="2024-12")
    parser.add_argument("--lot", default="SYN-LOT-0001")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = measure(args.dataset, args.first, args.last, args.lot)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
