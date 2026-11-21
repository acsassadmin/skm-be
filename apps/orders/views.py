from decimal import Decimal, InvalidOperation
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

# from utils.permissions import HasModulePermission
from orders.models import Coupon
from orders.serializers import CouponSerializer,OrderItemSerializer, OrderSerializer
from utils.pagination import StandardPagination
from utils.responses import error_response, success_response
from .utils.ordercalculation import *
from utils.filters import *
from django.shortcuts import get_object_or_404
from django.utils import timezone
from catalogue.models import Product
from .models import Cart, CartItem, Coupon
from .serializers import (
    CartSerializer,
    CartAddItemSerializer,
    CartUpdateSerializer,
)
from core.schema import auto_schema
from core.cache_hooks import *
from core.cache_constants import *
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

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
    @auto_schema(
        summary="Get coupons or a single coupon by ID",
        params={"id": int, "search": str, "page": int},
        response=CouponSerializer,
        many=True,
    )
    @CacheHook.cache_api_response(namespace=CacheKeys.COUPONS, timeout=CacheTTL.MEDIUM)
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

    @auto_schema(
        summary="Create a new coupon",
        request=CouponSerializer,
        response=CouponSerializer,
    )
    def post(self, request):
        serializer = CouponSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Invalid coupon data.")

        coupon = serializer.save()
        CacheHook.bump_version(CacheKeys.COUPONS)
        return success_response(
            data=CouponSerializer(coupon).data,
            message="Coupon created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    @auto_schema(
        summary="Update an existing coupon",
        params={"id*": int},
        request=CouponSerializer,
        response=CouponSerializer,
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
        CacheHook.bump_version(CacheKeys.COUPONS)
        return success_response(data=serializer.data, message="Coupon updated successfully.")
    @auto_schema(
        summary="Delete a coupon",
        params={"id*": int},
    )
    def delete(self, request):
        coupon_id = request.query_params.get("id")
        coupon = Coupon.objects.filter(id=coupon_id).first()
        if not coupon:
            return error_response(message="Coupon not found.", status_code=status.HTTP_404_NOT_FOUND)

        coupon.delete()
        CacheHook.bump_version(CacheKeys.COUPONS)
        return success_response(message="Coupon deleted successfully.")


class CouponValidateView(APIView):
    """Allows customers/dealers to preview discount on a cart subtotal before checkout."""
    permission_classes = [IsAuthenticated]
    @auto_schema(
        summary="Validate a coupon code against a cart subtotal",
        request=inline_serializer(
            name="CouponValidateRequest",
            fields={
                "code": serializers.CharField(),
                "subtotal": serializers.DecimalField(max_digits=12, decimal_places=2),
            },
        ),
    )
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


class OrderView(APIView):
    """
    GET:    ?id=<order_id> for single order, or list with ?search=&status=&payment_status=&start_date=&end_date=&page=&size=
    POST:   Create an order from the user's cart
    PUT:    Update an order via ?id=<order_id> (or body["id"])
    DELETE: Delete an order via ?id=<order_id> (or body["id"])
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def _base_queryset(self, request):
        qs = Order.objects.prefetch_related("items", "items__product").order_by("-created_at")
        if request.user.is_staff or request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)

    def _get_target_id(self, request):
        return request.query_params.get("id") or request.data.get("id")

    def get(self, request):
        qs = self._base_queryset(request)
        order_id = request.query_params.get("id")

        if order_id:
            order = get_object_or_404(qs, pk=order_id)
            serializer = OrderSerializer(order, context={"request": request})
            return success_response(
                data=serializer.data,
                message="Order retrieved successfully",
                status_code=status.HTTP_200_OK,
            )

        filtered_qs = apply_search_and_filters(
            qs,
            request,
            search_fields=[
                "order_number",
                "coupon_code",
                "shipping_full_name",
                "shipping_phone",
                "shipping_city",
            ],
            filter_fields={
                "status": "status",
                "payment_status": "payment_status",
                "is_dealer_order": "is_dealer_order",
                "coupon_code": "coupon_code",
            },
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(filtered_qs, request, view=self)
        serializer = OrderSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(
            serializer.data, message="Orders retrieved successfully"
        )

    def post(self, request):
        cart = get_object_or_404(Cart, user=request.user)
        shipping_amount = Decimal(str(request.data.get("shipping_amount", "0.00")))

        try:
            order = create_order_from_cart(
                user=request.user,
                cart=cart,
                shipping_data=request.data,
                shipping_amount=shipping_amount,
            )
        except (ValueError, KeyError) as exc:
            return error_response(
                errors={"detail": str(exc)},
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = OrderSerializer(order, context={"request": request})
        return success_response(
            data=serializer.data,
            message="Order created successfully",
            status_code=status.HTTP_201_CREATED,
        )

    def put(self, request):
        order_id = self._get_target_id(request)
        if not order_id:
            return error_response(
                errors={"id": ["This field is required."]},
                message="Query param 'id' is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        order = get_object_or_404(self._base_queryset(request), pk=order_id)
        serializer = OrderSerializer(
            order, data=request.data, partial=True, context={"request": request}
        )
        if not serializer.is_valid():
            return error_response(
                errors=serializer.errors,
                message="Validation failed",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()
        shipping_override = (
            Decimal(str(request.data["shipping_amount"]))
            if "shipping_amount" in request.data and request.data["shipping_amount"] is not None
            else None
        )
        recalculate_order_totals(order, shipping_amount=shipping_override)

        return success_response(
            data=OrderSerializer(order, context={"request": request}).data,
            message="Order updated successfully",
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request):
        order_id = self._get_target_id(request)
        if not order_id:
            return error_response(
                errors={"id": ["This field is required."]},
                message="Query param 'id' is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        order = get_object_or_404(self._base_queryset(request), pk=order_id)
        order.delete()
        return success_response(
            data={},
            message="Order deleted successfully",
            status_code=status.HTTP_200_OK,
        )


class OrderItemView(APIView):
    """
    GET:    ?id=<item_id> for single item, or list with ?order_id=&search=&start_date=&end_date=&page=&size=
    POST:   Add/set an order item using ?order_id=<order_id> (or body["order"])
    PUT:    Update an order item via ?id=<item_id> (or body["id"])
    DELETE: Delete an order item via ?id=<item_id> (or body["id"])
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def _base_queryset(self, request):
        qs = OrderItem.objects.select_related("order", "product").order_by("id")
        if request.user.is_staff or request.user.is_superuser:
            return qs
        return qs.filter(order__user=request.user)

    def _get_order(self, request, order_id):
        qs = Order.objects.all()
        if not (request.user.is_staff or request.user.is_superuser):
            qs = qs.filter(user=request.user)
        return get_object_or_404(qs, pk=order_id)

    def _get_target_id(self, request):
        return request.query_params.get("id") or request.data.get("id")

    def get(self, request):
        qs = self._base_queryset(request)
        item_id = request.query_params.get("id")

        if item_id:
            item = get_object_or_404(qs, pk=item_id)
            serializer = OrderItemSerializer(item, context={"request": request})
            return success_response(
                data=serializer.data,
                message="Order item retrieved successfully",
                status_code=status.HTTP_200_OK,
            )

        filtered_qs = apply_search_and_filters(
            qs,
            request,
            search_fields=["product_name", "product_sku", "hsn_code", "order__order_number"],
            filter_fields={
                "order_id": "order_id",
                "product_id": "product_id",
            },
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(filtered_qs, request, view=self)
        serializer = OrderItemSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(
            serializer.data, message="Order items retrieved successfully"
        )

    def post(self, request):
        order_id = request.query_params.get("order_id") or request.data.get("order")
        if not order_id:
            return error_response(
                errors={"order_id": ["This field is required."]},
                message="Query param 'order_id' is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        order = self._get_order(request, order_id)
        product_id = request.data.get("product") or request.data.get("product_id")
        product = get_object_or_404(Product, pk=product_id)
        quantity = int(request.data.get("quantity", 1))

        try:
            item = add_or_update_order_item(order=order, product=product, quantity=quantity)
        except ValueError as exc:
            return error_response(
                errors={"detail": str(exc)},
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = OrderItemSerializer(item, context={"request": request})
        return success_response(
            data=serializer.data,
            message="Order item saved successfully",
            status_code=status.HTTP_201_CREATED,
        )

    def put(self, request):
        item_id = self._get_target_id(request)
        if not item_id:
            return error_response(
                errors={"id": ["This field is required."]},
                message="Query param 'id' is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        item = get_object_or_404(self._base_queryset(request), pk=item_id)
        quantity = int(request.data.get("quantity", item.quantity))

        try:
            updated_item = add_or_update_order_item(
                order=item.order,
                product=item.product,
                quantity=quantity,
            )
        except ValueError as exc:
            return error_response(
                errors={"detail": str(exc)},
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = OrderItemSerializer(updated_item, context={"request": request})
        return success_response(
            data=serializer.data,
            message="Order item updated successfully",
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request):
        item_id = self._get_target_id(request)
        if not item_id:
            return error_response(
                errors={"id": ["This field is required."]},
                message="Query param 'id' is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        item = get_object_or_404(self._base_queryset(request), pk=item_id)
        delete_order_item(item)
        return success_response(
            data={},
            message="Order item deleted successfully",
            status_code=status.HTTP_200_OK,
        )

class OrderHistoryView(APIView):
    """
    GET: Retrieve order history for the logged-in user.
         - Single order: ?id=<order_id>
         - Paginated list: ?search=&status=&payment_status=&is_dealer_order=&coupon_code=&start_date=&end_date=&page=&size=
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get(self, request):
        qs = (
            Order.objects.filter(user=request.user)
            .prefetch_related("items", "items__product")
            .order_by("-created_at")
        )

        order_id = request.query_params.get("id")
        if order_id:
            order = get_object_or_404(qs, pk=order_id)
            serializer = OrderSerializer(order, context={"request": request})
            return success_response(
                data=serializer.data,
                message="Order history detail retrieved successfully",
                status_code=status.HTTP_200_OK,
            )

        filtered_qs = apply_search_and_filters(
            qs,
            request,
            search_fields=[
                "order_number",
                "coupon_code",
                "shipping_full_name",
                "shipping_phone",
                "shipping_city",
                "items__product_name",
                "items__product_sku",
            ],
            filter_fields={
                "status": "status",
                "payment_status": "payment_status",
                "is_dealer_order": "is_dealer_order",
                "coupon_code": "coupon_code",
            },
        ).distinct()

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(filtered_qs, request, view=self)
        serializer = OrderSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(
            serializer.data, message="Order history retrieved successfully"
        )