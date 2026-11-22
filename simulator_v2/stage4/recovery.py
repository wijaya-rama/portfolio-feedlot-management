"""Source-lot recoverable feed control and authorized disposition."""

from dataclasses import dataclass
from datetime import datetime

from ..stage1.model import is_utc
from ..stage3.units import half_up
from .ledger import Account, Action


@dataclass(frozen=True)
class RecoveryLot:
    lot_id: str
    delivery_id: str
    bunk_ticket_id: str
    settlement_id: str
    location_id: str
    available_at: datetime
    g_af: int
    g_dm: int
    provisional_cents: int
    invoice_cents: int


@dataclass(frozen=True)
class Disposition:
    document_id: str
    lot_id: str
    source_id: str
    approval_id: str
    effective_at: datetime
    g_af: int
    next_delivery_id: str | None = None


def dispose(lot, document, *, prior_g_af=0, prior_cents=0):
    """Price an approved reuse or disposal at the remaining lot carrying value."""
    available = lot.g_af - prior_g_af
    cents = lot.provisional_cents + lot.invoice_cents - prior_cents
    if (document.lot_id != lot.lot_id or type(document.g_af) is not int
            or type(prior_g_af) is not int or type(prior_cents) is not int
            or min(prior_g_af, prior_cents, cents) < 0
            or not 0 < document.g_af <= available or not document.approval_id
            or not is_utc(document.effective_at) or document.effective_at < lot.available_at
            or document.next_delivery_id == lot.delivery_id):
        raise ValueError("invalid recoverable feed disposition")
    amount = half_up(cents * document.g_af, available)
    reuse = document.next_delivery_id is not None
    return Action(document.document_id, document.source_id, document.effective_at,
                  "refusal_reuse" if reuse else "refusal_disposal",
                  Account.DISTRIBUTION if reuse else Account.OTHER_VARIANCE,
                  Account.RECOVERY, amount, location_id=lot.location_id,
                  pool_id=document.next_delivery_id if reuse else lot.delivery_id,
                  approval_id=document.approval_id)
