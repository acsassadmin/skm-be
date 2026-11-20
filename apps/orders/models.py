from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.conf import settings
from catalogue.models import  Product
import uuid

class Coupon(models.Model):
    """Coupon and promotional code management."""

    class DiscountType(models.TextChoices):
        PERCENTAGE = "PERCENTAGE", "Percentage"
        FIXED = "FIXED", "Fixed Amount"

    code = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True)
    campaign_tag = models.CharField(max_length=80, blank=True, db_index=True)
    discount_type = models.CharField(
        max_length=15, choices=DiscountType.choices, default=DiscountType.PERCENTAGE
    )
    discount_value = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    min_order_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    max_discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def is_valid_for_amount(self, subtotal: Decimal) -> tuple[bool, str]:
        now = timezone.now()
        if not self.is_active:
            return False, "This coupon is inactive."
        if now < self.valid_from:
            return False, "This coupon is not active yet."
        if now > self.valid_until:
            return False, "This coupon has expired."
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return False, "Coupon usage limit has been reached."
        if subtotal < self.min_order_amount:
            return False, f"Minimum order amount of ₹{self.min_order_amount} is required."
        return True, "Valid"

    def calculate_discount(self, subtotal: Decimal) -> Decimal:
        if self.discount_type == self.DiscountType.PERCENTAGE:
            discount = (subtotal * self.discount_value) / Decimal("100.00")
            if self.max_discount_amount is not None:
                discount = min(discount, self.max_discount_amount)
        else:
            discount = self.discount_value
        return min(discount, subtotal).quantize(Decimal("0.01"))

    def __str__(self):
        return f"{self.code} ({self.discount_type})"




class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
    )
    applied_coupon = models.ForeignKey(
        "orders.Coupon",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="carts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_cart"

    def __str__(self):
        return f"Cart ({self.user.email})"


class CartItem(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="cart_items",
    )
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_cart_item"
        unique_together = ("cart", "product")

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    def get_unit_price(self, is_dealer: bool) -> Decimal:
      
        if is_dealer and self.product.dealer_price is not None:
            return Decimal(self.product.dealer_price)
        return Decimal(self.product.customer_price)

class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        PROCESSING = "PROCESSING", "Processing"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"
        REFUNDED = "REFUNDED", "Refunded"
        RETURN_REQUESTED = "RETURN_REQUESTED", "Return Requested"
        RETURNED = "RETURNED", "Returned"

    class PaymentStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    order_number = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    coupon = models.ForeignKey(
        "orders.Coupon",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    coupon_code = models.CharField(max_length=50, blank=True)

    is_dealer_order = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True
    )

    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    shipping_full_name = models.CharField(max_length=150)
    shipping_phone = models.CharField(max_length=15)
    shipping_address = models.TextField()
    shipping_city = models.CharField(max_length=100)
    shipping_state = models.CharField(max_length=100)
    shipping_pincode = models.CharField(max_length=15)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_order"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.order_number:
            date_str = timezone.now().strftime("%Y%m%d")
            suffix = uuid.uuid4().hex[:6].upper()
            self.order_number = f"ORD-{date_str}-{suffix}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_number} ({self.user.email})"


class OrderItem(models.Model):
    """Line items in an order (order list)."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=200)
    product_sku = models.CharField(max_length=60)
    hsn_code = models.CharField(max_length=20, blank=True)

    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"))
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    line_subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        db_table = "orders_order_item"
        unique_together = ("order", "product")

    def __str__(self):
        return f"{self.product_name} x {self.quantity} ({self.order.order_number})"




class ReturnRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        APPROVED = "APPROVED", "Approved"
        PICKUP_SCHEDULED = "PICKUP_SCHEDULED", "Pickup Scheduled"
        RECEIVED = "RECEIVED", "Received"
        INSPECTED = "INSPECTED", "Inspected"
        REJECTED = "REJECTED", "Rejected"
        COMPLETED = "COMPLETED", "Completed"

    class Reason(models.TextChoices):
        DEFECTIVE = "DEFECTIVE", "Defective"
        WRONG_ITEM = "WRONG_ITEM", "Wrong Item"
        DAMAGED_IN_TRANSIT = "DAMAGED_IN_TRANSIT", "Damaged in Transit"
        NOT_NEEDED = "NOT_NEEDED", "Not Needed"
        OTHER = "OTHER", "Other"

    return_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="returns",
    )
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True,
    )
    reason = models.CharField(
        max_length=30,
        choices=Reason.choices,
    )
    customer_notes = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True)
    restock_approved = models.BooleanField(default=False)

    requested_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_return_request"
        ordering = ["-requested_at"]

    def save(self, *args, **kwargs):
        if not self.return_number:
            date_str = timezone.now().strftime("%Y%m%d")
            suffix = uuid.uuid4().hex[:6].upper()
            self.return_number = f"RET-{date_str}-{suffix}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.return_number} ({self.order.order_number})"


class ReturnItem(models.Model):
    class ItemCondition(models.TextChoices):
        UNOPENED = "UNOPENED", "Unopened"
        OPENED_GOOD = "OPENED_GOOD", "Opened - Good Condition"
        DAMAGED = "DAMAGED", "Damaged"
        DEFECTIVE = "DEFECTIVE", "Defective"

    return_request = models.ForeignKey(
        ReturnRequest,
        on_delete=models.CASCADE,
        related_name="items",
    )
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.PROTECT,
        related_name="return_items",
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    item_condition = models.CharField(
        max_length=25,
        choices=ItemCondition.choices,
    )

    class Meta:
        db_table = "orders_return_item"
        unique_together = ("return_request", "order_item")

    def __str__(self):
        return f"{self.order_item.product_name} x {self.quantity} ({self.return_request.return_number})"


class Refund(models.Model):
    class Status(models.TextChoices):
        INITIATED = "INITIATED", "Initiated"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    class RefundMethod(models.TextChoices):
        ORIGINAL_PAYMENT = "ORIGINAL_PAYMENT", "Original Payment Method"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        STORE_CREDIT = "STORE_CREDIT", "Store Credit"

    refund_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="refunds",
    )
    return_request = models.ForeignKey(
        ReturnRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refunds",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INITIATED,
        db_index=True,
    )
    refund_method = models.CharField(
        max_length=25,
        choices=RefundMethod.choices,
    )

    subtotal_refund = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tax_refund = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    gateway_refund_id = models.CharField(max_length=100, blank=True, db_index=True)
    failure_reason = models.TextField(blank=True)

    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_refund"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.refund_number:
            date_str = timezone.now().strftime("%Y%m%d")
            suffix = uuid.uuid4().hex[:6].upper()
            self.refund_number = f"RFD-{date_str}-{suffix}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.refund_number} ({self.order.order_number} - {self.amount})"