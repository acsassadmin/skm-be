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

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from catalogue.models import Product
from utils.responses import success_response, error_response
from .models import Cart, CartItem, Coupon
from .serializers import (
    CartSerializer,
    CartAddItemSerializer,
    CartUpdateSerializer,
)


class CartView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_or_create_cart(self, user):
        cart, _ = Cart.objects.get_or_create(user=user)
        return cart

    def get(self, request):
        cart = self._get_or_create_cart(request.user)
        serializer = CartSerializer(cart, context={"request": request})
        return success_response(
            data=serializer.data,
            message="Cart fetched successfully.",
        )

    def post(self, request):
        """
        Add a product to the cart or increment its quantity.
        Body: { "product_id": 1, "quantity": 2 }
        """
        try:
            input_serializer = CartAddItemSerializer(data=request.data)
            input_serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

        product_id = input_serializer.validated_data["product_id"]
        quantity = input_serializer.validated_data["quantity"]

        product = Product.objects.filter(id=product_id, is_active=True).first()
        if not product:
            return error_response(
                errors={"product_id": ["Active product not found."]},
                message="Product not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        cart = self._get_or_create_cart(request.user)
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={"quantity": quantity},
        )

        new_quantity = quantity if created else cart_item.quantity + quantity
        if new_quantity > product.stock_quantity:
            if created:
                cart_item.delete()
            return error_response(
                errors={
                    "quantity": [
                        f"Only {product.stock_quantity} unit(s) available in stock."
                    ]
                },
                message="Insufficient stock.",
            )

        if not created:
            cart_item.quantity = new_quantity
            cart_item.save(update_fields=["quantity", "updated_at"])

        serializer = CartSerializer(cart, context={"request": request})
        return success_response(
            data=serializer.data,
            message="Item added to cart.",
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def put(self, request):
        """
        Update an item's quantity (quantity=0 removes it) and/or apply/remove a coupon.
        Supports ?id=<cart_item_id> or item_id in request body.
        """
        try:
            input_serializer = CartUpdateSerializer(data=request.data)
            input_serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

        cart = self._get_or_create_cart(request.user)
        data = input_serializer.validated_data

        # 1. Handle item quantity update if provided
        item_id = request.query_params.get("id") or data.get("item_id")
        if item_id is not None:
            cart_item = CartItem.objects.filter(id=item_id, cart=cart).select_related("product").first()
            if not cart_item:
                return error_response(
                    errors={"id": ["Cart item not found."]},
                    message="Cart item not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            quantity = data.get("quantity")
            if quantity is None:
                return error_response(
                    errors={"quantity": ["Quantity is required when updating an item."]},
                    message="Validation failed.",
                )

            if quantity == 0:
                cart_item.delete()
            else:
                if quantity > cart_item.product.stock_quantity:
                    return error_response(
                        errors={
                            "quantity": [
                                f"Only {cart_item.product.stock_quantity} unit(s) available in stock."
                            ]
                        },
                        message="Insufficient stock.",
                    )
                cart_item.quantity = quantity
                cart_item.save(update_fields=["quantity", "updated_at"])

        # 2. Handle coupon application or removal if coupon_code key was sent
        if "coupon_code" in request.data:
            raw_code = (data.get("coupon_code") or "").strip().upper()
            if not raw_code:
                cart.applied_coupon = None
                cart.save(update_fields=["applied_coupon", "updated_at"])
            else:
                now = timezone.now()
                coupon = Coupon.objects.filter(code__iexact=raw_code, is_active=True).first()
                if not coupon:
                    return error_response(
                        errors={"coupon_code": ["Invalid or inactive coupon code."]},
                        message="Coupon invalid.",
                    )
                if getattr(coupon, "valid_from", None) and now < coupon.valid_from:
                    return error_response(
                        errors={"coupon_code": ["This coupon is not active yet."]},
                        message="Coupon not yet valid.",
                    )
                if getattr(coupon, "valid_until", None) and now > coupon.valid_until:
                    return error_response(
                        errors={"coupon_code": ["This coupon has expired."]},
                        message="Coupon expired.",
                    )
                usage_limit = getattr(coupon, "usage_limit", None)
                used_count = getattr(coupon, "used_count", 0)
                if usage_limit is not None and used_count >= usage_limit:
                    return error_response(
                        errors={"coupon_code": ["Coupon usage limit reached."]},
                        message="Coupon limit reached.",
                    )

                cart.applied_coupon = coupon
                cart.save(update_fields=["applied_coupon", "updated_at"])

        serializer = CartSerializer(cart, context={"request": request})
        return success_response(
            data=serializer.data,
            message="Cart updated successfully.",
        )

    def delete(self, request):
        """
        Remove a single item via ?id=<cart_item_id>, or clear the entire cart if ?id= is omitted.
        """
        cart = self._get_or_create_cart(request.user)
        item_id = request.query_params.get("id")

        if item_id:
            cart_item = CartItem.objects.filter(id=item_id, cart=cart).first()
            if not cart_item:
                return error_response(
                    errors={"id": ["Cart item not found."]},
                    message="Cart item not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            cart_item.delete()
            msg = "Item removed from cart."
        else:
            cart.items.all().delete()
            cart.applied_coupon = None
            cart.save(update_fields=["applied_coupon", "updated_at"])
            msg = "Cart cleared successfully."

        serializer = CartSerializer(cart, context={"request": request})
        return success_response(
            data=serializer.data,
            message=msg,
        )
