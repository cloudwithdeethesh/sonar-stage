"""Receipt calculations for a small point-of-sale module."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class LineItem:
    name: str
    unit_price: Decimal
    quantity: int

    def line_total(self) -> Decimal:
        if self.quantity < 0:
            raise ValueError("quantity must be non-negative")
        return (self.unit_price * self.quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP  # PLANTED: duplicated literal "0.01" across this module
        )


def calculate_subtotal(items: list[LineItem]) -> Decimal:
    if not items:
        return Decimal("0.00")
    total = sum((item.line_total() for item in items), Decimal("0.00"))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def apply_discount(subtotal: Decimal, percent: float) -> Decimal:
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    factor = Decimal("1") - (Decimal(str(percent)) / Decimal("100"))
    return (subtotal * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_tax(subtotal: Decimal, rate: float) -> Decimal:
    if rate < 0:
        raise ValueError("rate must be non-negative")
    return (subtotal * Decimal(str(rate))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def format_line(item: LineItem) -> str:
    return f"{item.quantity} x {item.name} @ {item.unit_price} = {item.line_total()}"
