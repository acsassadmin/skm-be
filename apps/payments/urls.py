from django.urls import path
from payments.views import (
    PaymentSettingView,
    InitiatePaymentView,
    SubmitPaymentProofView,
    PaymentTransactionView,
    AdminVerifyPaymentView,
    InvoiceConfigurationView,
    PaymentInvoiceView
)

urlpatterns = [
    path("settings/", PaymentSettingView.as_view(), name="payment-settings"),
    path("initiate/", InitiatePaymentView.as_view(), name="payment-initiate"),
    path("submit-proof/", SubmitPaymentProofView.as_view(), name="payment-submit-proof"),
    path("transactions/", PaymentTransactionView.as_view(), name="payment-transactions"),
    path("verify/", AdminVerifyPaymentView.as_view(), name="payment-verify"),
    path("invoice-settings/", InvoiceConfigurationView.as_view(), name="payment-invoice-settings"),
    path("invoices/<str:order_number>/", PaymentInvoiceView.as_view(), name="payment-invoice"),
    
]
