from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone


def is_user_dealer(user) -> bool:
    """
    Checks whether the authenticated user holds an active DEALER role.
    """
    if not user or not user.is_authenticated:
        return False
    return user.roles.filter(code="DEALER", is_active=True).exists()


def calculate_coupon_discount(coupon, subtotal: Decimal) -> Decimal:
    """
    Validates active status, expiry, usage limits, and min order amount
    against the current cart subtotal, returning the discount amount.
    """
    if not coupon or not coupon.is_active:
        return Decimal("0.00")

    now = timezone.now()
    if getattr(coupon, "valid_from", None) and now < coupon.valid_from:
        return Decimal("0.00")
    if getattr(coupon, "valid_until", None) and now > coupon.valid_until:
        return Decimal("0.00")

    usage_limit = getattr(coupon, "usage_limit", None)
    used_count = getattr(coupon, "used_count", 0)
    if usage_limit is not None and used_count >= usage_limit:
        return Decimal("0.00")

    min_order = Decimal(getattr(coupon, "min_order_amount", 0) or 0)
    if subtotal < min_order:
        return Decimal("0.00")

    discount_type = getattr(coupon, "discount_type", "PERCENTAGE")
    discount_value = Decimal(getattr(coupon, "discount_value", 0) or 0)

    if discount_type == "PERCENTAGE":
        discount = (subtotal * discount_value / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        max_discount = getattr(coupon, "max_discount_amount", None)
        if max_discount is not None:
            discount = min(discount, Decimal(max_discount))
    else:
        discount = min(discount_value, subtotal)

    return discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
