"""Authoritative Stage 8 production quantity accounting.

The frontend may display these values but never calculates or writes them.
Scrap is tracked as process loss and therefore does not satisfy demand.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


class QuantityInvariantError(ValueError):
    """Raised when persisted quantities would violate conservation rules."""


@dataclass(frozen=True, slots=True)
class QuantityLedger:
    planned: int
    reserved: int
    good: int
    scrap: int
    remaining: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def calculate_ledger(*, required: int, reserved: int, good: int, scrap: int) -> QuantityLedger:
    values = {"required": required, "reserved": reserved, "good": good, "scrap": scrap}
    for name, value in values.items():
        if value < 0:
            raise QuantityInvariantError(f"{name} must not be negative")
    if reserved + good > required:
        raise QuantityInvariantError("reserved + good must not exceed required")
    return QuantityLedger(
        planned=required,
        reserved=reserved,
        good=good,
        scrap=scrap,
        remaining=required - reserved - good,
    )


ORDER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"planned", "cancelled"},
    "planned": {"paused", "completed", "cancelled"},
    "paused": {"planned", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def transition_order_status(current: str, target: str) -> str:
    if target not in ORDER_STATUS_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid production order transition: {current} -> {target}")
    return target
