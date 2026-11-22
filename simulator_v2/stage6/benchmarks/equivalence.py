"""Compare published tables from a Stage 4 reference run and an indexed run."""

import argparse
from collections import defaultdict
from itertools import zip_longest
import json
from pathlib import Path

import pyarrow.parquet as pq


def read_json(root, name):
    return json.loads((root / name).read_bytes())


def table_partitions(root):
    tables = defaultdict(dict)
    for path, info in read_json(root, "hashes.json")["partitions"].items():
        tables[info["table"]][path] = info
    return tables


def rows(root, path):
    for batch in pq.ParquetFile(root / path).iter_batches(batch_size=8192):
        yield from batch.to_pylist()


def journal_by_id(root, parts):
    result = {}
    for path in sorted(parts):
        for row in rows(root, path):
            key = row["journal_id"]
            if key in result:
                raise ValueError(f"duplicate journal identity: {key}")
            result[key] = row, parts[path]["month"]
    return result


def assert_equal(left, right, name):
    if left != right:
        raise ValueError(f"equivalence failed: {name}")


def compare(original, optimized):
    reference, candidate = (table_partitions(root) for root in (original, optimized))
    assert_equal(set(reference), set(candidate), "table set")
    assert_equal(read_json(original, "config.json"), read_json(optimized, "config.json"), "configuration")
    run_a, run_b = (read_json(root, "run_manifest.json")["run_id"] for root in (original, optimized))
    assert_equal(run_a, run_b, "comparison run namespace")
    result = {"run_id_held_constant": run_a, "tables": {}, "restated_rows_moved_by_routing_clock": []}
    for table, left in sorted(reference.items()):
        right = candidate[table]
        unchanged = sum(info == right.get(path) for path, info in left.items())
        count = sum(info["rows"] for info in left.values())
        result["tables"][table] = {"rows": count, "byte_identical_partitions": unchanged,
                                   "original_partitions": len(left), "optimized_partitions": len(right)}
        if left == right:
            continue
        if table == "journals_restated":
            before, after = journal_by_id(original, left), journal_by_id(optimized, right)
            assert_equal(before.keys(), after.keys(), "restated journal identity set")
            for key, (row, earlier) in before.items():
                new_row, later = after[key]
                assert_equal(row, new_row, key)
                if earlier != later:
                    if not row["restatement_approval_id"] or row["period_routing_at"] >= row["posted_at"]:
                        raise ValueError(f"unapproved routing partition change: {key}")
                    result["restated_rows_moved_by_routing_clock"].append(
                        {"journal_id": key, "original_partition": earlier, "optimized_partition": later})
            continue
        assert_equal(left.keys(), right.keys(), f"{table} partition set")
        for path, info in sorted(left.items()):
            if info == right[path]:
                continue
            old_rows, new_rows = rows(original, path), rows(optimized, path)
            for index, (old, new) in enumerate(zip_longest(old_rows, new_rows), 1):
                assert_equal(old, new, f"{path} row {index}")
    for name in ("monthly_summary.json", "weather.json"):
        assert_equal(read_json(original, name), read_json(optimized, name), name)
    old, new = (read_json(root, "diagnostics.json") for root in (original, optimized))
    assert_equal(old, {key: new[key] for key in old}, "existing diagnostics")
    result.update(passed=True, equal_monthly_financial_summary=True, equal_weather=True,
                  equal_existing_diagnostics=True, optimized_stock_reporting=new["stock_reporting"],
                  equal_historical_as_known_and_restated_snapshots=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("optimized", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.original, args.optimized)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
