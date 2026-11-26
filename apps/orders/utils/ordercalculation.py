from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from catalogue.models import Product
from orders.models import Cart, Coupon, Order, OrderItem
from orders.services.cart_service import is_user_dealer, calculate_coupon_discount


def quantize_money(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_line_amounts(unit_price: Decimal, quantity: int, gst_rate: Decimal) -> dict[str, Decimal]:
    line_subtotal = quantize_money(Decimal(unit_price) * Decimal(quantity))
    tax_amount = quantize_money((line_subtotal * Decimal(gst_rate or 0)) / Decimal("100.00"))
    line_total = quantize_money(line_subtotal + tax_amount)
    return {
        "line_subtotal": line_subtotal,
        "tax_amount": tax_amount,
        "line_total": line_total,
    }


def recalculate_order_totals(order: Order, shipping_amount: Decimal | None = None) -> Order:
    items = list(order.items.all())

    subtotal = quantize_money(
        sum((Decimal(item.line_subtotal) for item in items), Decimal("0.00"))
    )
    raw_tax = quantize_money(
        sum((Decimal(item.tax_amount) for item in items), Decimal("0.00"))
    )

    discount = Decimal("0.00")
    if order.coupon:
        is_valid, _ = order.coupon.is_valid_for_amount(subtotal)
        if is_valid:
            discount = quantize_money(calculate_coupon_discount(order.coupon, subtotal))
    discount = min(discount, subtotal)

    taxable_amount = max(subtotal - discount, Decimal("0.00"))

    if subtotal > Decimal("0.00") and discount > Decimal("0.00"):
        tax_amount = quantize_money(raw_tax * (taxable_amount / subtotal))
    else:
        tax_amount = raw_tax

    if shipping_amount is not None:
        order.shipping_amount = quantize_money(Decimal(shipping_amount))
    else:
        order.shipping_amount = quantize_money(Decimal(order.shipping_amount or 0))

    order.subtotal_amount = subtotal
    order.discount_amount = discount
    order.tax_amount = tax_amount
    order.total_amount = quantize_money(taxable_amount + tax_amount + order.shipping_amount)

    order.save(
        update_fields=[
            "subtotal_amount",
            "discount_amount",
            "tax_amount",
            "shipping_amount",
            "total_amount",
            "updated_at",
        ]
    )
    return order


@transaction.atomic
def create_order_from_cart(
    user,
    cart: Cart,
    shipping_data: dict,
    shipping_amount: Decimal = Decimal("0.00"),
) -> Order:
    cart_items = list(cart.items.select_related("product").select_for_update())
    if not cart_items:
        raise ValueError("Cart is empty.")

    is_dealer = is_user_dealer(user)
    coupon = cart.applied_coupon

    order = Order.objects.create(
        user=user,
        coupon=coupon,
        coupon_code=coupon.code if coupon else "",
        is_dealer_order=is_dealer,
        payment_status=Order.PaymentStatus.INITIATE,
        shipping_full_name=shipping_data.get("shipping_full_name") or user.full_name,
        shipping_phone=shipping_data.get("shipping_phone") or user.phone,
        shipping_address=shipping_data["shipping_address"],
        shipping_city=shipping_data["shipping_city"],
        shipping_state=shipping_data["shipping_state"],
        shipping_pincode=shipping_data["shipping_pincode"],
        notes=shipping_data.get("notes", ""),
        shipping_amount=quantize_money(shipping_amount),
    )

    order_items = []
    for c_item in cart_items:
        product = Product.objects.select_for_update().get(pk=c_item.product_id)
        if not product.is_active or product.stock_quantity < c_item.quantity:
            raise ValueError(f"Insufficient stock or inactive product: {product.name}")

        unit_price = quantize_money(c_item.get_unit_price(is_dealer))
        gst_rate = Decimal(product.gst_rate or 0)
        amounts = calculate_line_amounts(unit_price, c_item.quantity, gst_rate)

        product.stock_quantity -= c_item.quantity
        product.save(update_fields=["stock_quantity", "updated_at"])

        order_items.append(
            OrderItem(
                order=order,
                product=product,
                product_name=product.name,
                product_sku=product.sku,
                hsn_code=product.hsn_code,
                quantity=c_item.quantity,
                unit_price=unit_price,
                gst_rate=gst_rate,
                tax_amount=amounts["tax_amount"],
                line_subtotal=amounts["line_subtotal"],
                line_total=amounts["line_total"],
            )
        )

    OrderItem.objects.bulk_create(order_items)
    recalculate_order_totals(order, shipping_amount=shipping_amount)

    if coupon and order.discount_amount > Decimal("0.00"):
        Coupon.objects.filter(pk=coupon.pk).update(used_count=models.F("used_count") + 1)

    cart.items.all().delete()
    cart.applied_coupon = None
    cart.save(update_fields=["applied_coupon", "updated_at"])

    return order


@transaction.atomic
def add_or_update_order_item(order: Order, product: Product, quantity: int) -> OrderItem:
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")

    locked_product = Product.objects.select_for_update().get(pk=product.pk)
    existing = OrderItem.objects.filter(order=order, product=locked_product).first()

    old_qty = existing.quantity if existing else 0
    delta = quantity - old_qty

    if delta > 0 and locked_product.stock_quantity < delta:
        raise ValueError(f"Only {locked_product.stock_quantity} additional unit(s) available.")

    if delta != 0:
        locked_product.stock_quantity -= delta
        locked_product.save(update_fields=["stock_quantity", "updated_at"])

    unit_price = (
        existing.unit_price
        if existing
        else quantize_money(
            locked_product.dealer_price
            if order.is_dealer_order and locked_product.dealer_price is not None
            else locked_product.customer_price
        )
    )
    gst_rate = existing.gst_rate if existing else Decimal(locked_product.gst_rate or 0)
    amounts = calculate_line_amounts(unit_price, quantity, gst_rate)

    if existing:
        existing.quantity = quantity
        existing.unit_price = unit_price
        existing.gst_rate = gst_rate
        existing.tax_amount = amounts["tax_amount"]
        existing.line_subtotal = amounts["line_subtotal"]
        existing.line_total = amounts["line_total"]
        existing.save()
        order_item = existing
    else:
        order_item = OrderItem.objects.create(
            order=order,
            product=locked_product,
            product_name=locked_product.name,
            product_sku=locked_product.sku,
            hsn_code=locked_product.hsn_code,
            quantity=quantity,
            unit_price=unit_price,
            gst_rate=gst_rate,
            tax_amount=amounts["tax_amount"],
            line_subtotal=amounts["line_subtotal"],
            line_total=amounts["line_total"],
        )

    recalculate_order_totals(order)
    return order_item


@transaction.atomic
def delete_order_item(order_item: OrderItem) -> None:
    order = order_item.order
    product = Product.objects.select_for_update().get(pk=order_item.product_id)

    product.stock_quantity += order_item.quantity
    product.save(update_fields=["stock_quantity", "updated_at"])

    order_item.delete()
    recalculate_order_totals(order)