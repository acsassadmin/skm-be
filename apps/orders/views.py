from decimal import Decimal, InvalidOperation
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

# from utils.permissions import HasModulePermission
from orders.models import Coupon
from orders.serializers import CouponSerializer
from utils.pagination import StandardPagination
from utils.responses import error_response, success_response


def is_orders_staff(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_superuser or user.has_role("ADMIN")))


class CouponView(APIView):
    pagination_class = StandardPagination

    # def get_permissions(self):
    #     method_map = {
    #         "GET": [IsAuthenticated()],
    #         "POST": [IsAuthenticated(), HasModulePermission.for_module("Orders", "is_upload")],
    #         "PUT": [IsAuthenticated(), HasModulePermission.for_module("Orders", "is_update")],
    #         "DELETE": [IsAuthenticated(), HasModulePermission.for_module("Orders", "is_delete")],
    #     }
    #     return method_map.get(self.request.method, [IsAuthenticated()])

    def get(self, request):
        coupon_id = request.query_params.get("id")
        if coupon_id:
            coupon = Coupon.objects.filter(id=coupon_id).first()
            if not coupon:
                return error_response(message="Coupon not found.", status_code=status.HTTP_404_NOT_FOUND)
            return success_response(data=CouponSerializer(coupon).data)

        qs = Coupon.objects.all() if is_orders_staff(request.user) else Coupon.objects.filter(is_active=True)
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(code__icontains=search)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            CouponSerializer(page, many=True).data, message="Coupons retrieved successfully."
        )

    def post(self, request):
        serializer = CouponSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Invalid coupon data.")

        coupon = serializer.save()
        return success_response(
            data=CouponSerializer(coupon).data,
            message="Coupon created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def put(self, request):
        coupon_id = request.query_params.get("id")
        coupon = Coupon.objects.filter(id=coupon_id).first()
        if not coupon:
            return error_response(message="Coupon not found.", status_code=status.HTTP_404_NOT_FOUND)

        serializer = CouponSerializer(coupon, data=request.data, partial=True)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Coupon update failed.")

        serializer.save()
        return success_response(data=serializer.data, message="Coupon updated successfully.")

    def delete(self, request):
        coupon_id = request.query_params.get("id")
        coupon = Coupon.objects.filter(id=coupon_id).first()
        if not coupon:
            return error_response(message="Coupon not found.", status_code=status.HTTP_404_NOT_FOUND)

        coupon.delete()
        return success_response(message="Coupon deleted successfully.")


class CouponValidateView(APIView):
    """Allows customers/dealers to preview discount on a cart subtotal before checkout."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        code = str(request.data.get("code", "")).strip()
        raw_subtotal = request.data.get("subtotal")

        if not code or raw_subtotal is None:
            return error_response(
                errors={"code": "Coupon code and subtotal are required."},
                message="Missing validation parameters.",
            )

        try:
            subtotal = Decimal(str(raw_subtotal))
        except InvalidOperation:
            return error_response(errors={"subtotal": "Invalid numeric subtotal."}, message="Validation failed.")

        coupon = Coupon.objects.filter(code__iexact=code).first()
        if not coupon:
            return error_response(message="Invalid coupon code.", status_code=status.HTTP_404_NOT_FOUND)

        is_valid, reason = coupon.is_valid_for_amount(subtotal)
        if not is_valid:
            return error_response(message=reason, status_code=status.HTTP_400_BAD_REQUEST)

        discount = coupon.calculate_discount(subtotal)
        return success_response(
            data={
                "code": coupon.code,
                "discount_type": coupon.discount_type,
                "discount_value": str(coupon.discount_value),
                "subtotal": str(subtotal),
                "discount_amount": str(discount),
                "final_subtotal": str(subtotal - discount),
            },
            message="Coupon applied successfully.",
        )
