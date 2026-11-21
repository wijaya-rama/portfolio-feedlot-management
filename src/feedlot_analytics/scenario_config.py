"""Validated, immutable inputs for management scenario replay."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from numbers import Real
from types import MappingProxyType

from .contracts import DOMAINS

PHASES = DOMAINS["Fact_Feed_Daily"]["ration_phase"]
FEED_COMPONENTS = ("forage", "concentrate", "supplement")


def number(name, value, *, minimum=None, maximum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ValueError(f"{name} outside allowed bounds [{minimum}, {maximum}]")


def positive_integer(name, value):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _multipliers(name, values, allowed):
    if not isinstance(values, Mapping) or set(values) - set(allowed):
        raise ValueError(f"{name} must map these names to fractional changes: {', '.join(allowed)}")
    for key, value in values.items():
        number(f"{name}.{key}", value, minimum=-1)
    return MappingProxyType(dict(sorted(values.items())))


@dataclass(frozen=True)
class PriceShocks:
    """Signed nominal CAD/kg or fractional changes at fixed recorded volumes."""

    purchase_cad_per_live_kg: float = 0
    carcass_cad_per_hcw_kg: float = 0
    carcass_fraction: float = 0
    feed_fraction: float = 0
    feed_phase_fractions: Mapping[str, float] = field(default_factory=dict)
    feed_component_fractions: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("purchase_cad_per_live_kg", "carcass_cad_per_hcw_kg"):
            number(name, getattr(self, name))
        for name in ("carcass_fraction", "feed_fraction"):
            number(name, getattr(self, name), minimum=-1)
        if self.carcass_cad_per_hcw_kg and self.carcass_fraction:
            raise ValueError("Specify either a carcass CAD/kg change or a fractional change")
        for name, allowed in (("feed_phase_fractions", PHASES), ("feed_component_fractions", FEED_COMPONENTS)):
            object.__setattr__(self, name, _multipliers(name, getattr(self, name), allowed))

    @property
    def active(self):
        return any((self.purchase_cad_per_live_kg, self.carcass_cad_per_hcw_kg,
                    self.carcass_fraction, self.feed_fraction, *self.feed_phase_fractions.values(),
                    *self.feed_component_fractions.values()))

    def reprice_carcass(self, revenue_cad, hcw_kg):
        return revenue_cad * (1 + self.carcass_fraction) + hcw_kg * self.carcass_cad_per_hcw_kg


@dataclass(frozen=True)
class AdditionalSurvivors:
    """Whole recorded deaths converted to conditional sales at specified finish terms."""

    head: int
    finish_financial_dof: int
    finish_live_kg: float
    dressing_fraction: float
    price_cad_per_hcw_kg: float
    feed_cad_per_extra_day: float
    yardage_cad_per_extra_day: float
    vet_cad_per_head: float
    other_cad_per_head: float

    def __post_init__(self):
        positive_integer("head", self.head)
        positive_integer("finish_financial_dof", self.finish_financial_dof)
        number("finish_live_kg", self.finish_live_kg, positive=True)
        number("dressing_fraction", self.dressing_fraction, maximum=1, positive=True)
        for name in ("price_cad_per_hcw_kg", "feed_cad_per_extra_day", "yardage_cad_per_extra_day",
                     "vet_cad_per_head", "other_cad_per_head"):
            number(name, getattr(self, name), minimum=0)


@dataclass(frozen=True)
class AdditionalDeaths:
    """Whole recorded sales converted to deaths with explicit avoidable cost shares."""

    head: int
    avoidable_feed_fraction: float
    avoidable_yardage_fraction: float
    vet_cad_per_head: float
    other_cad_per_head: float

    def __post_init__(self):
        positive_integer("head", self.head)
        for name in ("avoidable_feed_fraction", "avoidable_yardage_fraction"):
            number(name, getattr(self, name), minimum=0, maximum=1)
        for name in ("vet_cad_per_head", "other_cad_per_head"):
            number(name, getattr(self, name), minimum=0)


@dataclass(frozen=True)
class Scenario:
    name: str
    prices: PriceShocks = field(default_factory=PriceShocks)
    mortality: AdditionalSurvivors | AdditionalDeaths | None = None
    limitations: str = ""

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Scenario name must be nonempty text")
        if not isinstance(self.prices, PriceShocks):
            raise ValueError("prices must be PriceShocks")
        if self.mortality is not None and not isinstance(self.mortality, (AdditionalSurvivors, AdditionalDeaths)):
            raise ValueError("mortality must be AdditionalSurvivors or AdditionalDeaths")
        if not isinstance(self.limitations, str):
            raise ValueError("limitations must be text")

    @property
    def kind(self):
        if self.mortality is not None:
            return "hypothetical operational"
        return "fixed-volume accounting" if self.prices.active else "observed booked"

    def assumptions(self):
        """Report input values with unit-bearing field names."""
        prices = {name: (dict(value) if isinstance(value, Mapping) else value)
                  for name, value in vars(self.prices).items() if value}
        mortality = None if self.mortality is None else {
            "direction": "lower" if isinstance(self.mortality, AdditionalSurvivors) else "higher",
            **vars(self.mortality),
        }
        return {"prices": prices, "mortality": mortality}


def _unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Scenario JSON contains a duplicate field")
    return result


def load_scenarios(path):
    """Read a nonempty JSON array of scenarios with unique names."""
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
    if not isinstance(data, list) or not data:
        raise ValueError("Scenario configuration must be a nonempty JSON array")
    scenarios = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each scenario must be a JSON object")
        fields = item.copy()
        try:
            prices = PriceShocks(**fields.pop("prices", {}))
            mortality = fields.pop("mortality", None)
            if mortality is not None:
                mortality = dict(mortality) if isinstance(mortality, dict) else {}
                direction = mortality.pop("direction", None)
                if direction == "lower":
                    mortality = AdditionalSurvivors(**mortality)
                elif direction == "higher":
                    mortality = AdditionalDeaths(**mortality)
                else:
                    raise ValueError("mortality.direction must be 'lower' or 'higher'")
            scenarios.append(Scenario(**fields, prices=prices, mortality=mortality))
        except TypeError as error:
            raise ValueError(f"Invalid fields for scenario {item.get('name')!r}: {error}") from error
    if len({scenario.name for scenario in scenarios}) != len(scenarios):
        raise ValueError("Scenario names must be unique")
    return tuple(scenarios)
