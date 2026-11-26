from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import ValidationError

from core.cache_constants import  CacheKeys, CacheTTL
from core.cache_hooks import CacheHook
from utils.pagination import StandardPagination
from utils.permissions import HasModulePermission
from utils.responses import success_response, error_response
from core.schema import auto_schema
from utils.filters import apply_search_and_filters

from orders.models import Order
from payments.models import PaymentSetting, PaymentTransaction
from payments.serializers import (
    PaymentSettingPublicSerializer,
    PaymentSettingAdminSerializer,
    InitiatePaymentSerializer,
    SubmitPaymentProofSerializer,
    AdminVerifyPaymentSerializer,
    PaymentTransactionSerializer,
)
from payments.services.payment_service import PaymentService


class PaymentSettingView(APIView):
    """
    GET  /api/payments/settings/       -> Active QR code, UPI ID, mobile & enabled gateways (cached)
    POST /api/payments/settings/       -> Admin creates new QR/UPI configuration
    PUT  /api/payments/settings/?id=1  -> Admin updates QR code, UPI ID, mobile, or Razorpay toggle
    """

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        method_map = {
            "GET": [AllowAny()],
            # "POST": [IsAuthenticated(), HasModulePermission.for_module("Orders", "is_upload")],
            "PUT": [IsAuthenticated(), HasModulePermission.for_module("Orders", "is_update")],
        }
        return method_map.get(self.request.method, [IsAuthenticated()])

    @auto_schema(
        summary="Get active payment settings (QR code, UPI ID, mobile number, enabled gateways)",
        response=PaymentSettingPublicSerializer,
    )
    @CacheHook.cache_api_response(
        namespace=CacheKeys.PAYMENT_SETTINGS,
        timeout=CacheTTL.LONG,
    )
    def get(self, request):
        setting = PaymentService.get_active_setting()
        if not setting:
            return error_response(
                message="No active payment configuration found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return success_response(
            data=PaymentSettingPublicSerializer(setting, context={"request": request}).data,
            message="Payment settings fetched successfully.",
            status_code=status.HTTP_200_OK,
        )

    @auto_schema(
        summary="Create payment setting (QR code, UPI ID, mobile number, gateway toggles)",
        request=PaymentSettingAdminSerializer,
        response=PaymentSettingAdminSerializer,
    )
    def post(self, request):
        serializer = PaymentSettingAdminSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return error_response(
                message="Invalid payment setting data.",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        setting = serializer.save(updated_by=request.user, is_active=True)
        CacheHook.bump_version(CacheKeys.PAYMENT_SETTINGS)
        return success_response(
            data=PaymentSettingAdminSerializer(setting, context={"request": request}).data,
            message="Payment settings created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    @auto_schema(
        summary="Update active or specific payment setting by ID",
        params={"id": int},
        request=PaymentSettingAdminSerializer,
        response=PaymentSettingAdminSerializer,
    )
    def put(self, request):
        setting_id = request.query_params.get("id")
        setting = (
            PaymentSetting.objects.filter(id=setting_id).first()
            if setting_id
            else PaymentService.get_active_setting()
        )
        if not setting:
            return error_response(
                message="Payment setting not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = PaymentSettingAdminSerializer(
            setting, data=request.data, partial=True, context={"request": request}
        )
        if not serializer.is_valid():
            return error_response(
                message="Invalid payment setting data.",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        setting = serializer.save(updated_by=request.user)
        CacheHook.bump_version(CacheKeys.PAYMENT_SETTINGS)
        return success_response(
            data=PaymentSettingAdminSerializer(setting, context={"request": request}).data,
            message="Payment settings updated successfully.",
            status_code=status.HTTP_200_OK,
        )


class InitiatePaymentView(APIView):
    """
    POST /api/payments/initiate/
    Body: {"order_number": "ORD-20261123-ABC123", "gateway": "MANUAL_UPI"}
    """

    permission_classes = [IsAuthenticated]

    @auto_schema(
        summary="Initiate payment for a pending order (returns QR/UPI details or Razorpay order)",
        request=InitiatePaymentSerializer,
    )
    def post(self, request):
        serializer = InitiatePaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid payment initiation request.",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        order_number = serializer.validated_data["order_number"].strip()
        gateway = serializer.validated_data["gateway"]

        order = Order.objects.filter(order_number=order_number, user=request.user).first()
        if not order:
            return error_response(
                message="Order not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if order.payment_status == Order.PaymentStatus.PAID:
            return error_response(
                message="Order is already paid.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = PaymentService.initiate_payment(
                order=order, user=request.user, gateway=gateway
            )
        except ValidationError as exc:
            msg = exc.detail[0] if isinstance(exc.detail, list) else str(exc.detail)
            return error_response(message=msg, status_code=status.HTTP_400_BAD_REQUEST)

        return success_response(
            data=payload,
            message="Payment initiated successfully.",
            status_code=status.HTTP_201_CREATED,
        )


class SubmitPaymentProofView(APIView):
    """
    POST /api/payments/submit-proof/
    Multipart/Form-Data: transaction_number, utr_number, payer_upi_or_mobile, payment_screenshot
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @auto_schema(
        summary="Submit manual UPI UTR reference and payment screenshot",
        request=SubmitPaymentProofSerializer,
        response=PaymentTransactionSerializer,
    )
    def post(self, request):
        serializer = SubmitPaymentProofSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid payment proof submission.",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        txn = PaymentTransaction.objects.filter(
            transaction_number=data["transaction_number"],
            user=request.user,
        ).first()

        if not txn:
            return error_response(
                message="Payment transaction not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            txn = PaymentService.submit_manual_proof(
                txn=txn,
                utr_number=data["utr_number"],
                payer_upi_or_mobile=data.get("payer_upi_or_mobile", ""),
                payment_screenshot=data.get("payment_screenshot"),
            )
        except ValidationError as exc:
            msg = exc.detail[0] if isinstance(exc.detail, list) else str(exc.detail)
            return error_response(message=msg, status_code=status.HTTP_400_BAD_REQUEST)

        return success_response(
            data=PaymentTransactionSerializer(txn, context={"request": request}).data,
            message="Payment proof submitted successfully. Awaiting admin verification.",
            status_code=status.HTTP_200_OK,
        )
class PaymentTransactionView(APIView):
    """
    GET /api/payments/transactions/
    GET /api/payments/transactions/?id=12
    GET /api/payments/transactions/?status=SUBMITTED&gateway=MANUAL_UPI&search=ORD-2026&start_date=2026-11-01&end_date=2026-11-23
    """

    pagination_class = StandardPagination
    permission_classes = [IsAuthenticated]

    @auto_schema(
        summary="Get payment transactions (staff sees all with filters; customers see their own)",
        params={
            "id": int,
            "status": str,
            "gateway": str,
            "order_number": str,
            "search": str,
            "start_date": str,
            "end_date": str,
            "page": int,
        },
        response=PaymentTransactionSerializer,
        many=True,
    )
    def get(self, request):
        has_staff_access = HasModulePermission.for_module("Orders", "is_view").has_permission(
            request, self
        )
        base_qs = PaymentTransaction.objects.select_related("order", "user", "verified_by")
        if not has_staff_access:
            base_qs = base_qs.filter(user=request.user)

        txn_id = request.query_params.get("id")
        if txn_id:
            txn = base_qs.filter(id=txn_id).first()
            if not txn:
                return error_response(
                    message="Payment transaction not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            return success_response(
                data=PaymentTransactionSerializer(txn, context={"request": request}).data,
                message="Payment transaction fetched successfully.",
            )

        queryset = apply_search_and_filters(
            queryset=base_qs,
            request=request,
            search_fields=[
                "transaction_number",
                "utr_number",
                "payer_upi_or_mobile",
                "gateway_payment_id",
                "order__order_number",
                "user__email",
            ],
            filter_fields={
                "status": "status",
                "gateway": "gateway",
                "order_number": "order__order_number",
            },
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = PaymentTransactionSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)


class AdminVerifyPaymentView(APIView):
    """
    PUT /api/payments/verify/?id=12
    Body: {"approve": true, "admin_remarks": "Verified in ICICI bank statement"}
    """

    permission_classes = [IsAuthenticated, HasModulePermission.for_module("Orders", "is_update")]

    @auto_schema(
        summary="Admin approve or reject a submitted manual UPI payment",
        params={"id": int},
        request=AdminVerifyPaymentSerializer,
        response=PaymentTransactionSerializer,
    )
    def put(self, request):
        txn_id = request.query_params.get("id")
        if not txn_id:
            return error_response(
                message="Query parameter 'id' is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        txn = PaymentTransaction.objects.select_related("order").filter(id=txn_id).first()
        if not txn:
            return error_response(
                message="Payment transaction not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = AdminVerifyPaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid verification payload.",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            txn = PaymentService.verify_manual_payment(
                txn=txn,
                admin_user=request.user,
                approve=serializer.validated_data["approve"],
                admin_remarks=serializer.validated_data.get("admin_remarks", ""),
            )
        except ValidationError as exc:
            msg = exc.detail if isinstance(exc.detail, list) else str(exc.detail)
            return error_response(message=msg, status_code=status.HTTP_400_BAD_REQUEST)

        CacheHook.bump_version(CacheKeys.SALES_REPORTS)

        action_label = "verified" if serializer.validated_data["approve"] else "rejected"
        return success_response(
            data=PaymentTransactionSerializer(txn, context={"request": request}).data,
            message=f"Payment transaction {action_label} successfully.",
            status_code=status.HTTP_200_OK,
        )