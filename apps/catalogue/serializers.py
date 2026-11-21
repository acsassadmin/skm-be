from rest_framework import serializers
from .models import *
from django.db import transaction
import json

class CategorySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source="parent.name", read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent", "parent_name", "description", "image", "is_active", "created_at"]
        read_only_fields = ["id", "slug", "created_at"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "product", "image", "alt_text", "is_primary", "display_order"]


class ProductVideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVideo
        fields = ["id", "product", "title", "video_url", "video_file"]

    def validate(self, attrs):
        if not attrs.get("video_url") and not attrs.get("video_file"):
            raise serializers.ValidationError("Provide either a video_url or a video_file.")
        return attrs


class ProductSerializer(serializers.ModelSerializer):
    # Read-only nested media & computed RBAC price
    images = ProductImageSerializer(many=True, read_only=True)
    videos = ProductVideoSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    applicable_price = serializers.SerializerMethodField()

    # Write-only nested media inputs (for form-data POST / PUT)
    uploaded_images = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False,
    )
    uploaded_videos = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
    )
    video_urls = serializers.ListField(
        child=serializers.URLField(),
        write_only=True,
        required=False,
    )
    delete_image_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )
    delete_video_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = ["id", "slug", "created_at"]

    def validate_specifications(self, value):
        # Parses JSON string when submitted via multipart/form-data
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError("Specifications must be valid JSON.")
        return value

    def get_applicable_price(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_approved and user.has_role("DEALER"):
            return str(obj.dealer_price)
        return str(obj.customer_price)

    # def to_representation(self, instance):
    #     data = super().to_representation(instance)
    #     request = self.context.get("request")
    #     user = getattr(request, "user", None)

    #     # Hide wholesale dealer_price from public visitors & non-dealers (except ADMIN)
    #     can_see_dealer = bool(
    #         user
    #         and user.is_authenticated
    #         and (
    #             user.is_superuser
    #             or user.has_role("ADMIN")
    #             or (user.is_approved and user.has_role("DEALER"))
    #         )
    #     )
    #     if not can_see_dealer:
    #         data.pop("dealer_price", None)
    #     return data
    def to_representation(self, instance):
        data = super().to_representation(instance)
        specs = data.get("specifications")
        if isinstance(specs, dict):
            data["specifications"] = [
                {"key": k, "value": v} for k, v in specs.items()
            ]
        return data

    def _attach_media(self, product, uploaded_images, uploaded_videos, video_urls):
        if uploaded_images:
            has_primary = product.images.filter(is_primary=True).exists()
            ProductImage.objects.bulk_create([
                ProductImage(
                    product=product,
                    image=img,
                    is_primary=(not has_primary and idx == 0),
                    sort_order=idx,
                )
                for idx, img in enumerate(uploaded_images)
            ])

        if uploaded_videos:
            ProductVideo.objects.bulk_create([
                ProductVideo(product=product, video_file=vid)
                for idx, vid in enumerate(uploaded_videos)
            ])

        if video_urls:
            ProductVideo.objects.bulk_create([
                ProductVideo(product=product, video_url=url)
                for idx, url in enumerate(video_urls)
            ])

    @transaction.atomic
    def create(self, validated_data):
        uploaded_images = validated_data.pop("uploaded_images", [])
        uploaded_videos = validated_data.pop("uploaded_videos", [])
        video_urls = validated_data.pop("video_urls", [])
        validated_data.pop("delete_image_ids", None)
        validated_data.pop("delete_video_ids", None)

        product = Product.objects.create(**validated_data)
        self._attach_media(product, uploaded_images, uploaded_videos, video_urls)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        uploaded_images = validated_data.pop("uploaded_images", [])
        uploaded_videos = validated_data.pop("uploaded_videos", [])
        video_urls = validated_data.pop("video_urls", [])
        delete_image_ids = validated_data.pop("delete_image_ids", [])
        delete_video_ids = validated_data.pop("delete_video_ids", [])

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if delete_image_ids:
            ProductImage.objects.filter(product=instance, id__in=delete_image_ids).delete()
        if delete_video_ids:
            ProductVideo.objects.filter(product=instance, id__in=delete_video_ids).delete()

        self._attach_media(instance, uploaded_images, uploaded_videos, video_urls)
        return instance

class WarrantySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    order_number = serializers.CharField(
        source="order_item.order.order_number",
        read_only=True,
        default=None,
    )

    class Meta:
        model = Warranty
        fields = "__all__"
        
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        start_date = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end_date = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError("end_date cannot be earlier than start_date.")
        return attrs


class WarrantyClaimSerializer(serializers.ModelSerializer):
    warranty_serial = serializers.CharField(
        source="warranty.serial_number",
        read_only=True,
    )
    product_sku = serializers.CharField(
        source="warranty.product.sku",
        read_only=True,
    )

    class Meta:
        model = WarrantyClaim
        fields = "__all__"
        
        read_only_fields = ["id", "claim_number", "reported_at"]

    def validate(self, attrs):
        resolution = attrs.get("resolution", getattr(self.instance, "resolution", None))
        replacement_serial = attrs.get(
            "replacement_serial",
            getattr(self.instance, "replacement_serial", ""),
        )
        if resolution == WarrantyClaim.Resolution.REPLACED and not replacement_serial:
            raise serializers.ValidationError(
                "replacement_serial is required when resolution is REPLACED."
            )
        return attrs

class WarrantySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    order_number = serializers.CharField(
        source="order_item.order.order_number",
        read_only=True,
        default=None,
    )

    class Meta:
        model = Warranty
        fields = "__all__"
        
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        start_date = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end_date = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError("end_date cannot be earlier than start_date.")
        return attrs


class WarrantyClaimSerializer(serializers.ModelSerializer):
    warranty_serial = serializers.CharField(
        source="warranty.serial_number",
        read_only=True,
    )
    product_sku = serializers.CharField(
        source="warranty.product.sku",
        read_only=True,
    )

    class Meta:
        model = WarrantyClaim
        fields = "__all__"
        
        read_only_fields = ["id", "claim_number", "reported_at"]

    def validate(self, attrs):
        resolution = attrs.get("resolution", getattr(self.instance, "resolution", None))
        replacement_serial = attrs.get(
            "replacement_serial",
            getattr(self.instance, "replacement_serial", ""),
        )
        if resolution == WarrantyClaim.Resolution.REPLACED and not replacement_serial:
            raise serializers.ValidationError(
                "replacement_serial is required when resolution is REPLACED."
            )
        return attrs


class InventoryLogSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    performed_by_email = serializers.EmailField(
        source="performed_by.email", read_only=True, default=None
    )

    class Meta:
        model = InventoryLog
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "transaction_type",
            "quantity_change",
            "stock_before",
            "stock_after",
            "reference_id",
            "notes",
            "performed_by",
            "performed_by_email",
            "created_at",
        ]
        read_only_fields = fields


