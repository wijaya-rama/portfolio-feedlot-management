"""Conditional closeout scenarios built from the audited all-outcome ledger."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .closeout_economics import COST_CENTS, price_break_even
from .contracts import COSTS, FINISHED, MORTALITY
from .feed_growth import load_analysis
from .metrics import CLOSEOUT_METRICS, aggregate_closeout, apply_metrics
from .relations import cents, require_key, safe_ratio
from .scenario_config import FEED_COMPONENTS, PHASES, AdditionalSurvivors, PriceShocks, Scenario, number

COHORTS = ("origin_region", "placement_quarter")
COUNTS = ("head_placed", "head_sold", "head_mortality", "head_hcw_eligible")
BASELINE_CENTS = (*COST_CENTS, "gross_revenue_cents", "production_cost_cents",
                  "all_outcome_margin_cents", "mortality_loss_cents")
DELIVERY_COSTS = [f"{name}_cost_cad" for name in FEED_COMPONENTS]
OUTCOME_MONEY = ("revenue_delta_cad", "feed_delta_cad", "yardage_delta_cad",
                 "vet_delta_cad", "other_delta_cad")
OUTCOME_ADDITIVE = (*OUTCOME_MONEY, "sold_head_delta", "hcw_eligible_head_delta", "hcw_delta_kg")
BRIDGE_COLUMNS = (
    "animal_id", "lot_id", "original_outcome", "scenario_outcome",
    *[f"booked_{cost}" for cost in COSTS], "booked_gross_revenue_cad", "booked_death_burden_cad",
    "extra_financial_days", "conditional_finish_live_kg", "conditional_dressing_fraction",
    "conditional_price_cad_per_hcw_kg", *OUTCOME_ADDITIVE,
    "incremental_margin_cad",
)
ADDITIVE = (
    *COUNTS, "placement_weight_kg", "hcw_kg", "booked_hcw_kg", "booked_head_sold",
    "booked_head_mortality", "booked_eligible_head", "booked_revenue_cad", "booked_total_cost_cad",
    "booked_margin_cad", "booked_mortality_burden_cad", *COSTS, "other_incremental_cost_cad",
    "revenue_cad", "total_cost_cad", "margin_cad", "margin_change_cad",
    "purchase_price_cost_change_cad", "feed_price_cost_change_cad", "carcass_price_revenue_change_cad",
    "operational_margin_change_cad",
)


def _feed_exposure(delivery, bridge):
    """Trace phase and ingredient weights from native lot–pen–day deliveries to booked lot costs."""
    require_key(delivery, ("lot_id", "pen_id", "feed_date"), "daily feed delivery")
    require_key(bridge, ("lot_id",), "lot feed reconciliation")
    if (not bridge.within_rounding_bound.all() or
            not delivery.ration_phase.isin(PHASES).all()):
        raise ValueError("Feed scenario requires reconciled lots and recognized phases")
    delivered = delivery.assign(delivered_cents=cents(delivery.delivered_feed_cost_cad))
    by_lot = delivered.groupby("lot_id").delivered_cents.sum().sort_index()
    canonical = cents(bridge.set_index("lot_id").delivered_feed_cost_cad).sort_index()
    if not by_lot.equals(canonical):
        raise ValueError("Daily feed cost must reconcile to the delivered lot ledger")

    # Daily component splits absorb component-display rounding before lot–phase rollup.
    components = delivery[DELIVERY_COSTS]
    component_total = components.sum(axis=1)
    if (components.isna().any(axis=None) or components.lt(0).any(axis=None)
            or ((component_total - delivery.delivered_feed_cost_cad).abs() > .010001).any()):
        raise ValueError("Ingredient costs must reconcile to the daily delivered cost")
    weights = components.div(component_total.where(component_total.gt(0)), axis=0).fillna(0)
    attributed = weights.mul(delivery.delivered_feed_cost_cad, axis=0)
    by_phase = (delivery[["lot_id", "ration_phase"]].join(attributed)
                .groupby(["lot_id", "ration_phase"])[DELIVERY_COSTS].sum())
    if not np.allclose(by_phase.groupby(level="lot_id").sum().sum(axis=1),
                       by_lot / 100, rtol=0, atol=1e-8):
        raise ValueError("Ration-phase components must retain total delivered cost by lot")
    detail = by_phase.rename(columns=dict(zip(DELIVERY_COSTS, FEED_COMPONENTS, strict=True)))
    detail = detail.reset_index().melt(id_vars=["lot_id", "ration_phase"], var_name="component",
                                      value_name="delivery_attributed_cost_cad")
    booked = bridge.set_index("lot_id").allocated_feed_cost_cad
    scale = safe_ratio(booked, by_lot / 100)
    if scale.isna().any():
        raise ValueError("A reconciled feed lot requires positive delivery expense")
    detail["booked_feed_exposure_cad"] = detail.delivery_attributed_cost_cad * detail.lot_id.map(scale)
    if not np.allclose(detail.groupby("lot_id").booked_feed_exposure_cad.sum(),
                       booked.sort_index(), rtol=0, atol=1e-8):
        raise ValueError("Ration-phase exposure must reproduce the booked allocation per lot")
    return detail.sort_values(["lot_id", "ration_phase", "component"], ignore_index=True)


def _candidates(animals, outcome):
    # Spread integer scenarios across lots by systematic fractional rank of the original outcome pool.
    pool = animals.loc[animals.exit_type.eq(outcome)].sort_values(["lot_id", "animal_id"]).copy()
    groups = pool.groupby("lot_id").animal_id
    priority = (groups.cumcount() + .5) / groups.transform("size")
    return pool.assign(priority=priority).sort_values(["priority", "lot_id", "animal_id"])


def _outcome_bridge(pool, change, prices, lot_feed_multiplier):
    if change.head > len(pool):
        raise ValueError(f"mortality.head exceeds eligible outcomes ({len(pool)})")
    rows = pool.head(change.head)
    result = rows[["animal_id", "lot_id"]].assign(
        original_outcome=rows.exit_type,
        **{f"booked_{column}": rows[column] for column in (*COSTS, "gross_revenue_cad")},
        extra_financial_days=np.nan, conditional_finish_live_kg=np.nan,
        conditional_dressing_fraction=np.nan, conditional_price_cad_per_hcw_kg=np.nan,
        vet_delta_cad=change.vet_cad_per_head, other_delta_cad=change.other_cad_per_head,
    )
    feed_multiplier = rows.lot_id.map(lot_feed_multiplier)
    if isinstance(change, AdditionalSurvivors):
        extra_days = change.finish_financial_dof - rows.financial_dof
        if extra_days.le(0).any() or rows.entry_weight_kg.gt(change.finish_live_kg).any():
            raise ValueError("A hypothetical survivor must finish after its recorded death DOF "
                             "and at or above its entry weight")
        hcw = change.finish_live_kg * change.dressing_fraction
        revenue = prices.reprice_carcass(hcw * change.price_cad_per_hcw_kg, hcw)
        if revenue < 0:
            raise ValueError("The shocked hypothetical survivor price must be nonnegative")
        result = result.assign(
            scenario_outcome=FINISHED, booked_death_burden_cad=rows.production_cost_cad,
            extra_financial_days=extra_days, conditional_finish_live_kg=change.finish_live_kg,
            conditional_dressing_fraction=change.dressing_fraction,
            conditional_price_cad_per_hcw_kg=revenue / hcw,
            sold_head_delta=1, hcw_eligible_head_delta=1, hcw_delta_kg=hcw, revenue_delta_cad=revenue,
            feed_delta_cad=extra_days * change.feed_cad_per_extra_day * feed_multiplier,
            yardage_delta_cad=extra_days * change.yardage_cad_per_extra_day,
        )
    else:
        eligible = rows.hot_carcass_weight_kg.gt(0)
        hcw = rows.hot_carcass_weight_kg.where(eligible, 0)
        repriced = prices.reprice_carcass(rows.gross_revenue_cad, hcw).where(eligible, rows.gross_revenue_cad)
        result = result.assign(
            scenario_outcome=MORTALITY, booked_death_burden_cad=0,
            sold_head_delta=-1, hcw_eligible_head_delta=-eligible.astype(int), hcw_delta_kg=-hcw,
            revenue_delta_cad=-repriced,
            feed_delta_cad=-rows.allocated_feed_cost_cad * feed_multiplier * change.avoidable_feed_fraction,
            yardage_delta_cad=-rows.yardage_cost_cad * change.avoidable_yardage_fraction,
        )
    result["incremental_margin_cad"] = result.revenue_delta_cad - result[list(OUTCOME_MONEY[1:])].sum(axis=1)
    return result[list(BRIDGE_COLUMNS)].reset_index(drop=True)


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    lots: pd.DataFrame
    mortality_bridge: pd.DataFrame

    def select(self, lot_ids):
        """Slice complete lots after fixing the portfolio's hypothetical outcome assignments."""
        if isinstance(lot_ids, str):
            raise ValueError("lot_ids must be a collection of complete lot IDs")
        lot_ids = pd.Index(list(lot_ids)).unique()
        if not len(lot_ids) or not lot_ids.isin(self.lots.lot_id).all():
            raise ValueError("Select at least one known, complete lot")
        lots = self.lots.loc[self.lots.lot_id.isin(lot_ids)].reset_index(drop=True)
        bridge = self.mortality_bridge.loc[self.mortality_bridge.lot_id.isin(lot_ids)].reset_index(drop=True)
        return ScenarioResult(self.scenario, lots, bridge)

    def summarize(self, *, by=()):
        """Pool additive values and recompute CAD per placed head and share of loss-making lots."""
        by = tuple(by)
        if set(by) - set(COHORTS) or len(by) != len(set(by)):
            raise ValueError(f"Group by unique cohort columns from {COHORTS}")
        data = self.lots.assign(lots=1, loss_making_lots=self.lots.margin_cad.round(2).lt(0).astype(int))
        columns = [*ADDITIVE, "lots", "loss_making_lots"]
        totals = (data.groupby(list(by), dropna=False, as_index=False)[columns].sum()
                  if by else pd.DataFrame([data[columns].sum()]).astype(data[columns].dtypes))
        for column in (*COUNTS, "booked_head_sold", "booked_head_mortality", "booked_eligible_head",
                       "lots", "loss_making_lots"):
            totals[column] = totals[column].astype(int)
        return totals.assign(
            scenario=self.scenario.name, classification=self.scenario.kind,
            assumptions=[self.scenario.assumptions() for _ in range(len(totals))],
            limitations=self.scenario.limitations,
            margin_cad_per_head_placed=safe_ratio(totals.margin_cad, totals.head_placed),
            loss_making_lot_share=safe_ratio(totals.loss_making_lots, totals.lots),
            mortality_fraction=safe_ratio(totals.head_mortality, totals.head_placed),
        )


