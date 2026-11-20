from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from orders.models import Refund, ReturnRequest


def quantize_money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_return_refund_breakdown(return_request, include_tax=True):
    """
    Calculates subtotal_refund, tax_refund, and amount from a ReturnRequest's items.
    Safely falls back to zero if OrderItem doesn't expose line_total/tax_amount fields.
    """
    subtotal = Decimal("0.00")
    tax = Decimal("0.00")

    for item in return_request.items.select_related("order_item"):
        order_item = item.order_item
        qty = Decimal(item.quantity)

        if hasattr(order_item, "unit_price") and order_item.unit_price is not None:
            line_sub = Decimal(order_item.unit_price) * qty
        elif hasattr(order_item, "price") and order_item.price is not None:
            line_sub = Decimal(order_item.price) * qty
        else:
            line_sub = Decimal("0.00")

        subtotal += line_sub

        if include_tax and hasattr(order_item, "tax_amount") and order_item.tax_amount is not None:
            ordered_qty = Decimal(getattr(order_item, "quantity", 0) or 0)
            if ordered_qty > 0:
                tax += (Decimal(order_item.tax_amount) / ordered_qty) * qty

    subtotal = quantize_money(subtotal)
    tax = quantize_money(tax if include_tax else Decimal("0.00"))
    amount = quantize_money(subtotal + tax)

    return {
        "subtotal_refund": subtotal,
        "tax_refund": tax,
        "amount": amount,
    }


@transaction.atomic
def complete_return_request(return_request, restock_approved=None, admin_notes=None):
    """
    Marks a ReturnRequest COMPLETED, sets completed_at, and optionally restocks
    returned quantities back onto Product stock when restock_approved is True.
    """
    if restock_approved is not None:
        return_request.restock_approved = bool(restock_approved)
    if admin_notes is not None:
        return_request.admin_notes = admin_notes

    if return_request.restock_approved and return_request.status != ReturnRequest.Status.COMPLETED:
        for item in return_request.items.select_related("order_item__product"):
            product = getattr(item.order_item, "product", None)
            if product is not None and hasattr(product, "stock"):
                type(product).objects.filter(pk=product.pk).update(
                    stock=F("stock") + item.quantity
                )

    return_request.status = ReturnRequest.Status.COMPLETED
    if return_request.completed_at is None:
        return_request.completed_at = timezone.now()

    return_request.save(
        update_fields=[
            "status",
            "restock_approved",
            "admin_notes",
            "completed_at",
            "updated_at",
        ]
    )
    return return_request


@transaction.atomic
def update_refund_status(refund, new_status, gateway_refund_id=None, failure_reason=None):
    """
    Updates Refund status cleanly and stamps processed_at when COMPLETED.
    """
    refund.status = new_status
    update_fields = ["status", "updated_at"]

    if gateway_refund_id is not None:
        refund.gateway_refund_id = gateway_refund_id
        update_fields.append("gateway_refund_id")

    if failure_reason is not None:
        refund.failure_reason = failure_reason
        update_fields.append("failure_reason")

    if new_status == Refund.Status.COMPLETED:
        if refund.processed_at is None:
            refund.processed_at = timezone.now()
        refund.failure_reason = ""
        update_fields.extend(["processed_at", "failure_reason"])
    elif new_status in (Refund.Status.INITIATED, Refund.Status.PROCESSING, Refund.Status.FAILED, Refund.Status.CANCELLED):
        if new_status != Refund.Status.FAILED and refund.processed_at is not None and new_status == Refund.Status.INITIATED:
            refund.processed_at = None
            update_fields.append("processed_at")

    refund.save(update_fields=list(dict.fromkeys(update_fields)))
    return refund


def get_order_refunded_total(order):
    """
    Returns total COMPLETED refund amount for an order.
    """
    total = (
        Refund.objects.filter(order=order, status=Refund.Status.COMPLETED)
        .aggregate(total=Sum("amount"))
        .get("total")
    )
    return quantize_money(total or Decimal("0.00"))