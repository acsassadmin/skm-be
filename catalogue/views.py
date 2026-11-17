from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from utils.responses import error_response, success_response
from .models import Category, Product, ProductImage, ProductVideo
from .serializers import (
    CategorySerializer,
    ProductImageSerializer,
    ProductSerializer,
    ProductVideoSerializer,
)


def is_admin_user(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_superuser or user.has_role("ADMIN")))


class CategoryView(APIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request):
        cat_id = request.query_params.get("id")
        if cat_id:
            category = Category.objects.filter(id=cat_id).first()
            if not category:
                return error_response(message="Category not found.", status_code=status.HTTP_404_NOT_FOUND)
            return success_response(data=CategorySerializer(category).data)

        queryset = Category.objects.all()
        if not is_admin_user(request.user):
            queryset = queryset.filter(is_active=True)
        return success_response(data=CategorySerializer(queryset, many=True).data)

    def post(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        serializer = CategorySerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Invalid category data.")

        category = serializer.save()
        return success_response(
            data=CategorySerializer(category).data,
            message="Category created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def put(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        cat_id = request.query_params.get("id")
        category = Category.objects.filter(id=cat_id).first()
        if not category:
            return error_response(message="Category not found.", status_code=status.HTTP_404_NOT_FOUND)

        serializer = CategorySerializer(category, data=request.data, partial=True)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Invalid category update.")

        serializer.save()
        return success_response(data=serializer.data, message="Category updated successfully.")

    def delete(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        cat_id = request.query_params.get("id")
        category = Category.objects.filter(id=cat_id).first()
        if not category:
            return error_response(message="Category not found.", status_code=status.HTTP_404_NOT_FOUND)

        category.delete()
        return success_response(message="Category deleted successfully.")


class ProductView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request):
        product_id = request.query_params.get("id")
        if product_id:
            product = Product.objects.select_related("category").prefetch_related("images", "videos").filter(id=product_id).first()
            if not product:
                return error_response(message="Product not found.", status_code=status.HTTP_404_NOT_FOUND)
            return success_response(data=ProductSerializer(product, context={"request": request}).data)

        queryset = Product.objects.select_related("category").prefetch_related("images", "videos").all()
        if not is_admin_user(request.user):
            queryset = queryset.filter(is_active=True)

        category_id = request.query_params.get("category")
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        featured = request.query_params.get("featured")
        if featured and featured.lower() == "true":
            queryset = queryset.filter(is_featured=True)

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(sku__icontains=search)
                | Q(brand__icontains=search)
                | Q(short_description__icontains=search)
                | Q(description__icontains=search)
            )

        serializer = ProductSerializer(queryset, many=True, context={"request": request})
        return success_response(data=serializer.data)

    def post(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        serializer = ProductSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Product validation failed.")

        product = serializer.save()
        return success_response(
            data=ProductSerializer(product, context={"request": request}).data,
            message="Product onboarded successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def put(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        product_id = request.query_params.get("id")
        product = Product.objects.filter(id=product_id).first()
        if not product:
            return error_response(message="Product not found.", status_code=status.HTTP_404_NOT_FOUND)

        serializer = ProductSerializer(product, data=request.data, partial=True, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Product update failed.")

        serializer.save()
        return success_response(data=serializer.data, message="Product updated successfully.")

    def delete(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        product_id = request.query_params.get("id")
        product = Product.objects.filter(id=product_id).first()
        if not product:
            return error_response(message="Product not found.", status_code=status.HTTP_404_NOT_FOUND)

        product.delete()
        return success_response(message="Product deleted successfully.")


class ProductImageView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        serializer = ProductImageSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Image upload failed.")

        img = serializer.save()
        return success_response(
            data=ProductImageSerializer(img).data,
            message="Product image uploaded successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        img_id = request.query_params.get("id")
        img = ProductImage.objects.filter(id=img_id).first()
        if not img:
            return error_response(message="Image not found.", status_code=status.HTTP_404_NOT_FOUND)

        img.delete()
        return success_response(message="Product image deleted successfully.")


class ProductVideoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        serializer = ProductVideoSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Video upload failed.")

        video = serializer.save()
        return success_response(
            data=ProductVideoSerializer(video).data,
            message="Product demo video added successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        video_id = request.query_params.get("id")
        video = ProductVideo.objects.filter(id=video_id).first()
        if not video:
            return error_response(message="Video not found.", status_code=status.HTTP_404_NOT_FOUND)

        video.delete()
        return success_response(message="Product video deleted successfully.")
