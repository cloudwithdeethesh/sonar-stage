import pytest

from src.validators import is_valid_email, is_valid_sku


@pytest.mark.parametrize(
    "value",
    [
        "user@example.com",
        "a.b+c@sub.example.co",
    ],
)
def test_is_valid_email_accepts(value):
    assert is_valid_email(value)


@pytest.mark.parametrize(
    "value",
    [
        "no-at-sign",
        "@example.com",
        "user@",
        "user@example",
        "x" * 300 + "@example.com",
    ],
)
def test_is_valid_email_rejects(value):
    assert not is_valid_email(value)


@pytest.mark.parametrize("value", ["AB-1234", "XYZ-00001", "ABCD-123456"])
def test_is_valid_sku_accepts(value):
    assert is_valid_sku(value)


@pytest.mark.parametrize(
    "value",
    ["ab-1234", "A-1234", "ABCDE-1234", "AB-12"],
)
def test_is_valid_sku_rejects(value):
    assert not is_valid_sku(value)
