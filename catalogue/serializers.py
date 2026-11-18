from rest_framework import serializers
from .models import Category, Product, ProductImage, ProductVideo
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
