from urllib.parse import quote
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from orders.models import Order
from payments.models import PaymentSetting, PaymentTransaction


class PaymentService:
    @staticmethod
    def get_active_setting() -> PaymentSetting | None:
        return PaymentSetting.objects.filter(is_active=True).first()

    @staticmethod
    def build_upi_intent_url(setting: PaymentSetting, order: Order, txn: PaymentTransaction) -> str:
        """Generates a mobile UPI deep-link with pre-filled amount and TXN reference."""
        if not setting or not setting.upi_id:
            return ""
        payee_name = quote(setting.account_holder_name or "SKM Electronics")
        note = quote(f"{order.order_number} ({txn.transaction_number})")
        return (
            f"upi://pay?pa={setting.upi_id}&pn={payee_name}"
            f"&am={order.total_amount}&tn={note}&cu=INR"
        )

    @staticmethod
    @transaction.atomic
    def initiate_payment(
        order: Order, user, gateway: str = PaymentTransaction.Gateway.MANUAL_UPI
    ) -> dict:
        setting = PaymentService.get_active_setting()
        
        if gateway == PaymentTransaction.Gateway.MANUAL_UPI:
            if setting and not setting.is_manual_upi_enabled:
                raise ValidationError("Manual UPI payment is currently disabled.")
        elif gateway == PaymentTransaction.Gateway.RAZORPAY:
            if not setting or not setting.is_razorpay_enabled:
                raise ValidationError("Razorpay payment is not enabled yet.")

        txn = PaymentTransaction.objects.create(
            order=order,
            user=user,
            gateway=gateway,
            status=PaymentTransaction.Status.PENDING,
            amount=order.total_amount,
        )
        order.payment_status=order.PaymentStatus.INITIATE
        order.save(update_fields=["payment_status", "updated_at"])

        if gateway == PaymentTransaction.Gateway.MANUAL_UPI:
            return {
                "transaction_number": txn.transaction_number,
                "order_number": order.order_number,
                "gateway": txn.gateway,
                "status": txn.status,
                "payment_status": order.payment_status,
                "amount": str(txn.amount),
                "payment_details": {
                    "label": setting.label if setting else "SKM Electronics UPI",
                    "account_holder_name": setting.account_holder_name if setting else "SKM Electronics",
                    "upi_id": setting.upi_id if setting else "",
                    "upi_mobile_number": setting.upi_mobile_number if setting else "",
                    "qr_code_image": setting.qr_code_image.url if (setting and setting.qr_code_image) else None,
                    "instructions": setting.payment_instructions if setting else "",
                    "upi_intent_url": PaymentService.build_upi_intent_url(setting, order, txn),
                },
            }

        # --- Phase 2: Razorpay Hook ---
        # import razorpay
        # client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        # rzp_order = client.order.create({
        #     "amount": int(order.total_amount * 100),  # paise
        #     "currency": "INR",
        #     "receipt": txn.transaction_number,
        # })
        # txn.gateway_order_id = rzp_order["id"]
        # txn.save(update_fields=["gateway_order_id"])
        # return {
        #     "transaction_number": txn.transaction_number,
        #     "order_number": order.order_number,
        #     "gateway": txn.gateway,
        #     "amount": str(txn.amount),
        #     "razorpay_order_id": rzp_order["id"],
        #     "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        # }

    @staticmethod
    @transaction.atomic
    def submit_manual_proof(
        txn: PaymentTransaction,
        utr_number: str,
        payer_upi_or_mobile: str = "",
        payment_screenshot=None,
    ) -> PaymentTransaction:
        if txn.gateway != PaymentTransaction.Gateway.MANUAL_UPI:
            raise ValidationError("Proof submission is only valid for Manual UPI transactions.")

        if txn.status == PaymentTransaction.Status.VERIFIED:
            raise ValidationError("This payment is already verified.")

        utr_clean = utr_number.strip().upper()
        if not utr_clean:
            raise ValidationError("UTR / Transaction reference number is required.")

        # Prevent duplicate UTR reuse across different transactions
        duplicate_exists = (
            PaymentTransaction.objects.filter(
                utr_number__iexact=utr_clean,
                status__in=[
                    PaymentTransaction.Status.SUBMITTED,
                    PaymentTransaction.Status.VERIFIED,
                ],
            )
            .exclude(pk=txn.pk)
            .exists()
        )
        if duplicate_exists:
            raise ValidationError("This UTR / Reference number has already been submitted for another payment.")

        txn.utr_number = utr_clean
        txn.payer_upi_or_mobile = payer_upi_or_mobile.strip()
        if payment_screenshot:
            txn.payment_screenshot = payment_screenshot
        txn.status = PaymentTransaction.Status.PENDING_VERIFICATION
        txn.save()
        txn.order.payment_status=Order.PaymentStatus.PENDING_VERIFICATION
        txn.order.save(update_fields=["payment_status", "updated_at"])
        return txn

    @staticmethod
    @transaction.atomic
    def verify_manual_payment(
        txn: PaymentTransaction, admin_user, approve: bool, admin_remarks: str = ""
    ) -> PaymentTransaction:
        if txn.status == PaymentTransaction.Status.VERIFIED and approve:
            raise ValidationError("Transaction is already verified.")

        txn.verified_by = admin_user
        txn.verified_at = timezone.now()
        txn.admin_remarks = admin_remarks.strip()

        order = txn.order
        if approve:
            txn.status = PaymentTransaction.Status.VERIFIED
            order.payment_status = Order.PaymentStatus.PAID
            if order.status == Order.Status.PENDING:
                order.status = Order.Status.CONFIRMED
        else:
            txn.status = PaymentTransaction.Status.REJECTED
            order.payment_status = Order.PaymentStatus.FAILED

        txn.save()
        order.save(update_fields=["payment_status", "status", "updated_at"])
        return txn
