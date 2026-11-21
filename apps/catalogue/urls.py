from django.urls import path
from .views import CategoryView, ProductImageView, ProductVideoView, ProductView,ProductExcelExportView,ProductExcelImportView,InventoryView,LowStockAlertView

urlpatterns = [
    path("categories/", CategoryView.as_view(), name="catalogue-categories"),
    path("products/", ProductView.as_view(), name="catalogue-products"),
    path("product-images/", ProductImageView.as_view(), name="catalogue-product-images"),
    path("product-videos/", ProductVideoView.as_view(), name="catalogue-product-videos"),
    path("products/export-excel/", ProductExcelExportView.as_view(), name="catalogue-products-export-excel"),
    path("products/import-excel/", ProductExcelImportView.as_view(), name="catalogue-products-import-excel"),
    path("inventory/", InventoryView.as_view(), name="catalogue-inventory"),
    path("inventory/alerts/", LowStockAlertView.as_view(), name="catalogue-inventory-alerts"),
]