class StockAdjustmentInputSerializer(serializers.Serializer):
    ALLOWED_MANUAL_TYPES = [
        InventoryLog.TransactionType.RESTOCK,
        InventoryLog.TransactionType.ADJUSTMENT,
        InventoryLog.TransactionType.DAMAGED,
    ]

    product_id = serializers.IntegerField()
    transaction_type = serializers.ChoiceField(choices=ALLOWED_MANUAL_TYPES)
    quantity_change = serializers.IntegerField()
    reference_id = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        tx_type = attrs["transaction_type"]
        qty = attrs["quantity_change"]

        if qty == 0:
            raise serializers.ValidationError({"quantity_change": "Quantity change cannot be zero."})

        if tx_type == InventoryLog.TransactionType.RESTOCK and qty < 0:
            raise serializers.ValidationError(
                {"quantity_change": "RESTOCK must be a positive integer."}
            )

        if tx_type == InventoryLog.TransactionType.DAMAGED and qty > 0:
            # Auto-convert positive input to negative deduction for convenience
            attrs["quantity_change"] = -qty

        return attrs


class LowStockProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    stock_status = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "brand",
            "category_name",
            "stock_quantity",
            "low_stock_threshold",
            "stock_status",
            "is_active",
            "updated_at",
        ]

    def get_stock_status(self, obj):
        return "OUT_OF_STOCK" if obj.stock_quantity == 0 else "LOW_STOCK"