from rest_framework import serializers
import re
from .models import *


GSTIN_REGEX = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"

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
    
    as_invoice = serializers.SerializerMethodField()
    invoice_number = serializers.SerializerMethodField()

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
        
        def get_has_invoice(self, obj):
            return hasattr(obj, "invoice")

        def get_invoice_number(self, obj):
            return obj.invoice.invoice_number if hasattr(obj, "invoice") else None


class InvoiceConfigurationSerializer(serializers.ModelSerializer):
    """Admin serializer for viewing and updating agreed invoice settings."""

    class Meta:
        model = InvoiceConfiguration
        fields = [
            "company_name",
            "company_address",
            "company_state",
            "company_state_code",
            "gstin",
            "gst_invoice_prefix",
            "gst_next_sequence",
            "non_gst_invoice_prefix",
            "non_gst_next_sequence",
            "non_gst_title",
            "terms_and_conditions",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        gstin = attrs.get("gstin", getattr(self.instance, "gstin", "")).strip().upper()

        if gstin:
            if not re.match(GSTIN_REGEX, gstin):
                raise serializers.ValidationError({"gstin": "Invalid 15-character Indian GSTIN format."})
            attrs["gstin"] = gstin
            # Auto-extract 2-digit state code from GSTIN (e.g., '33' for Tamil Nadu)
            attrs["company_state_code"] = gstin[:2]
        return attrs


class InvoiceGenerateSerializer(serializers.Serializer):
    """Validates customer's post-payment 'With GST' or 'Without GST' choice."""

    is_gst = serializers.BooleanField(default=True)
    buyer_gstin = serializers.CharField(
        max_length=15, required=False, allow_blank=True, default=""
    )
    buyer_company_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        is_gst = attrs.get("is_gst", True)
        gstin = attrs.get("buyer_gstin", "").strip().upper()
        company = attrs.get("buyer_company_name", "").strip()

        if is_gst and gstin:
            if not re.match(GSTIN_REGEX, gstin):
                raise serializers.ValidationError(
                    {"buyer_gstin": "Invalid 15-character Indian GSTIN format."}
                )
            if not company:
                raise serializers.ValidationError(
                    {"buyer_company_name": "Company name is required when providing a GSTIN."}
                )

        # Clear B2B fields if customer selected 'Without GST'
        attrs["buyer_gstin"] = gstin if is_gst else ""
        attrs["buyer_company_name"] = company if is_gst else ""
        return attrs


class InvoiceDetailSerializer(serializers.ModelSerializer):
    """Read-only serializer representing a generated invoice."""

    order_number = serializers.CharField(source="order.order_number", read_only=True)
    transaction_number = serializers.CharField(source="transaction.transaction_number", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "order_number",
            "transaction_number",
            "is_gst",
            "buyer_gstin",
            "buyer_company_name",
            "subtotal_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_tax_amount",
            "grand_total",
            "generated_at",
        ]
