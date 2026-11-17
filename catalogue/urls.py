from django.urls import path
from .views import CategoryView, ProductImageView, ProductVideoView, ProductView

urlpatterns = [
    path("categories/", CategoryView.as_view(), name="catalogue-categories"),
    path("products/", ProductView.as_view(), name="catalogue-products"),
    path("product-images/", ProductImageView.as_view(), name="catalogue-product-images"),
    path("product-videos/", ProductVideoView.as_view(), name="catalogue-product-videos"),
]