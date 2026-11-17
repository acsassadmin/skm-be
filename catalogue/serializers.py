from rest_framework import serializers
from .models import Category, Product, ProductImage, ProductVideo


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
    category_name = serializers.CharField(source="category.name", read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    videos = ProductVideoSerializer(many=True, read_only=True)
    in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "category", "category_name", "name", "slug", "sku", "hsn_code", "brand",
            "short_description", "description", "specifications",
            "customer_price", "dealer_price", "gst_rate",
            "stock_quantity", "low_stock_threshold", "in_stock", "warranty_months",
            "is_featured", "is_active", "images", "videos", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]

    # def to_representation(self, instance):
    #     data = super().to_representation(instance)
    #     request = self.context.get("request")
    #     user = getattr(request, "user", None)

    #     can_view_dealer = bool(
    #         user and user.is_authenticated and (
    #             user.is_superuser or user.has_role("ADMIN") or user.has_role("DEALER")
    #         )
    #     )
    #     if not can_view_dealer:
    #         data.pop("dealer_price", None)
    #     return data
