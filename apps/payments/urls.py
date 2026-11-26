from django.urls import path
from payments.views import (
    PaymentSettingView,
    InitiatePaymentView,
    SubmitPaymentProofView,
    PaymentTransactionView,
    AdminVerifyPaymentView,
)

urlpatterns = [
    path("settings/", PaymentSettingView.as_view(), name="payment-settings"),
    path("initiate/", InitiatePaymentView.as_view(), name="payment-initiate"),
    path("submit-proof/", SubmitPaymentProofView.as_view(), name="payment-submit-proof"),
    path("transactions/", PaymentTransactionView.as_view(), name="payment-transactions"),
    path("verify/", AdminVerifyPaymentView.as_view(), name="payment-verify"),
    
]
