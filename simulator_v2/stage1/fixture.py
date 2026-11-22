"""Fixed synthetic movement schedule with a seed-specific RFID stream."""

from datetime import date, datetime

from .ledger import Ledger
from .model import EDMONTON, UTC, Animal, AnimalEvent, EventKind, LocationKind, LocationVersion, Lot
from .model import RunConfig, Source
from .provenance import canonical, sha256, stable_id

START = date(2023, 12, 31)
END = date(2024, 3, 11)
A, B, R, H = "SYN-PEN-A", "SYN-PEN-B", "SYN-RECEIVING", "SYN-HOSPITAL"


def local(text, *, fold=0):
    return datetime.fromisoformat(text).replace(tzinfo=EDMONTON, fold=fold).astimezone(UTC)


ORIGINAL_CUTOFF = local("2024-01-01 00:00")
LATE_CUTOFF = local("2024-01-02 08:00")
REVISED_CUTOFF = local("2024-01-04 10:00")
FINAL_CUTOFF = local("2024-03-12 00:00")


def animal_id(number):
    return f"SYN-A{number:02d}"


def fixture(seed=42):
    config = RunConfig("12-cattle", seed, START, END)
    registered = local("2023-12-30 00:00")
    receipts = [("2023-12-30 21:00", [1, 2]), ("2023-12-31 08:00", [3, 4, 5]),
                ("2024-01-01 08:00", [6, 7, 8]), ("2024-02-29 09:00", [9, 10, 11]),
                ("2024-03-10 00:00", [12])]
    lot_ids = (1, 1, 1, 1, 2, 2, 2, 3, 3, 3, 2, 3)
    lots = [Lot(f"SYN-LOT-{i}", f"SYN-SUPPLIER-{i}", "finishing",
                registered, registered, registered) for i in (1, 2, 3)]
    rfid_base = int(sha256(canonical([seed, "fixture-rfid"]))[:16], 16) % (10**12 - 12)
    animals = [Animal(animal_id(n), f"SYN-LOT-{lot_ids[n - 1]}", f"000{rfid_base + n:012d}",
                      local(when), local(when), local(when))
               for when, numbers in receipts for n in numbers]
    versions = [LocationVersion(f"{key}-V1", key, kind, cap, registered, registered, registered)
                for key, kind, cap in (
                    (A, LocationKind.PRODUCTION, 5), (B, LocationKind.PRODUCTION, 4),
                    (R, LocationKind.RECEIVING, 3), (H, LocationKind.HOSPITAL, 1))]
    reduced = local("2024-02-29 00:00")
    versions.append(LocationVersion(f"{B}-V2", B, LocationKind.PRODUCTION, 3,
                                    reduced, reduced, reduced))
    ledger = Ledger(config, lots, animals, versions)
    events = []

    def record(document, when, kind, animal, source=None, target=None, *,
               posted=None, available=None, supersedes=None, reason=None):
        effective = local(when)
        posted_at = local(posted) if posted else effective
        available_at = local(available) if available else posted_at
        row = Source("SYN-FIXTURE", f"SYN-{document}", animal_id(animal))
        event = AnimalEvent(stable_id("EVENT", [config.scenario, row]), animal_id(animal), kind,
                            effective, posted_at, available_at,
                            supersedes.sequence if supersedes else len(events) + 1, row,
                            source, target, supersedes.event_id if supersedes else None, reason)
        events.append(event)
        return event

    for when, numbers in receipts:
        opening = numbers[0] == 1
        for n in numbers:
            record("OPEN-2023" if opening else f"RECEIPT-{when[:10]}", when,
                   EventKind.OPENING if opening else EventKind.RECEIPT, n, target=A if opening else R)

    record("PLACE-DEC", "2023-12-31 09:00", EventKind.TRANSFER, 4, R, B)
    dec_original = record("PLACE-DEC", "2023-12-31 09:00", EventKind.TRANSFER, 3, R, A)
    record("PLACE-DEC", "2023-12-31 09:00", EventKind.TRANSFER, 5, R, A)
    record("HOSP-DEC", "2023-12-31 10:00", EventKind.TRANSFER, 2, A, H)
    record("LATE-DEC", "2023-12-31 15:00", EventKind.TRANSFER, 5, A, B,
           posted="2024-01-01 08:00", available="2024-01-02 08:00")
    record("SALE-DEC", "2023-12-31 18:00", EventKind.SALE, 4, B)

    record("RETURN-JAN", "2024-01-01 07:00", EventKind.TRANSFER, 2, H, A)
    record("PLACE-JAN", "2024-01-01 09:00", EventKind.TRANSFER, 6, R, A)
    record("PLACE-JAN", "2024-01-01 09:00", EventKind.TRANSFER, 7, R, B)
    record("PLACE-JAN", "2024-01-01 09:00", EventKind.TRANSFER, 8, R, B)
    jan_void = record("MOVE-JAN", "2024-01-01 16:00", EventKind.TRANSFER, 1, A, B)
    record("DEATH-JAN1", "2024-01-01 15:00", EventKind.DEATH, 8, B, reason="UNKNOWN")
    record("FIX-DEC", "2023-12-31 09:00", EventKind.TRANSFER, 3, R, B,
           posted="2024-01-03 10:00", available="2024-01-04 10:00",
           supersedes=dec_original, reason="WRONG_DESTINATION")
    record("VOID-JAN", "2024-01-01 16:00", EventKind.REVERSAL, 1,
           posted="2024-01-04 12:00", available="2024-01-05 08:00",
           supersedes=jan_void, reason="MOVEMENT_DID_NOT_OCCUR")
    record("SALE-JAN", "2024-01-31 11:00", EventKind.SALE, 5, B)
    record("SALE-JAN", "2024-01-31 11:00", EventKind.SALE, 6, A)
    record("DEATH-JAN31", "2024-01-31 16:00", EventKind.DEATH, 1, A, reason="UNKNOWN")

    for n, target in ((9, A), (10, B), (11, A)):
        record("PLACE-FEB", "2024-02-29 10:00", EventKind.TRANSFER, n, R, target)
    record("SALE-FEB", "2024-02-29 16:00", EventKind.SALE, 7, B)

    record("PLACE-MAR", "2024-03-10 01:55", EventKind.TRANSFER, 12, R, B)
    record("HOSP-MAR", "2024-03-10 03:05", EventKind.TRANSFER, 10, B, H)
    record("RETURN-MAR", "2024-03-10 20:00", EventKind.TRANSFER, 10, H, B)
    record("SALE-MAR", "2024-03-10 22:00", EventKind.SALE, 12, B)
    ledger.ingest(reversed(events))
    return ledger
