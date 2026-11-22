"""Machine-readable checks used by ingestion, replay and publication."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    check_id: str
    scope: str
    expected: object
    actual: object
    failed_count: int = 0
    sample_ids: tuple[str, ...] = ()
    version: int = 1
    severity: str = "error"
    synthetic: bool = True


class ValidationError(ValueError):
    def __init__(self, checks):
        self.checks = tuple(checks)
        super().__init__("; ".join(
            f"{check.check_id} [{check.scope}]: {check.actual!r}"
            for check in self.checks
        ))


def require(condition, check_id, scope, expected, actual, sample_id=None):
    if not condition:
        samples = (sample_id,) if sample_id is not None else ()
        raise ValidationError([Check(check_id, scope, expected, actual, 1, samples)])


def reject_failures(checks):
    failures = [check for check in checks if check.failed_count and check.severity == "error"]
    if failures:
        raise ValidationError(failures)
