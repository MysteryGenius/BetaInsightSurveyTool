from datetime import datetime, timezone
from pathlib import Path

import pytest

from surveytool.ingest.display_order import (
    DisplayOrder,
    ProjectDisplayOrders,
    load_display_orders,
    write_display_order,
)


def test_load_display_orders_returns_empty_for_missing_file(tmp_path):
    result = load_display_orders(tmp_path / "does_not_exist.yaml")
    assert result.orders == {}


def test_write_then_load_round_trips(tmp_path):
    path = tmp_path / "orders.yaml"
    order = DisplayOrder(
        variable="Q7",
        label_order=["Likely", "Very Likely", "Neutral", "Unlikely", "Very Unlikely"],
        is_manual=True,
        saved_at=datetime.now(timezone.utc),
    )
    write_display_order(path, order)
    loaded = load_display_orders(path)
    assert loaded.orders["Q7"].label_order == order.label_order
    assert loaded.orders["Q7"].is_manual is True


def test_write_overwrites_existing_entry_for_same_variable(tmp_path):
    path = tmp_path / "orders.yaml"
    first = DisplayOrder(variable="Q7", label_order=["A", "B"], is_manual=True, saved_at=datetime.now(timezone.utc))
    second = DisplayOrder(variable="Q7", label_order=["B", "A"], is_manual=True, saved_at=datetime.now(timezone.utc))
    write_display_order(path, first)
    write_display_order(path, second)
    loaded = load_display_orders(path)
    assert loaded.orders["Q7"].label_order == ["B", "A"]
