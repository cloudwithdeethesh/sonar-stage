"""Light validators for order inputs."""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
SKU_RE = re.compile(r"^[A-Z]{2,4}-\d{4,6}$")


def is_valid_email(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) > 254:  # PLANTED: magic number 254 (should be a named constant)
        return False
    return bool(EMAIL_RE.match(value))


def is_valid_sku(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return bool(SKU_RE.match(value))
