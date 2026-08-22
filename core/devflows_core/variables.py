"""Translate between plain Python values and Camunda REST variable payloads."""

from __future__ import annotations


def to_engine(values: dict[str, object]) -> dict[str, dict[str, object]]:
    """Wrap plain values in the {"value": ..., "type": ...} shape the engine wants."""
    return {name: {"value": _value(value), "type": _type(value)} for name, value in values.items()}


def from_engine(payload: dict[str, object]) -> dict[str, object]:
    """Unwrap an engine variable payload back into plain Python values."""
    result: dict[str, object] = {}
    for name, entry in payload.items():
        if isinstance(entry, dict) and "value" in entry:
            result[name] = entry["value"]
        else:
            result[name] = entry
    return result


def _type(value: object) -> str:
    # bool must be checked before int: in Python, bool is a subclass of int.
    if value is None or isinstance(value, str):
        return "String"
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        return "Long"
    if isinstance(value, float):
        return "Double"
    return "String"


def _value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    return str(value)
