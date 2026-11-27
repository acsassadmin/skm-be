from django.db import models
from django.utils import timezone
from orders.models import *

from django.contrib.auth import get_user_model
User=get_user_model()
# Create your models here.
class PaymentSetting(models.Model):
    """
    Admin-configurable payment settings.
    Supports dynamic QR/UPI details today and a Razorpay toggle for Phase 2.
    """

    label = models.CharField(max_length=100, default="SKM Electronics Primary UPI")
    upi_id = models.CharField(
        max_length=100, blank=True, help_text="e.g., skmelectronics@okicici"
    )
    upi_mobile_number = models.CharField(
        max_length=20, blank=True, help_text="e.g., 9876543210"
    )
    account_holder_name = models.CharField(max_length=150, default="SKM Electronics")
    qr_code_image = models.ImageField(
        upload_to="payments/qr_codes/", null=True, blank=True
    )
    payment_instructions = models.TextField(
        blank=True,
        default="Scan the QR code or transfer to the UPI ID / mobile number shown, then submit your 12-digit UTR/Transaction ID for verification.",
    )

    # Gateway feature toggles
    is_manual_upi_enabled = models.BooleanField(default=True)
    is_razorpay_enabled = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True, db_index=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_payment_settings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_payment_setting"
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        if self.is_active:
            PaymentSetting.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.label} ({'Active' if self.is_active else 'Inactive'})"


class PaymentTransaction(models.Model):
    """
    Gateway-agnostic payment ledger.
    Handles Manual QR/UPI proofs now and Razorpay orders/webhooks in the future.
    """

    class Gateway(models.TextChoices):
        MANUAL_UPI = "MANUAL_UPI", "Manual UPI / QR Code"
        RAZORPAY = "RAZORPAY", "Razorpay"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Payment"
        PENDING_VERIFICATION="PENDING_VERIFICATION", "Pending Verification"
        SUBMITTED = "SUBMITTED", "Proof Submitted (Awaiting Verification)"
        VERIFIED = "VERIFIED", "Verified / Paid"
        REJECTED = "REJECTED", "Rejected / Failed"
        REFUNDED = "REFUNDED", "Refunded"

    transaction_number = models.CharField(
        max_length=32, unique=True, db_index=True, editable=False
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="payment_transactions",
    )
    gateway = models.CharField(
        max_length=20,
        choices=Gateway.choices,
        default=Gateway.MANUAL_UPI,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )

    # --- Manual QR / UPI Fields (Phase 1) ---
    utr_number = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Customer-submitted 12-digit UPI UTR / Bank Reference",
    )
    payer_upi_or_mobile = models.CharField(max_length=100, blank=True)
    payment_screenshot = models.ImageField(
        upload_to="payments/proofs/", null=True, blank=True
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_transactions",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    admin_remarks = models.TextField(blank=True)

    # --- Razorpay Fields (Phase 2 Plug-in Ready) ---
    gateway_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    gateway_payment_id = models.CharField(max_length=100, blank=True, db_index=True)
    gateway_signature = models.CharField(max_length=255, blank=True)
    gateway_raw_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_payment_transaction"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            date_str = timezone.now().strftime("%Y%m%d")
            suffix = uuid.uuid4().hex[:6].upper()
            self.transaction_number = f"TXN-{date_str}-{suffix}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_number} - {self.order.order_number} ({self.status})"