from rest_framework import serializers
from payments.models import PaymentSetting, PaymentTransaction


class PaymentSettingPublicSerializer(serializers.ModelSerializer):
    """Returned to customers/public at checkout (hides internal admin flags)."""

    class Meta:
        model = PaymentSetting
        fields = [
            "id",
            "label",
            "upi_id",
            "upi_mobile_number",
            "account_holder_name",
            "qr_code_image",
            "payment_instructions",
            "is_manual_upi_enabled",
            "is_razorpay_enabled",
            "updated_at",
        ]


class PaymentSettingAdminSerializer(serializers.ModelSerializer):
    """Used by Admin to create/update QR code, UPI ID, mobile number, and gateway toggles."""

    class Meta:
        model = PaymentSetting
        fields = [
            "id",
            "label",
            "upi_id",
            "upi_mobile_number",
            "account_holder_name",
            "qr_code_image",
            "payment_instructions",
            "is_manual_upi_enabled",
            "is_razorpay_enabled",
            "is_active",
            "updated_at",
        ]


class InitiatePaymentSerializer(serializers.Serializer):
    order_number = serializers.CharField(max_length=32)
    gateway = serializers.ChoiceField(
        choices=PaymentTransaction.Gateway.choices,
        default=PaymentTransaction.Gateway.MANUAL_UPI,
    )


class SubmitPaymentProofSerializer(serializers.Serializer):
    transaction_number = serializers.CharField(max_length=32)
    utr_number = serializers.CharField(max_length=100)
    payer_upi_or_mobile = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    payment_screenshot = serializers.ImageField(required=False, allow_null=True)


class AdminVerifyPaymentSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    admin_remarks = serializers.CharField(required=False, allow_blank=True, default="")


class PaymentTransactionSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    order_payment_status = serializers.CharField(source="order.payment_status", read_only=True)
    customer_email = serializers.EmailField(source="user.email", read_only=True)
    verified_by_email = serializers.EmailField(
        source="verified_by.email", read_only=True, default=None
    )

    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "transaction_number",
            "order",
            "order_number",
            "order_payment_status",
            "customer_email",
            "gateway",
            "status",
            "amount",
            "utr_number",
            "payer_upi_or_mobile",
            "payment_screenshot",
            "verified_by_email",
            "verified_at",
            "admin_remarks",
            "gateway_order_id",
            "gateway_payment_id",
            "created_at",
            "updated_at",
        ]
