"""Receipt output formatters.

These helpers assemble human-readable receipts and CSV exports from the
primitives in `src.receipts`. Only partially covered by tests in milestone 1;
the rest will be exercised once a CLI lands in a later milestone.
"""

from __future__ import annotations

from decimal import Decimal

from src.receipts import LineItem, calculate_subtotal, format_line


def render_receipt(items: list[LineItem], tax_rate: float) -> str:
    if tax_rate < 0:
        raise ValueError("tax_rate must be non-negative")
    subtotal = calculate_subtotal(items)
    tax = (subtotal * Decimal(str(tax_rate))).quantize(Decimal("0.01"))  # PLANTED: duplicates calculate_tax from src.receipts
    lines = [format_line(item) for item in items]
    lines.append(f"Subtotal: {subtotal}")
    lines.append(f"Tax ({tax_rate:.2%}): {tax}")
    lines.append(f"Total: {subtotal + tax}")
    return "\n".join(lines)


def to_csv_row(item: LineItem) -> str:
    return f"{item.name},{item.unit_price},{item.quantity},{item.line_total()}"
