from django.urls import path
from .views import (
    CategoryView, ProductImageView, 
    ProductVideoView, ProductView,
    ProductExcelExportView,ProductExcelImportView, 
    WarrantyView, WarrantyClaimView,
    InventoryView,LowStockAlertView,
    ProductReviewView, MyReviewsView,)

urlpatterns = [
    path("categories/", CategoryView.as_view(), name="catalogue-categories"),
    path("products/", ProductView.as_view(), name="catalogue-products"),
    path("product-images/", ProductImageView.as_view(), name="catalogue-product-images"),
    path("product-videos/", ProductVideoView.as_view(), name="catalogue-product-videos"),
    path("products/export-excel/", ProductExcelExportView.as_view(), name="catalogue-products-export-excel"),
    path("products/import-excel/", ProductExcelImportView.as_view(), name="catalogue-products-import-excel"),
    path("warranties/", WarrantyView.as_view(), name="warranty"),
    path("warranty-claims/", WarrantyClaimView.as_view(), name="warranty-claim"),
    path("inventory/", InventoryView.as_view(), name="catalogue-inventory"),
    path("inventory/alerts/", LowStockAlertView.as_view(), name="catalogue-inventory-alerts"),
    path("myreviews/", MyReviewsView.as_view(), name="my-reviews"),
    path("reviews/", ProductReviewView.as_view(), name="reviews")
]