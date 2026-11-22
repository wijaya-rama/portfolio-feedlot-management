"""Stable identifiers and canonical JSON encoding."""

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime

from .model import UTC


def encode(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical(value):
    return (json.dumps(value, default=encode, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix, value):
    return f"SYN-{prefix}-{sha256(canonical(value))[:24]}"
