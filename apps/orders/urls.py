from django.urls import path
from .views import CouponValidateView, CouponView

urlpatterns = [
    path("coupons/", CouponView.as_view(), name="orders-coupons"),
    path("coupons/validate/", CouponValidateView.as_view(), name="orders-coupon-validate"),
]
