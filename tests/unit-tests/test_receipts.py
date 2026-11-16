from decimal import Decimal

import pytest

from src.formatters import to_csv_row
from src.receipts import (
    LineItem,
    apply_discount,
    calculate_subtotal,
    calculate_tax,
    format_line,
)


def _item(name: str, unit_price: str, quantity: int) -> LineItem:
    return LineItem(name=name, unit_price=Decimal(unit_price), quantity=quantity)


def test_line_total_rounds_half_up():
    item = _item("widget", "2.005", 1)
    assert item.line_total() == Decimal("2.01")


def test_line_total_rejects_neg_qty():
    item = _item("widget", "1.00", -1)
    with pytest.raises(ValueError):
        item.line_total()


def test_calculate_subtotal_empty_cart():
    assert calculate_subtotal([]) == Decimal("0.00")


def test_calculate_subtotal_multiple_items():
    items = [_item("a", "1.50", 2), _item("b", "3.00", 1)]
    assert calculate_subtotal(items) == Decimal("6.00")


def test_apply_discount_percent():
    assert apply_discount(Decimal("10.00"), 10) == Decimal("9.00")


def test_apply_discount_zero_percent():
    assert apply_discount(Decimal("10.00"), 0) == Decimal("10.00")


def test_apply_discount_oob():
    with pytest.raises(ValueError):
        apply_discount(Decimal("10.00"), -1)
    with pytest.raises(ValueError):
        apply_discount(Decimal("10.00"), 101)


def test_calculate_tax():
    assert calculate_tax(Decimal("10.00"), 0.1) == Decimal("1.00")


def test_calculate_tax_neg_rate():
    with pytest.raises(ValueError):
        calculate_tax(Decimal("10.00"), -0.1)


def test_to_csv_row():
    item = _item("widget", "2.00", 3)
    assert to_csv_row(item) == "widget,2.00,3,6.00"
