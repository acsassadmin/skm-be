from django.urls import path
from .views import CouponValidateView, CouponView,CartView,OrderView,OrderItemView,OrderHistoryView

urlpatterns = [
    path("coupons/", CouponView.as_view(), name="orders-coupons"),
    path("coupons/validate/", CouponValidateView.as_view(), name="orders-coupon-validate"),
    path("cart/", CartView.as_view(), name="cart"),
    path("orders-cart/", OrderView.as_view(), name="orders"),
    path("order-items/", OrderItemView.as_view(), name="order-items"),
    path("orders-history/", OrderHistoryView.as_view(), name="order-history"),

]
