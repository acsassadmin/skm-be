from django.db.models import Q,F
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from utils.permissions import HasModulePermission
from utils.responses import error_response, success_response
from .models import Category, Product, ProductImage, ProductVideo
from .serializers import (
    CategorySerializer,
    ProductImageSerializer,
    ProductSerializer,
    ProductVideoSerializer,
    InventoryLogSerializer,
    LowStockProductSerializer,
    StockAdjustmentInputSerializer
)
from catalogue.services.excel_service import import_products_from_excel,export_products_from_db,generate_product_import_template
from django.http import HttpResponse
from utils.pagination import StandardPagination
from core.cache_constants import CacheKeys, CacheTTL
from core.cache_hooks import CacheHook
from .models import *
from catalogue.services.inventory_service import adjust_product_stock
from core.schema import auto_schema 

def is_admin_user(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_superuser or user.has_role("ADMIN")))


class CategoryView(APIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]
    @auto_schema(
        summary="Get categories or single category",
        params={"id": int},  
        response=CategorySerializer,
        many=True,
    )
    @CacheHook.cache_api_response(namespace=CacheKeys.CATEGORIES,timeout=CacheTTL.SHORT)
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

    @auto_schema(
        summary="Create category",
        request=CategorySerializer,
        response=CategorySerializer,
    )
    def post(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        serializer = CategorySerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Invalid category data.")

        category = serializer.save()
        CacheHook.bump_version(CacheKeys.CATEGORIES)
        return success_response(
            data=CategorySerializer(category).data,
            message="Category created successfully.",
            status_code=status.HTTP_201_CREATED,
        )
    @auto_schema(
        summary="Update category",
        params={"id*": int},
        request=CategorySerializer,
        response=CategorySerializer,
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
        CacheHook.bump_version(CacheKeys.CATEGORIES)
        CacheHook.bump_version(CacheKeys.PRODUCTS) 
        return success_response(data=serializer.data, message="Category updated successfully.")
    @auto_schema(
        summary="Delete category",
        params={"id*": int},
    )
    def delete(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        cat_id = request.query_params.get("id")
        category = Category.objects.filter(id=cat_id).first()
        if not category:
            return error_response(message="Category not found.", status_code=status.HTTP_404_NOT_FOUND)

        category.delete()
        CacheHook.bump_version(CacheKeys.CATEGORIES)
        CacheHook.bump_version(CacheKeys.PRODUCTS) 
        return success_response(message="Category deleted successfully.")


class ProductView(APIView):
    pagination_class=StandardPagination
    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]
    @auto_schema(
        summary="Get products",
        params={"id": int, "category": int, "featured": bool, "search": str, "page": int},
        response=ProductSerializer,
        many=True,
    )
    @CacheHook.cache_api_response(namespace=CacheKeys.PRODUCTS, timeout=CacheTTL.SHORT)
    def get(self, request):
        product_id = request.query_params.get("id")
        if product_id:
            product = (
                Product.objects.select_related("category")
                .prefetch_related("images", "videos")
                .filter(id=product_id)
                .first()
            )
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

        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ProductSerializer(paginated_queryset, many=True, context={"request": request})
        return paginator.get_paginated_response(
            serializer.data, message="Products retrieved successfully."
        )

    @auto_schema(summary="Create product", request=ProductSerializer, response=ProductSerializer)
    def post(self, request):
        serializer = ProductSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Product validation failed.")

        product = serializer.save()
        if product.stock_quantity > 0:
            InventoryLog.objects.create(
                product=product,
                transaction_type=InventoryLog.TransactionType.OPENING_STOCK,
                quantity_change=product.stock_quantity,
                stock_before=0,
                stock_after=product.stock_quantity,
                notes="Initial stock on product creation",
                performed_by=request.user,
            )
        CacheHook.bump_version(CacheKeys.PRODUCTS) #invalidate and update cache
        return success_response(
            data=ProductSerializer(product, context={"request": request}).data,
            message="Product onboarded successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    @auto_schema(
        summary="Update product",
        params={"id": int},
        request=ProductSerializer,
        response=ProductSerializer,
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
        CacheHook.bump_version(CacheKeys.PRODUCTS)#invalidate and update cache
        return success_response(data=serializer.data, message="Product updated successfully.")

    @auto_schema(
        summary="Delete product",
        params={"id": int},
    )
    def delete(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        product_id = request.query_params.get("id")
        product = Product.objects.filter(id=product_id).first()
        if not product:
            return error_response(message="Product not found.", status_code=status.HTTP_404_NOT_FOUND)

        product.delete()
        CacheHook.bump_version(CacheKeys.PRODUCTS) #invalidate and update cache
        return success_response(message="Product deleted successfully.")


class ProductImageView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        serializer = ProductImageSerializer(data=request.data,context={"request":request})
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

class ProductExcelImportView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    @auto_schema(summary="Download sample product import Excel template (.xlsx)")
    def get(self, request):
        """Download sample Excel template + guidance tab before uploading."""
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        excel_stream = generate_product_import_template()
        response = HttpResponse(
            excel_stream.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="skm_product_import_template.xlsx"'
        return response

    def post(self, request):
        """Bulk import/update products from uploaded .xlsx file."""
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        excel_file = request.FILES.get("file")
        if not excel_file:
            return error_response(
                errors={"file": "Please upload an .xlsx Excel file under the 'file' key."},
                message="No file uploaded.",
            )

        if not excel_file.name.lower().endswith(".xlsx"):
            return error_response(
                errors={"file": "Only .xlsx Excel files are supported."},
                message="Invalid file format.",
            )

        try:
            summary = import_products_from_excel(excel_file,performed_by=request.user)
        except Exception as exc:
            return error_response(
                errors={"file": str(exc)},
                message="Failed to process Excel file.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        CacheHook.bump_version(CacheKeys.PRODUCTS)
        return success_response(
            data=summary,
            message=f"Import complete: {summary['created']} created, {summary['updated']} updated, {summary['failed']} failed.",
            status_code=status.HTTP_200_OK,
        )


class ProductExcelExportView(APIView):

    
    permission_classes = [IsAuthenticated]
    @auto_schema(summary="Bulk import products from Excel (.xlsx)", files=["file*"])
    def get(self, request):
        """Export live products from the database into an .xlsx file."""
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        queryset = Product.objects.select_related("category").all()

        category_id = request.query_params.get("category")
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        is_active = request.query_params.get("is_active")
        if is_active in {"true", "false"}:
            queryset = queryset.filter(is_active=(is_active == "true"))

        excel_stream = export_products_from_db(queryset=queryset)
        response = HttpResponse(
            excel_stream.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="skm_products_export.xlsx"'
        return response
    
class InventoryView(APIView):
    """
    GET  /api/catalogue/inventory/ -> Paginated stock audit ledger
    POST /api/catalogue/inventory/ -> Manual Restock / Adjustment / Damage write-off
    """

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), HasModulePermission.for_module("Catalogue", "is_view")()]
        return [IsAuthenticated(), HasModulePermission.for_module("Catalogue", "is_update")()]
    @auto_schema(
        summary="Get inventory logs",
        params={
            "product_id": int,
            "sku": str,
            "transaction_type": str,
            "reference_id": str,
            "page": int,
        },
        response=InventoryLogSerializer,
        many=True,
    )
    def get(self, request):
        queryset = InventoryLog.objects.select_related("product", "performed_by").all()

        product_id = request.query_params.get("product_id")
        sku = request.query_params.get("sku")
        transaction_type = request.query_params.get("transaction_type")
        reference_id = request.query_params.get("reference_id")

        if product_id:
            queryset = queryset.filter(product_id=product_id)
        if sku:
            queryset = queryset.filter(product__sku__iexact=sku.strip())
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type.upper().strip())
        if reference_id:
            queryset = queryset.filter(reference_id__icontains=reference_id.strip())

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = InventoryLogSerializer(page, many=True)
        return paginator.get_paginated_response(
            serializer.data, message="Inventory logs retrieved successfully."
        )
    @auto_schema(
        summary="Adjust product stock",
        request=StockAdjustmentInputSerializer,
        response=InventoryLogSerializer,
    )
    def post(self, request):
        try:
            input_serializer = StockAdjustmentInputSerializer(data=request.data)
            input_serializer.is_valid(raise_exception=True)
            data = input_serializer.validated_data

            log_entry = adjust_product_stock(
                product_id=data["product_id"],
                quantity_change=data["quantity_change"],
                transaction_type=data["transaction_type"],
                performed_by=request.user,
                reference_id=data.get("reference_id", ""),
                notes=data.get("notes", ""),
            )
            CacheHook.bump_version(CacheKeys.PRODUCTS)
            return success_response(
                data=InventoryLogSerializer(log_entry).data,
                message="Stock updated and logged successfully.",
                status_code=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return error_response(errors=e.detail, message="Stock adjustment failed.")


class LowStockAlertView(APIView):
    """
    GET /api/catalogue/inventory/alerts/ -> Products at or below low_stock_threshold
    Query params: ?status=OUT_OF_STOCK | LOW_STOCK
    """

    permission_classes = [IsAuthenticated, HasModulePermission.for_module("Catalogue", "is_view")]
    @auto_schema(
        summary="Get low stock and out-of-stock product alerts",
        params={
            "status": str,  # OUT_OF_STOCK | LOW_STOCK
            "page": int,
        },
        response=LowStockProductSerializer,
        many=True,
    )
    def get(self, request):
        queryset = (
            Product.objects.select_related("category")
            .filter(is_active=True, stock_quantity__lte=F("low_stock_threshold"))
            .order_by("stock_quantity", "name")
        )

        stock_status = request.query_params.get("status", "").upper().strip()
        if stock_status == "OUT_OF_STOCK":
            queryset = queryset.filter(stock_quantity=0)
        elif stock_status == "LOW_STOCK":
            queryset = queryset.filter(stock_quantity__gt=0)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = LowStockProductSerializer(page, many=True)
        return paginator.get_paginated_response(
            serializer.data, message="Low stock alerts retrieved successfully."
        )