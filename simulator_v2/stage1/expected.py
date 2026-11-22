"""Independent hand-counted fixture expectations, including the quiet dates."""

from datetime import date

from .fixture import A, B, H, R, END, START, animal_id
from .model import AnimalStatus
from .soh import YARD
from .validation import Check

# Opening, receipts, sales, deaths, closing, animal-days. Dates absent here have no movements.
YARD_DAYS = {
    "2023-12-31": (2, 3, 1, 0, 4, 5),
    "2024-01-01": (4, 3, 0, 1, 6, 7),
    "2024-01-31": (6, 0, 2, 1, 3, 6),
    "2024-02-29": (3, 3, 1, 0, 5, 6),
    "2024-03-10": (5, 1, 1, 0, 5, 6),
}
YARD_MONTHS = {
    "2023-12-31": (2, 3, 1, 0, 4, 5),
    "2024-01-31": (4, 3, 2, 2, 3, 187),
    "2024-02-29": (3, 3, 1, 0, 5, 90),
    "2024-03-11": (5, 1, 1, 0, 5, 56),
}
# Closing counts in Pen A, Pen B, receiving, hospital, and lots 1–3.
CLOSING_BY_PERIOD = {
    "2023-12-31": (1, 2, 0, 1, 3, 1, 0),
    "2024-01-01": (3, 3, 0, 0, 3, 3, 0),
    "2024-01-31": (1, 2, 0, 0, 2, 1, 0),
    "2024-02-29": (3, 2, 0, 0, 2, 1, 2),
    "2024-03-10": (3, 2, 0, 0, 2, 1, 2),
}
# Transfers in/out for each physical location, in A, B, receiving, hospital order.
TRANSFERS = {
    "2023-12-31": ((1, 2), (3, 0), (0, 3), (1, 0)),
    "2024-01-01": ((2, 0), (2, 0), (0, 3), (0, 1)),
    "2024-02-29": ((2, 0), (1, 0), (0, 3), (0, 0)),
    "2024-03-10": ((0, 0), (2, 1), (0, 1), (1, 1)),
}
DECEMBER = {
    "original": ((3, 0, 0, 1), ((2, 1), (1, 0), (0, 3), (1, 0))),
    "late": ((2, 1, 0, 1), ((2, 2), (2, 0), (0, 3), (1, 0))),
    "revised": ((1, 2, 0, 1), ((1, 2), (3, 0), (0, 3), (1, 0))),
}
LOCATIONS = A, B, R, H
SCOPES = (*LOCATIONS, "SYN-LOT-1", "SYN-LOT-2", "SYN-LOT-3")


def yard_counts(row):
    return row.opening_head, row.receipts, row.sales, row.deaths, row.closing_head, row.animal_days


def combine_checks(check_id, scope, comparisons):
    bad = [(key, expected, actual) for key, expected, actual in comparisons if expected != actual]
    return Check(check_id, scope, "independent hand counts", bad[:10] if bad else "matched",
                 len(bad), tuple(key for key, _, _ in bad[:10]))


def december_checks(daily, version):
    rows = {row.scope_id: row for row in daily}
    closing, flows = DECEMBER[version]
    return (combine_checks("MANUAL_DECEMBER", version, [
        (YARD[1], YARD_DAYS["2023-12-31"], yard_counts(rows[YARD[1]])),
        *((key, (head, *transfer),
           (rows[key].closing_head, rows[key].transfers_in, rows[key].transfers_out))
          for key, head, transfer in zip(LOCATIONS, closing, flows, strict=True)),
    ]),)


def fixture_checks(result, daily, monthly):
    days = {(row.period_end.isoformat(), row.scope_id): row for row in daily}
    expected_opening = (2, 0, 0, 0, 2, 0, 0)
    comparisons = []
    for ordinal in range(START.toordinal(), END.toordinal() + 1):
        day = date.fromordinal(ordinal).isoformat()
        expected_closing = CLOSING_BY_PERIOD.get(day, expected_opening)
        opening = sum(expected_opening[:4])
        comparisons.append((f"{day}/{YARD[1]}", YARD_DAYS.get(day, (opening, 0, 0, 0, opening, opening)),
                            yard_counts(days[day, YARD[1]])))
        for key, start, end in zip(SCOPES, expected_opening, expected_closing, strict=True):
            row = days[day, key]
            comparisons.append((f"{day}/{key}", (start, end), (row.opening_head, row.closing_head)))
        for key, flow in zip(LOCATIONS, TRANSFERS.get(day, ((0, 0),) * 4), strict=True):
            row = days[day, key]
            comparisons.append((f"{day}/{key}/transfer", flow, (row.transfers_in, row.transfers_out)))
        expected_opening = expected_closing
    monthly_comparisons = []
    for row in monthly:
        if row.scope_type == "yard":
            day = row.period_end.isoformat()
            monthly_comparisons.append((day, YARD_MONTHS[day], yard_counts(row)))
    manual_active = {animal_id(n): location for n, location in ((2, A), (3, B), (9, A), (10, B), (11, A))}
    return (
        combine_checks("MANUAL_DAILY", "fixture", comparisons),
        combine_checks("MANUAL_MONTHLY", "fixture", monthly_comparisons),
        combine_checks("MANUAL_FINAL_STATE", "fixture", [
            ("active", manual_active, {row.animal_id: row.location_id for row in result.states
                                      if row.status == AnimalStatus.ACTIVE}),
            ("sold", [animal_id(n) for n in (4, 5, 6, 7, 12)],
             [row.animal_id for row in result.states if row.status == AnimalStatus.SOLD]),
            ("dead", [animal_id(n) for n in (1, 8)],
             [row.animal_id for row in result.states if row.status == AnimalStatus.DEAD]),
        ]),
    )
