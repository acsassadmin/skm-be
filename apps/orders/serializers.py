from decimal import Decimal, ROUND_HALF_UP
from rest_framework import serializers
from catalogue.models import Product
from django.db import transaction
from .models import Cart, CartItem, Coupon, Order, OrderItem, Refund,ReturnItem,ReturnRequest
from .services.cart_service import is_user_dealer, calculate_coupon_discount


class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = "__all__"
        read_only_fields = ["id", "used_count", "created_at"]

    def validate(self, attrs):
        valid_from = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        valid_until = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if valid_from and valid_until and valid_until <= valid_from:
            raise serializers.ValidationError({"valid_until": "End date must be after start date."})

        discount_type = attrs.get("discount_type", getattr(self.instance, "discount_type", None))
        discount_value = attrs.get("discount_value", getattr(self.instance, "discount_value", None))
        if discount_type == Coupon.DiscountType.PERCENTAGE and discount_value and discount_value > 100:
            raise serializers.ValidationError({"discount_value": "Percentage discount cannot exceed 100%."})

        return attrs




class CartItemSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source="product.id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    stock_quantity = serializers.IntegerField(source="product.stock_quantity", read_only=True)
    gst_rate = serializers.DecimalField(
        source="product.gst_rate", max_digits=5, decimal_places=2, read_only=True
    )
    pricing_tier = serializers.SerializerMethodField()
    unit_price = serializers.SerializerMethodField()
    line_subtotal = serializers.SerializerMethodField()
    line_gst = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = [
            "id",
            "product_id",
            "product_name",
            "sku",
            "quantity",
            "stock_quantity",
            "in_stock",
            "pricing_tier",
            "unit_price",
            "gst_rate",
            "line_subtotal",
            "line_gst",
            "line_total",
        ]

    def _is_dealer(self):
        request = self.context.get("request")
        return is_user_dealer(request.user) if request else False

    def get_pricing_tier(self, obj):
        if self._is_dealer() and obj.product.dealer_price is not None:
            return "DEALER"
        return "CUSTOMER"

    def get_unit_price(self, obj):
        return obj.get_unit_price(self._is_dealer())

    def get_line_subtotal(self, obj):
        unit_price = self.get_unit_price(obj)
        return (unit_price * obj.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def get_line_gst(self, obj):
        line_sub = self.get_line_subtotal(obj)
        gst_rate = Decimal(obj.product.gst_rate or 0)
        return (line_sub * gst_rate / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def get_line_total(self, obj):
        return (self.get_line_subtotal(obj) + self.get_line_gst(obj)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def get_in_stock(self, obj):
        return obj.product.is_active and obj.product.stock_quantity >= obj.quantity


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    coupon_code = serializers.CharField(
        source="applied_coupon.code", read_only=True, default=None
    )
    pricing_tier = serializers.SerializerMethodField()
    total_items = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    discount_amount = serializers.SerializerMethodField()
    taxable_amount = serializers.SerializerMethodField()
    estimated_gst = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = [
            "id",
            "pricing_tier",
            "coupon_code",
            "total_items",
            "items",
            "subtotal",
            "discount_amount",
            "taxable_amount",
            "estimated_gst",
            "grand_total",
            "updated_at",
        ]

    def _is_dealer(self):
        request = self.context.get("request")
        return is_user_dealer(request.user) if request else False

    def get_pricing_tier(self, obj):
        return "DEALER" if self._is_dealer() else "CUSTOMER"

    def get_total_items(self, obj):
        return sum(item.quantity for item in obj.items.all())

    def _compute_totals(self, obj):
        if hasattr(self, "_cached_totals"):
            return self._cached_totals

        is_dealer = self._is_dealer()
        subtotal = Decimal("0.00")
        raw_gst = Decimal("0.00")

        for item in obj.items.select_related("product").all():
            unit_price = item.get_unit_price(is_dealer)
            line_sub = unit_price * item.quantity
            gst_rate = Decimal(item.product.gst_rate or 0)
            subtotal += line_sub
            raw_gst += line_sub * gst_rate / Decimal("100")

        subtotal = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discount = calculate_coupon_discount(obj.applied_coupon, subtotal)
        taxable = max(subtotal - discount, Decimal("0.00"))

        # Proportionally adjust GST if a coupon discount was applied
        if subtotal > 0 and discount > 0:
            discount_ratio = taxable / subtotal
            estimated_gst = (raw_gst * discount_ratio).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            estimated_gst = raw_gst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        grand_total = (taxable + estimated_gst).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        self._cached_totals = {
            "subtotal": subtotal,
            "discount": discount,
            "taxable": taxable,
            "estimated_gst": estimated_gst,
            "grand_total": grand_total,
        }
        return self._cached_totals

    def get_subtotal(self, obj):
        return self._compute_totals(obj)["subtotal"]

    def get_discount_amount(self, obj):
        return self._compute_totals(obj)["discount"]

    def get_taxable_amount(self, obj):
        return self._compute_totals(obj)["taxable"]

    def get_estimated_gst(self, obj):
        return self._compute_totals(obj)["estimated_gst"]

    def get_grand_total(self, obj):
        return self._compute_totals(obj)["grand_total"]


class CartAddItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class CartUpdateSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(required=False)
    quantity = serializers.IntegerField(min_value=0, required=False)
    coupon_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = "__all__"
        read_only_fields = ["id", "order"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = "__all__"
        read_only_fields = [
            "id",
            "order_number",
            "user",
            "subtotal_amount",
            "discount_amount",
            "tax_amount",
            "shipping_amount",
            "total_amount",
            "created_at",
            "updated_at",
        ]


class ReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="order_item.product_name", read_only=True)
    order_item_id = serializers.PrimaryKeyRelatedField(
        source="order_item",
        queryset=OrderItem.objects.all(),
    )

    class Meta:
        model = ReturnItem
        fields = [
            "id",
            "order_item_id",
            "product_name",
            "quantity",
            "item_condition",
        ]
        read_only_fields = ["id", "product_name"]

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            if "order_item_id" not in data and "order_item" in data:
                data["order_item_id"] = data["order_item"]
        return super().to_internal_value(data)


class ReturnRequestSerializer(serializers.ModelSerializer):
    order_id = serializers.PrimaryKeyRelatedField(
        source="order",
        queryset=Order.objects.all(),
    )
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    items = ReturnItemSerializer(many=True)

    class Meta:
        model = ReturnRequest
        fields = [
            "id",
            "return_number",
            "order_id",
            "order_number",
            "status",
            "reason",
            "customer_notes",
            "admin_notes",
            "restock_approved",
            "requested_at",
            "completed_at",
            "updated_at",
            "items",
        ]
        read_only_fields = [
            "id",
            "return_number",
            "requested_at",
            "completed_at",
            "updated_at",
        ]

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            if "order_id" not in data and "order" in data:
                data["order_id"] = data["order"]
        return super().to_internal_value(data)

    def validate(self, attrs):
        order = attrs.get("order") or getattr(self.instance, "order", None)
        items = attrs.get("items")

        if items is not None and len(items) == 0:
            raise serializers.ValidationError({"items": "At least one return item is required."})

        if items and order:
            order_ref = getattr(order, "order_number", None) or f"#{order.id}"
            for item_data in items:
                order_item = item_data["order_item"]
                qty = item_data["quantity"]

                if order_item.order_id != order.id:
                    raise serializers.ValidationError(
                        {"items": f"OrderItem #{order_item.id} does not belong to order {order_ref}."}
                    )

                if qty > order_item.quantity:
                    raise serializers.ValidationError(
                        {
                            "items": (
                                f"Return quantity ({qty}) for {order_item.product_name} "
                                f"cannot exceed ordered quantity ({order_item.quantity})."
                            )
                        }
                    )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        return_request = ReturnRequest.objects.create(**validated_data)

        for item_data in items_data:
            ReturnItem.objects.create(return_request=return_request, **item_data)

        return return_request

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                ReturnItem.objects.create(return_request=instance, **item_data)

        return instance


class RefundSerializer(serializers.ModelSerializer):
    order_id = serializers.PrimaryKeyRelatedField(
        source="order",
        queryset=Order.objects.all(),
    )
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    return_request_id = serializers.PrimaryKeyRelatedField(
        source="return_request",
        queryset=ReturnRequest.objects.all(),
        required=False,
        allow_null=True,
    )
    return_number = serializers.CharField(
        source="return_request.return_number",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Refund
        fields = [
            "id",
            "refund_number",
            "order_id",
            "order_number",
            "return_request_id",
            "return_number",
            "status",
            "refund_method",
            "subtotal_refund",
            "tax_refund",
            "amount",
            "gateway_refund_id",
            "failure_reason",
            "processed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "refund_number",
            "processed_at",
            "created_at",
            "updated_at",
        ]

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            if "order_id" not in data and "order" in data:
                data["order_id"] = data["order"]
            if "return_request_id" not in data and "return_request" in data:
                data["return_request_id"] = data["return_request"]
        return super().to_internal_value(data)

    def validate(self, attrs):
        order = attrs.get("order") or getattr(self.instance, "order", None)
        return_request = attrs.get("return_request")
        if return_request is None and self.instance is not None:
            return_request = self.instance.return_request

        if return_request and order and return_request.order_id != order.id:
            raise serializers.ValidationError(
                {"return_request_id": "Return request does not belong to the selected order."}
            )

        subtotal = attrs.get("subtotal_refund")
        if subtotal is None and self.instance is not None:
            subtotal = self.instance.subtotal_refund
        subtotal = subtotal if subtotal is not None else Decimal("0.00")

        tax = attrs.get("tax_refund")
        if tax is None and self.instance is not None:
            tax = self.instance.tax_refund
        tax = tax if tax is not None else Decimal("0.00")

        amount = attrs.get("amount")
        if amount is None and self.instance is not None:
            amount = self.instance.amount

        if subtotal < Decimal("0.00") or tax < Decimal("0.00"):
            raise serializers.ValidationError("Refund amounts cannot be negative.")

        if amount is not None and amount < Decimal("0.00"):
            raise serializers.ValidationError({"amount": "Total refund amount cannot be negative."})

        if "amount" not in attrs and self.instance is None:
            attrs["amount"] = subtotal + tax

        return attrs