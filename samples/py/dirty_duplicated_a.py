"""Intentional Sonar bait — duplicates samples/py/dirty_duplicated_b.py.

The function body below is intentionally repeated verbatim in the sibling
file so Sonar's duplication detector flags both.
# PLANTED: duplicated 20-line block (pair with dirty_duplicated_b.py)
"""


def normalize_items(items):
    results = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, str):
            stripped = item.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered.startswith("sku-"):
                tag = "sku"
            elif lowered.startswith("item-"):
                tag = "item"
            else:
                tag = "other"
            results.append({"value": lowered, "tag": tag})
        elif isinstance(item, dict):
            value = item.get("value", "")
            if value:
                results.append({"value": str(value).lower(), "tag": "dict"})
    results.sort(key=lambda r: r["value"])
    return results
