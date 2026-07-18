"""Stage 8 quantity-conservation and state-transition contracts."""

import pytest

from backend.app.services.production_accounting import (
    ORDER_STATUS_TRANSITIONS,
    QuantityInvariantError,
    calculate_ledger,
    transition_order_status,
)


def test_quantity_ledger_conserves_required_quantity():
    ledger = calculate_ledger(required=20, reserved=6, good=9, scrap=2)

    assert ledger.planned == 20
    assert ledger.reserved == 6
    assert ledger.good == 9
    assert ledger.scrap == 2
    assert ledger.remaining == 5
    assert ledger.planned == ledger.reserved + ledger.good + ledger.remaining


@pytest.mark.parametrize(
    "values",
    [
        {"required": -1, "reserved": 0, "good": 0, "scrap": 0},
        {"required": 1, "reserved": -1, "good": 0, "scrap": 0},
        {"required": 1, "reserved": 0, "good": -1, "scrap": 0},
        {"required": 1, "reserved": 0, "good": 0, "scrap": -1},
        {"required": 10, "reserved": 6, "good": 5, "scrap": 0},
    ],
)
def test_quantity_ledger_rejects_negative_or_overallocated_values(values):
    with pytest.raises(QuantityInvariantError):
        calculate_ledger(**values)


def test_scrap_is_recorded_but_does_not_reduce_remaining_demand():
    ledger = calculate_ledger(required=10, reserved=0, good=4, scrap=3)
    assert ledger.remaining == 6


def test_order_status_transition_table_is_explicit_and_terminal_states_are_closed():
    assert {
        "draft": {"planned", "cancelled"},
        "planned": {"paused", "completed", "cancelled"},
        "paused": {"planned", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    } == ORDER_STATUS_TRANSITIONS
    assert transition_order_status("planned", "paused") == "paused"
    with pytest.raises(ValueError):
        transition_order_status("cancelled", "planned")
