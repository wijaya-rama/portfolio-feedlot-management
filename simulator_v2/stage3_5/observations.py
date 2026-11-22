"""Sample latent weight and publish a separate, availability-gated document stream."""

from dataclasses import dataclass
from datetime import date, datetime

from ..stage1.fixture import local
from ..stage1.model import EventKind, business_date
from ..stage1.snapshots import RevisionApproval
from ..stage2.observations import Kind, Observations, WeighPlan, correct, simulate_observations


@dataclass(frozen=True)
class ScaleSample:
    observation_id: str
    animal_id: str
    effective_at: datetime
    observed_at: datetime
    business_date: date
    physical_snapshot_id: str
    latent_kg: float
    scale_bias_kg: float
    measurement_error_kg: float
    shrink_kg: float
    precision_kg: float


@dataclass(frozen=True)
class ScaleCancellation:
    source_id: str
    animal_id: str
    scheduled_at: datetime
    exit_event_id: str
    reason: str


@dataclass(frozen=True)
class ScaleRevision:
    observation_id: str
    parent_observation_id: str
    approval_id: str
    effective_at: datetime
    restated_origin_at: datetime
    knowledge_cutoff: datetime


def added_plans(scenario):
    for row in scenario["extra_weighing_plans"]:
        observed, posted, available = (local(row[key]) for key in (
            "observed_local", "posted_local", "available_local"))
        yield WeighPlan(row["source_id"], row["animal_id"], Kind(row["kind"]), observed,
                        posted - observed, available - posted, row["missing_probability"])


class ScaleBook:
    def __init__(self, timeline, biology, plans, config, corrections):
        self.timeline, self.biology, self.config = timeline, biology, config
        plans = tuple(sorted(plans, key=lambda row: (row.measured_at, row.source_id)))
        plan_ids = {row.source_id for row in plans}
        correction_ids = {row["source_id"] for row in corrections}
        if len(plan_ids) != len(plans) or len(correction_ids) != len(corrections) or plan_ids & correction_ids:
            raise ValueError("weighing source IDs must be unique")
        if any(not row["source_id"].startswith("SYN-") or row["parent_source_id"] not in plan_ids
               for row in corrections):
            raise ValueError("scale correction must reference a planned synthetic source")
        self.plans = iter(plans)
        self.pending = next(self.plans, None)
        self.corrections = {row["parent_source_id"]: row for row in corrections}
        if len(self.corrections) != len(corrections):
            raise ValueError("only one source correction per scheduled ticket is supported by this fixture")
        self.samples, self.attempts, self.records = [], [], []
        self.cancellations, self.revisions, self.approvals = [], [], []
        self.public = []
        self.unpublished = []

    def _sample(self, plan, observation_id, latent, bias, noise, precision):
        self.samples.append(ScaleSample(
            observation_id, plan.animal_id, plan.measured_at, plan.measured_at,
            business_date(plan.measured_at), self.timeline.snapshot_id,
            latent, bias, noise, 0.0, precision))

    def _append(self, record):
        self.records.append(record)
        self.unpublished.append(record)

    def _correct(self, record, settings):
        posted, available = (local(settings[key]) for key in ("posted_local", "available_local"))
        origin = local(settings["restated_origin_local"])
        approval = RevisionApproval(settings["approval_id"], settings["approved_by"], available,
                                    settings["reason"])
        if (not approval.approval_id.startswith("SYN-") or not approval.approved_by.startswith("SYN-")
                or not approval.reason.strip() or not record.available_at <= origin < available
                or not record.available_at <= posted <= available):
            raise ValueError("scale revision requires a later authorized vintage")
        correction = correct(
            record, source_id=settings["source_id"], posted_at=posted, available_at=available,
            measured_weight_kg=round(record.measured_weight_kg + settings["adjustment_kg"], 6))
        self._append(correction)
        self.approvals.append(approval)
        self.revisions.append(ScaleRevision(correction.observation_id, record.observation_id,
                                            approval.approval_id, record.measured_at, origin, available))

    def observe_through(self, instant):
        while self.pending is not None and self.pending.measured_at <= instant:
            plan = self.pending
            self.pending = next(self.plans, None)
            exit_event = self.timeline.exits.get(plan.animal_id)
            terminal_at_exit = (plan.kind == Kind.FINAL_SALE and exit_event is not None
                                and exit_event.kind == EventKind.SALE
                                and plan.measured_at == exit_event.effective_at)
            if exit_event and plan.measured_at >= exit_event.effective_at and not terminal_at_exit:
                self.cancellations.append(ScaleCancellation(plan.source_id, plan.animal_id,
                                                            plan.measured_at, exit_event.event_id,
                                                            str(exit_event.kind)))
                continue
            attempts, records = simulate_observations(
                self.timeline, self.biology, (plan,), self.config, on_sample=self._sample)
            self.attempts.extend(attempts)
            for record in records:
                self._append(record)
                correction = self.corrections.get(record.source_event_id)
                if correction:
                    self._correct(record, correction)

    def as_of(self, cutoff):
        ready = [row for row in self.unpublished if row.available_at <= cutoff]
        self.public.extend(ready)
        self.unpublished = [row for row in self.unpublished if row.available_at > cutoff]
        return Observations(self.timeline, self.public, self.config)

    def finish(self):
        if self.pending is not None:
            raise ValueError("weighing plan beyond the scenario horizon")
        if len(self.revisions) != len(self.corrections):
            raise ValueError("authorized scale correction references an unmeasured ticket")
        return Observations(self.timeline, self.records, self.config)
