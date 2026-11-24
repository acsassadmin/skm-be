from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Avg, Count

from catalogue.models import Product
from orders.models import Order, OrderItem
from catalogue.models import ProductReview


def get_verified_purchase(user, product, order_item=None) -> tuple[bool, OrderItem | None]:
    """
    Returns (is_verified_purchase, order_item) if the user has a DELIVERED
    order containing this product.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False, None

    if order_item is not None:
        is_valid = (
            order_item.order.user_id == user.id
            and order_item.product_id == product.id
            and order_item.order.status == Order.Status.DELIVERED
        )
        return is_valid, order_item if is_valid else None

    delivered_item = (
        OrderItem.objects.select_related("order")
        .filter(
            order__user=user,
            order__status=Order.Status.DELIVERED,
            product=product,
        )
        .order_by("-order__created_at")
        .first()
    )
    return bool(delivered_item), delivered_item


def recalculate_product_rating(product_or_id) -> Product | None:
    """
    Recalculates and updates average_rating and review_count on Product
    from APPROVED reviews only.
    """
    product = (
        product_or_id
        if isinstance(product_or_id, Product)
        else Product.objects.filter(pk=product_or_id).first()
    )
    if not product:
        return None

    stats = ProductReview.objects.filter(
        product=product,
        status=ProductReview.Status.APPROVED,
    ).aggregate(
        avg_rating=Avg("rating"),
        total_count=Count("id"),
    )

    avg_raw = stats["avg_rating"]
    avg_rating = (
        Decimal(str(avg_raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if avg_raw is not None
        else Decimal("0.00")
    )

    product.average_rating = avg_rating
    product.review_count = stats["total_count"] or 0
    product.save(update_fields=["average_rating", "review_count"])
    return product