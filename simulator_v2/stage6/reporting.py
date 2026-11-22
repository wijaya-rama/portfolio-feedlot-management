"""Keep period-end stock and the final simulation roster explicit."""

from ..stage1.model import AnimalStatus


def stock_reporting(monthly, final_statuses):
    periods = [row for row in monthly if row.scope_type == "yard"]
    final = sum(status == AnimalStatus.ACTIVE for status in final_statuses)
    if not periods or periods[-1].closing_head != final:
        raise ValueError("final simulation SOH differs from the final period-end SOH")
    for row in periods:
        if row.opening_head + row.receipts - row.sales - row.deaths != row.closing_head:
            raise ValueError(f"SOH does not reconcile for {row.period_end}")
    for earlier, later in zip(periods, periods[1:]):
        if earlier.closing_head != later.opening_head or earlier.period_end >= later.period_start:
            raise ValueError(f"SOH periods overlap or do not roll forward at {later.period_start}")
    return {
        "final_simulation_date": periods[-1].period_end,
        "final_simulation_soh": final,
        "periods": [{"period_start": row.period_start, "period_end": row.period_end,
                     "period_end_soh": row.closing_head} for row in periods],
    }
