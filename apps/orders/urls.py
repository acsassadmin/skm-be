from django.urls import path
from .views import CouponValidateView, CouponView,CartView

urlpatterns = [
    path("coupons/", CouponView.as_view(), name="orders-coupons"),
    path("coupons/validate/", CouponValidateView.as_view(), name="orders-coupon-validate"),
    path("cart/", CartView.as_view(), name="cart"),

]
