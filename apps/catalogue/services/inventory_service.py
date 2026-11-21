from django.db import transaction
from rest_framework.exceptions import ValidationError

from catalogue.models import InventoryLog, Product


@transaction.atomic
def adjust_product_stock(
    *,
    product_id: int,
    quantity_change: int,
    transaction_type: str,
    performed_by=None,
    reference_id: str = "",
    notes: str = "",
) -> InventoryLog:
    """
    Atomically locks the Product row, validates non-negative stock,
    updates stock_quantity, and writes an immutable InventoryLog entry.
    """
    if quantity_change == 0:
        raise ValidationError({"quantity_change": "Quantity change cannot be zero."})

    try:
        product = Product.objects.select_for_update().get(pk=product_id)
    except Product.DoesNotExist:
        raise ValidationError({"product_id": f"Product with id={product_id} not found."})

    stock_before = product.stock_quantity
    stock_after = stock_before + quantity_change

    if stock_after < 0:
        raise ValidationError(
            {
                "stock": (
                    f"Insufficient stock for '{product.name}' (SKU: {product.sku}). "
                    f"Available: {stock_before}, Requested deduction: {abs(quantity_change)}."
                )
            }
        )

    product.stock_quantity = stock_after
    product.save(update_fields=["stock_quantity", "updated_at"])

    return InventoryLog.objects.create(
        product=product,
        transaction_type=transaction_type,
        quantity_change=quantity_change,
        stock_before=stock_before,
        stock_after=stock_after,
        reference_id=reference_id,
        notes=notes,
        performed_by=performed_by,
    )
