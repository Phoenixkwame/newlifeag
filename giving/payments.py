from decimal import Decimal, InvalidOperation


def payment_matches(result, *, reference, amount):
    """Bind the provider's verified payment to the exact checkout we created."""
    if not isinstance(result, dict) or not reference or amount is None:
        return False
    data = result.get("data")
    if not isinstance(data, dict):
        return False
    try:
        paid = Decimal(str(data.get("amount")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return (
        paid.is_finite()
        and result.get("status") == "success"
        and data.get("status") == "successful"
        and data.get("tx_ref") == reference
        and paid == amount
        and data.get("currency") == "GHS"
    )
