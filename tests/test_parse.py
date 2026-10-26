from datetime import datetime, timezone
from decimal import Decimal

import pytest

from fetch_rates import ApiError, parse_response

GOOD = {
    "result": "success", "provider": "https://www.exchangerate-api.com",
    "time_last_update_unix": 1759536000, "base_code": "EUR",
    "rates": {"EUR": 1, "USD": 1.17, "TND": 3.4}
}


def test_parses_rate_and_timestamp():
    updated, rates = parse_response(GOOD, ["TND", "USD"])
    assert rates == {"TND": Decimal("3.4"), "USD": Decimal("1.17")}
    assert updated == datetime.fromtimestamp(1759536000, tz=timezone.utc)


def test_api_error_result_raises():
    with pytest.raises(ApiError, match="unsupported-code"):
        parse_response({"result": "error", "error-type": "unsupported-code"}, ["TND"])


def test_missing_currency_raises():
    with pytest.raises(ApiError, match="XYZ"):
        parse_response(GOOD, ["XYZ"])


def test_float_noise_is_avoided():
    # 0.1 + 0.2 style float noise must not leak into stored money values
    _, rates = parse_response({**GOOD, "rates": {"TND": 3.3000000000000003}}, ["TND"])
    assert rates["TND"] == Decimal("3.3000000000000003")  # exact decimal of what the API sent