class ScenarioEngine:
    """Replay a scenario against a validated build and its native delivery rows."""

    @classmethod
    def from_repository(cls, root: Path):
        """Build with the archived weather and verify the existing 661 controls and source hashes."""
        build, delivery = load_analysis(root)
        return cls(build, delivery)

    def __init__(self, build, delivery):
        tables = build.tables
        animals = tables["animal_closeout"]
        health = tables["animal_health_summary"]
        self._overall = aggregate_closeout(animals, health)
        self._baseline = aggregate_closeout(animals, health, by=("lot_id", *COHORTS))
        require_key(self._baseline, ("lot_id",), "scenario lots")
        if (self._baseline.head_placed.ne(self._baseline.head_sold + self._baseline.head_mortality).any()
                or animals.entry_weight_kg.isna().any() or animals.entry_weight_kg.le(0).any()
                or not self._baseline.gross_revenue_cents.sub(self._baseline.production_cost_cents)
                .eq(self._baseline.all_outcome_margin_cents).all()):
            raise ValueError("Scenario baseline requires closed lots, entry kg and a balanced booked ledger")
        self._feed = _feed_exposure(delivery, tables["lot_feed_reconciliation"])
        booked_feed = self._baseline.set_index("lot_id").allocated_feed_cost_cents.sort_index()
        allocated = cents(tables["lot_feed_reconciliation"].set_index("lot_id")
                          .allocated_feed_cost_cad).sort_index()
        if not booked_feed.equals(allocated):
            raise ValueError("Feed bridge must match the booked animal allocation")
        self._sold = _candidates(animals, FINISHED)
        self._deaths = _candidates(animals, MORTALITY)
        if self._deaths.gross_revenue_cad.ne(0).any():
            raise ValueError("The mortality bridge requires zero booked sale revenue on deaths")
        self._min_purchase_basis = (animals.purchase_cost_cad / animals.entry_weight_kg).min()
        eligible = self._sold.loc[self._sold.hot_carcass_weight_kg.gt(0)]
        self._min_carcass_price = (eligible.gross_revenue_cad / eligible.hot_carcass_weight_kg).min()

    def feed_cost_detail(self, prices=PriceShocks()):
        """Return allocated exposure by lot, ration phase and ingredient, with both cost bases."""
        detail = self._feed.copy()
        phase = detail.ration_phase.map(dict(prices.feed_phase_fractions)).fillna(0)
        component = detail.component.map(dict(prices.feed_component_fractions)).fillna(0)
        multiplier = (1 + prices.feed_fraction) * (1 + phase) * (1 + component)
        detail["feed_cost_change_cad"] = detail.booked_feed_exposure_cad * (multiplier - 1)
        detail["scenario_feed_exposure_cad"] = detail.booked_feed_exposure_cad + detail.feed_cost_change_cad
        return detail

    def _feed_cost_delta(self, prices):
        base = self._baseline
        if not (any(prices.feed_phase_fractions.values()) or any(prices.feed_component_fractions.values())):
            return base.allocated_feed_cost_cents / 100 * prices.feed_fraction
        costs = self.feed_cost_detail(prices).groupby("lot_id").feed_cost_change_cad.sum()
        return base.lot_id.map(costs)

    def evaluate(self, scenario):
        """Reprice the original ledger first, then apply conditional changes to outcomes."""
        base, prices = self._baseline, scenario.prices
        if prices.purchase_cad_per_live_kg < -self._min_purchase_basis:
            raise ValueError("purchase_cad_per_live_kg would make an individual purchase basis negative")
        if prices.carcass_cad_per_hcw_kg < -self._min_carcass_price:
            raise ValueError("carcass_cad_per_hcw_kg would make an eligible sale price negative")
        ledger = base[["lot_id", *COHORTS, *COUNTS, "placement_weight_kg", "hcw_kg"]].copy()
        ledger[["booked_head_sold", "booked_head_mortality", "booked_eligible_head", "booked_hcw_kg"]] = (
            base[["head_sold", "head_mortality", "head_hcw_eligible", "hcw_kg"]]
        )
        ledger[[*COSTS, "booked_revenue_cad", "booked_total_cost_cad",
                "booked_margin_cad", "booked_mortality_burden_cad"]] = base[list(BASELINE_CENTS)] / 100
        purchase_delta = prices.purchase_cad_per_live_kg * base.placement_weight_kg
        feed_delta = self._feed_cost_delta(prices)
        carcass_delta = (prices.carcass_fraction * base.hcw_eligible_revenue_cents / 100
                         + prices.carcass_cad_per_hcw_kg * base.hcw_kg)
        ledger["purchase_price_cost_change_cad"] = purchase_delta
        ledger["feed_price_cost_change_cad"] = feed_delta
        ledger["carcass_price_revenue_change_cad"] = carcass_delta
        ledger["purchase_cost_cad"] += purchase_delta
        ledger["allocated_feed_cost_cad"] += feed_delta
        ledger["revenue_cad"] = ledger.booked_revenue_cad + carcass_delta
        ledger["other_incremental_cost_cad"] = 0.0
        operational_cost_delta = 0.0
        ledger["operational_margin_change_cad"] = 0.0
        bridge = pd.DataFrame(columns=list(BRIDGE_COLUMNS))

        change = scenario.mortality
        if change is not None:
            pool = self._deaths if isinstance(change, AdditionalSurvivors) else self._sold
            feed_multiplier = pd.Series(1 + feed_delta / (base.allocated_feed_cost_cents / 100))
            feed_multiplier.index = base.lot_id
            bridge = _outcome_bridge(pool, change, prices, feed_multiplier)
            deltas = bridge.groupby("lot_id")[list(OUTCOME_ADDITIVE)].sum()
            deltas = deltas.reindex(base.lot_id, fill_value=0).set_axis(base.index)
            ledger["head_sold"] += deltas.sold_head_delta
            ledger["head_mortality"] -= deltas.sold_head_delta
            ledger["head_hcw_eligible"] += deltas.hcw_eligible_head_delta
            ledger["hcw_kg"] += deltas.hcw_delta_kg
            ledger["revenue_cad"] += deltas.revenue_delta_cad
            ledger["allocated_feed_cost_cad"] += deltas.feed_delta_cad
            ledger["yardage_cost_cad"] += deltas.yardage_delta_cad
            ledger["vet_cost_cad"] += deltas.vet_delta_cad
            ledger["other_incremental_cost_cad"] = deltas.other_delta_cad.astype(float)
            operational_cost_delta = deltas[list(OUTCOME_MONEY[1:])].sum(axis=1)
            ledger["operational_margin_change_cad"] = deltas.revenue_delta_cad - operational_cost_delta

        # Add scenario deltas to exact source-cent totals and avoid rounding hypothetical transactions.
        ledger["total_cost_cad"] = ledger.booked_total_cost_cad + purchase_delta + feed_delta + operational_cost_delta
        ledger["margin_change_cad"] = (carcass_delta - purchase_delta - feed_delta
                                       + ledger.operational_margin_change_cad)
        ledger["margin_cad"] = ledger.booked_margin_cad + ledger.margin_change_cad
        if not np.isfinite(ledger[list(ADDITIVE)].to_numpy(dtype=float)).all():
            raise ValueError("Scenario assumptions produce non-finite results")
        ledger["margin_cad_per_head_placed"] = safe_ratio(ledger.margin_cad, ledger.head_placed)
        return ScenarioResult(scenario, ledger, bridge)

    def break_even(self, *, by=()):
        """Published conditional thresholds and one-at-a-time margin-eliminating shocks."""
        by = tuple(by)
        if by == ("lot_id",):
            totals = self._baseline.set_index(["lot_id", *COHORTS])
        elif not by:
            totals = self._overall
        elif set(by) <= set(COHORTS) and len(by) == len(set(by)):
            totals = apply_metrics(self._baseline.groupby(list(by)).sum(numeric_only=True),
                                   CLOSEOUT_METRICS)
        else:
            raise ValueError("Break-even groups must be lot_id or procurement cohort columns")
        margin = totals.all_outcome_margin_cents
        return price_break_even(totals).assign(
            booked_margin_cad=margin / 100,
            feed_fraction_at_break_even=safe_ratio(margin, totals.allocated_feed_cost_cents),
            carcass_fraction_at_break_even=safe_ratio(-margin, totals.hcw_eligible_revenue_cents),
            feed_margin_change_cad_per_1pct=-totals.allocated_feed_cost_cents / 10_000,
            carcass_margin_change_cad_per_1pct=totals.hcw_eligible_revenue_cents / 10_000,
        )

    def break_even_frontier(self, purchase_changes, *, feed_fraction=0):
        """Signed CAD/HCW kg shock required at each CAD/live kg offset and fixed feed fraction."""
        prices = PriceShocks(feed_fraction=feed_fraction)
        base = self._overall.iloc[0]
        records = []
        for purchase in purchase_changes:
            number("purchase change", purchase, minimum=-self._min_purchase_basis)
            carcass = ((purchase * base.placement_weight_kg
                        + prices.feed_fraction * base.allocated_feed_cost_cents / 100
                        - base.all_outcome_margin_cents / 100) / base.hcw_kg
                       if base.head_hcw_eligible > 0 else np.nan)
            records.append({
                "purchase_cad_per_live_kg": purchase, "feed_fraction": feed_fraction,
                "break_even_carcass_cad_per_hcw_kg": carcass,
                "nonnegative_eligible_prices": bool(carcass >= -self._min_carcass_price),
            })
        return pd.DataFrame.from_records(records)
