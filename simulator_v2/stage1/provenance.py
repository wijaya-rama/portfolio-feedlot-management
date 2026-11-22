"""Stable identifiers and canonical JSON encoding."""

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from functools import cache
from json.encoder import encode_basestring as _quote

from .model import UTC


@cache
def _field_names(cls):
    return tuple(field.name for field in fields(cls))


def _encode_dt(value):
    if value.tzinfo is UTC:
        return value.isoformat()[:-6] + "Z"
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def encode(value):
    cls = type(value)
    if is_dataclass(cls):
        return {name: getattr(value, name) for name in _field_names(cls)}
    if isinstance(value, datetime):
        return _encode_dt(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported canonical value: {cls.__name__}")


_ENCODER = json.JSONEncoder(default=encode, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False)


def _fast_list(items):
    parts = []
    for item in items:
        t = type(item)
        if t is str:
            parts.append(_quote(item))
        elif item is None:
            parts.append("null")
        elif t is int:
            parts.append(str(item))
        elif t is datetime:
            parts.append(f'"{_encode_dt(item)}"')
        elif t is list and all(type(x) is str for x in item):
            parts.append("[" + ",".join(_quote(x) for x in item) + "]")
        elif isinstance(item, str):
            parts.append(_quote(item))
        else:
            return None
    return ("[" + ",".join(parts) + "]\n").encode("utf-8")


def canonical(value):
    if type(value) is list:
        fast = _fast_list(value)
        if fast is not None:
            return fast
    return (_ENCODER.encode(value) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix, value):
    return f"SYN-{prefix}-{sha256(canonical(value))[:24]}"
