from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime
import json

import pyarrow.parquet as pq
import pytest

from simulator_v2.stage1.model import midnight
from simulator_v2.stage1.provenance import canonical, sha256
from simulator_v2.stage1.soh import StockRow
from simulator_v2.stage4.ledger import Account, periods
from simulator_v2.stage6.benchmark_configs import CONFIGS, SIZES, benchmark_config
from simulator_v2.stage6.close_index import CloseIndex
from simulator_v2.stage6.config import HERE, load
from simulator_v2.stage6.reporting import stock_reporting


@dataclass(frozen=True)
class Entry:
    accounting_month: str
    available_at: datetime
    effective_at: datetime
    component: str = "yardage"
    amount_cents: int = 10
    debit_account: Account = Account.WIP
    credit_account: Account = Account.YARDAGE
    animal_id: str = "animal"
    principal_release: bool = False
    approval_id: str | None = None


def test_incremental_closes_keep_original_and_revised_order_at_each_cutoff():
    calendar = periods(date(2024, 1, 1), date(2024, 3, 20))
    first = midnight(date(2024, 1, 2))
    future = midnight(date(2024, 4, 2))
    opening = Entry("2024-01", first, first, component="opening_wip", amount_cents=100,
                    credit_account=Account.OPENING)
    service = Entry("2024-01", first, first)
    feb = Entry("2024-02", calendar[0].locked_at, calendar[0].locked_at, amount_cents=20)
    march = Entry("2024-03", calendar[1].locked_at, calendar[1].locked_at, amount_cents=30)
    # Exercise a late fact ordered before another already-visible journal in the restated stream.
    adjustment = replace(service, accounting_month="2024-02", available_at=midnight(date(2024, 2, 3)),
                         amount_cents=7, approval_id="approved", component="yardage_correction")
    revised = replace(adjustment, accounting_month="2024-01")
    too_late = replace(march, available_at=future, amount_cents=99)

    def measure(rows, cutoffs):
        index = CloseIndex(calendar, cutoffs)
        index.add(rows[:3])
        index.add(rows[3:])
        result = []
        for period, cutoff, (summary, digest, count) in zip(calendar, cutoffs, index.checkpoints(), strict=True):
            expected = [row for row in rows if row.accounting_month <= period.month and row.available_at <= cutoff]
            assert (digest, count) == (sha256(canonical(expected)), len(expected))
            assert summary.balances[Account.WIP] == sum(row.amount_cents for row in expected)
            result.append((summary.wip["animal"] - summary.current_wip["animal"],
                           summary.wip["animal"], digest))
        return result

    original_rows = [opening, service, feb, adjustment, march, too_late]
    known_cutoffs = tuple(period.locked_at for period in calendar)
    original = measure(original_rows, known_cutoffs)
    restated_rows = [opening, revised, service, feb, march, too_late]
    second = measure(restated_rows, (calendar[-1].locked_at,) * 3)
    assert [r[:2] for r in original] == [(100, 110), (110, 137), (137, 167)]
    assert [r[:2] for r in second] == [(100, 117), (117, 137), (137, 167)]
    assert all(a[2] != b[2] for a, b in zip(original, second))
    nonmonotone = measure([opening, feb, service, adjustment, march, too_late], known_cutoffs)
    assert [row[:2] for row in nonmonotone] == [row[:2] for row in original]
    assert nonmonotone[0][2] == original[0][2]
    assert nonmonotone[1][2] != original[1][2]
    assert measure(original_rows + [replace(too_late, amount_cents=123)], known_cutoffs) == original


def test_finance_reporting_uses_separate_period_and_final_fields():
    root = HERE / "evidence" / "diagnostic"
    yard_rows = [StockRow(**{key: value for key, value in row.items() if key != "run_id"})
                 for path in sorted(root.glob("monthly_soh/month=*/part.parquet"))
                 for row in pq.ParquetFile(path).read().to_pylist() if row["scope_type"] == "yard"]
    statuses = [row["status"] for path in sorted(root.glob("animal_outcomes/month=*/part.parquet"))
                for row in pq.ParquetFile(path).read(columns=["status"]).to_pylist()]
    diagnostic = json.loads((root / "diagnostics.json").read_bytes())
    assert diagnostic["head"] == {"opening": 8, "placements": 100, "sale": 64, "death": 4, "carry_out": 40}
    assert diagnostic["animal_days"] == 4698
    report = stock_reporting(yard_rows, statuses)
    assert report["periods"][1]["period_end"] == date(2025, 12, 31)
    assert report["periods"][1]["period_end_soh"] == 52
    assert report["final_simulation_date"] == date(2026, 2, 28)
    assert report["final_simulation_soh"] == 40
    with pytest.raises(ValueError, match="final simulation SOH"):
        stock_reporting(yard_rows, ["active"] * 52)


@pytest.mark.parametrize("size", SIZES)
def test_materialized_benchmarks_keep_stage5_shape(size):
    config = load(CONFIGS / f"preflight-{size}.json")
    assert config == benchmark_config(size)
    assert (date.fromisoformat(config["end"]) - date.fromisoformat(config["start"])).days + 1 == 731
    assert sum(row["head"] for row in config["placements"]) == size
    assert set(row["minimum_dof"] for row in config["placements"]) == {155, 175, 195}
    used = Counter()
    for row in config["carry_in"]:
        used[row["location"]] += row["head"]
        assert row["source"].startswith("SYN-PREFLIGHT-OPEN-2024-") and row["wip_cents"] > 0
    for number, cap in enumerate(config["capacities"]["production"], 1):
        assert used[f"SYN-P{number:02d}"] <= cap
    assert config["release_minutes"] == 30
    assert config["warehouse"]["lead_days"] + config["warehouse"]["split_receipt_delay_days"] == 7
