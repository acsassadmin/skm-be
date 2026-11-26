from django.db.models import Q,F
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from utils.permissions import HasModulePermission
from utils.responses import error_response, success_response
from utils.filters import *
from .models import Category, Product, ProductImage, ProductVideo,WarrantyClaim,Warranty
from .serializers import *
#
from .utils.warrantyhelper import *
from .utils.reviews import *
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

class WarrantyView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get(self, request):
        warranty_id = request.query_params.get("id")
        if warranty_id:
            warranty = (
                Warranty.objects.select_related("product", "order_item", "order_item__order")
                .filter(id=warranty_id)
                .first()
            )
            if not warranty:
                return error_response(message="Warranty not found.", status_code=status.HTTP_404_NOT_FOUND)
            sync_warranty_expiry(warranty)
            return success_response(data=WarrantySerializer(warranty, context={"request": request}).data)

        queryset = Warranty.objects.select_related("product", "order_item", "order_item__order").all()
        if not is_admin_user(request.user):
            queryset = queryset.filter(order_item__order__user=request.user)

        queryset = apply_search_and_filters(
            queryset,
            request,
            search_fields=[
                "serial_number",
                "product__name",
                "product__sku",
                "order_item__order__order_number",
            ],
            filter_fields={
                "status": "status",
                "product": "product_id",
                "order_item": "order_item_id",
                "serial_number": "serial_number",
            },
        )

        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(queryset, request, view=self)
        serializer = WarrantySerializer(paginated_queryset, many=True, context={"request": request})
        return paginator.get_paginated_response(
            serializer.data, message="Warranties retrieved successfully."
        )

    def post(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        serializer = WarrantySerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Warranty creation failed.")

        data = serializer.validated_data
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        months = data.get("warranty_months")
        product = data.get("product")

        if start_date and not end_date and product:
            effective_months = months if months is not None else product.warranty_months
            end_date = calculate_warranty_end_date(start_date, effective_months)

        if data.get("order_item") is None and not end_date and product:
            warranty = create_warranty_for_product(
                product=product,
                start_date=start_date,
                order_item=data.get("order_item"),
                serial_number=data.get("serial_number", ""),
                warranty_months=months,
            )
        else:
            warranty = serializer.save(end_date=end_date)

        return success_response(
            data=WarrantySerializer(warranty, context={"request": request}).data,
            message="Warranty created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def put(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        warranty_id = request.query_params.get("id")
        warranty = Warranty.objects.filter(id=warranty_id).first()
        if not warranty:
            return error_response(message="Warranty not found.", status_code=status.HTTP_404_NOT_FOUND)

        serializer = WarrantySerializer(warranty, data=request.data, partial=True, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Warranty update failed.")

        data = serializer.validated_data
        start_date = data.get("start_date", warranty.start_date)
        months = data.get("warranty_months", warranty.warranty_months)
        if ("start_date" in data or "warranty_months" in data) and "end_date" not in data:
            serializer.validated_data["end_date"] = calculate_warranty_end_date(start_date, months)

        updated = serializer.save()
        sync_warranty_expiry(updated)
        return success_response(
            data=WarrantySerializer(updated, context={"request": request}).data,
            message="Warranty updated successfully.",
        )

    def delete(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        warranty_id = request.query_params.get("id")
        warranty = Warranty.objects.filter(id=warranty_id).first()
        if not warranty:
            return error_response(message="Warranty not found.", status_code=status.HTTP_404_NOT_FOUND)

        warranty.delete()
        return success_response(message="Warranty deleted successfully.")


class WarrantyClaimView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get(self, request):
        claim_id = request.query_params.get("id")
        if claim_id:
            claim = (
                WarrantyClaim.objects.select_related("warranty", "warranty__product")
                .filter(id=claim_id)
                .first()
            )
            if not claim:
                return error_response(message="Warranty claim not found.", status_code=status.HTTP_404_NOT_FOUND)
            return success_response(data=WarrantyClaimSerializer(claim, context={"request": request}).data)

        queryset = WarrantyClaim.objects.select_related("warranty", "warranty__product").all()
        if not is_admin_user(request.user):
            queryset = queryset.filter(warranty__order_item__order__user=request.user)

        # Note: apply_search_and_filters filters on `created_at__date`, while WarrantyClaim uses `reported_at`.
        # Apply search & exact filters cleanly here, plus date range on `reported_at__date`.
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(claim_number__icontains=search)
                | Q(issue_description__icontains=search)
                | Q(replacement_serial__icontains=search)
                | Q(warranty__serial_number__icontains=search)
                | Q(warranty__product__sku__icontains=search)
            )

        status_param = request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)

        resolution_param = request.query_params.get("resolution")
        if resolution_param:
            queryset = queryset.filter(resolution=resolution_param)

        warranty_id = request.query_params.get("warranty")
        if warranty_id:
            queryset = queryset.filter(warranty_id=warranty_id)

        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        if start_date:
            queryset = queryset.filter(reported_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(reported_at__date__lte=end_date)

        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(queryset, request, view=self)
        serializer = WarrantyClaimSerializer(paginated_queryset, many=True, context={"request": request})
        return paginator.get_paginated_response(
            serializer.data, message="Warranty claims retrieved successfully."
        )

    def post(self, request):
        serializer = WarrantyClaimSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Warranty claim creation failed.")

        claim = serializer.save()
        return success_response(
            data=WarrantyClaimSerializer(claim, context={"request": request}).data,
            message="Warranty claim submitted successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    def put(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        claim_id = request.query_params.get("id")
        claim = WarrantyClaim.objects.filter(id=claim_id).first()
        if not claim:
            return error_response(message="Warranty claim not found.", status_code=status.HTTP_404_NOT_FOUND)

        serializer = WarrantyClaimSerializer(claim, data=request.data, partial=True, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Warranty claim update failed.")

        data = serializer.validated_data
        resolution = data.get("resolution")
        mark_claimed = bool(request.data.get("mark_warranty_claimed", False))

        if resolution and resolution != WarrantyClaim.Resolution.PENDING:
            if "issue_description" in data:
                claim.issue_description = data["issue_description"]
            claim = resolve_warranty_claim(
                claim=claim,
                resolution=resolution,
                replacement_serial=data.get("replacement_serial", claim.replacement_serial),
                mark_warranty_claimed=mark_claimed,
            )
            if "status" in data and claim.status != data["status"]:
                claim.status = data["status"]
                claim.save(update_fields=["status"])
        else:
            claim = serializer.save()
            if (
                data.get("resolution") == WarrantyClaim.Resolution.PENDING
                or data.get("status") == WarrantyClaim.Status.OPEN
            ) and claim.resolved_at is not None:
                claim.resolved_at = None
                claim.save(update_fields=["resolved_at"])

        return success_response(
            data=WarrantyClaimSerializer(claim, context={"request": request}).data,
            message="Warranty claim updated successfully.",
        )

    def delete(self, request):
        if not is_admin_user(request.user):
            return error_response(message="Admin privileges required.", status_code=status.HTTP_403_FORBIDDEN)

        claim_id = request.query_params.get("id")
        claim = WarrantyClaim.objects.filter(id=claim_id).first()
        if not claim:
            return error_response(message="Warranty claim not found.", status_code=status.HTTP_404_NOT_FOUND)

        claim.delete()
        return success_response(message="Warranty claim deleted successfully.")
    
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

class ProductReviewView(APIView):
    """
    Collection (/api/reviews/):
      GET  ?product=1&rating=5&search=...&start_date=...&end_date=...
      POST (authenticated)

    Detail (/api/reviews/<pk>/):
      GET    (single review)
      PATCH  (owner or admin/staff)
      DELETE (owner or admin/staff)
    """
    permission_classes = [IsAuthenticatedOrReadOnly]

    def _is_staff_or_admin(self, user) -> bool:
        return bool(
            user
            and user.is_authenticated
            and (user.is_staff or user.is_superuser or user.has_role("ADMIN"))
        )

    def _can_manage(self, user, review) -> bool:
        if not user or not user.is_authenticated:
            return False
        return review.user_id == user.id or self._is_staff_or_admin(user)

    def _get_review(self, pk) -> ProductReview:
        return get_object_or_404(
            ProductReview.objects.select_related("product", "user", "order_item").prefetch_related("images"),
            pk=pk,
        )

    def get(self, request, pk=None):
        if pk is not None:
            review = self._get_review(pk)
            serializer = ProductReviewSerializer(review, context={"request": request})
            return success_response(data=serializer.data, message="Review retrieved successfully")

        queryset = (
            ProductReview.objects.select_related("product", "user", "order_item")
            .prefetch_related("images")
        )
        is_staff = self._is_staff_or_admin(request.user)

        if not is_staff:
            queryset = queryset.filter(status=ProductReview.Status.APPROVED)

        filter_fields = {
            "product": "product_id",
            "rating": "rating",
            "verified": "is_verified_purchase",
        }
        if is_staff:
            filter_fields["status"] = "status"

        queryset = apply_search_and_filters(
            queryset,
            request,
            search_fields=["title", "comment", "product__name", "user__full_name"],
            filter_fields=filter_fields,
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ProductReviewSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(
            serializer.data,
            message="Reviews retrieved successfully",
        )

    def post(self, request, pk=None):
        if not request.user.is_authenticated:
            return error_response(
                message="Authentication required",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = ProductReviewSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return error_response(
                errors=serializer.errors,
                message="Validation failed",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        product = serializer.validated_data["product"]
        order_item = serializer.validated_data.get("order_item")
        is_verified, matched_item = get_verified_purchase(request.user, product, order_item)

        review = serializer.save(
            is_verified_purchase=is_verified,
            order_item=matched_item if matched_item is not None else order_item,
        )

        if review.status == ProductReview.Status.APPROVED:
            recalculate_product_rating(review.product_id)

        output_serializer = ProductReviewSerializer(review, context={"request": request})
        return success_response(
            data=output_serializer.data,
            message="Review submitted successfully",
            status_code=status.HTTP_201_CREATED,
        )

    def patch(self, request, pk=None):
        review_id = pk or request.query_params.get("id") or request.query_params.get("pk")
        if not review_id:
            return error_response(
                message="Review ID is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not request.user.is_authenticated:
            return error_response(
                message="Authentication required",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        review = self._get_review(review_id)
        if not self._can_manage(request.user, review):
            return error_response(
                message="Permission denied",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        data = request.data.copy()
        is_staff = self._is_staff_or_admin(request.user)

        if not is_staff:
            data.pop("status", None)
            data.pop("admin_reply", None)
        elif "admin_reply" in data and data["admin_reply"]:
            review.replied_at = timezone.now()

        serializer = ProductReviewSerializer(
            review,
            data=data,
            partial=True,
            context={"request": request},
        )
        if not serializer.is_valid():
            return error_response(
                errors=serializer.errors,
                message="Validation failed",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        target_product = serializer.validated_data.get("product", review.product)
        target_order_item = serializer.validated_data.get("order_item", review.order_item)
        is_verified, matched_item = get_verified_purchase(
            review.user, target_product, target_order_item
        )

        extra_kwargs = {"is_verified_purchase": is_verified}
        if matched_item is not None:
            extra_kwargs["order_item"] = matched_item

        updated_review = serializer.save(**extra_kwargs)
        recalculate_product_rating(updated_review.product_id)

        output_serializer = ProductReviewSerializer(updated_review, context={"request": request})
        return success_response(data=output_serializer.data, message="Review updated successfully")

    def delete(self, request, pk=None):
        review_id = pk or request.query_params.get("id") or request.query_params.get("pk")
        if not review_id:
            return error_response(
                message="Review ID is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not request.user.is_authenticated:
            return error_response(
                message="Authentication required",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        review = self._get_review(review_id)
        if not self._can_manage(request.user, review):
            return error_response(
                message="Permission denied",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        product_id = review.product_id
        review.delete()
        recalculate_product_rating(product_id)
        return success_response(message="Review deleted successfully")
class MyReviewsView(APIView):
    """
    GET /api/reviews/my/?product=1&rating=5&search=...
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = (
            ProductReview.objects.filter(user=request.user)
            .select_related("product", "order_item")
            .prefetch_related("images")
        )

        queryset = apply_search_and_filters(
            queryset,
            request,
            search_fields=["title", "comment", "product__name"],
            filter_fields={
                "product": "product_id",
                "rating": "rating",
                "status": "status",
                "verified": "is_verified_purchase",
            },
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ProductReviewSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(
            serializer.data,
            message="Your reviews retrieved successfully",
        )