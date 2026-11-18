from django.contrib import admin
from django.urls import path,include
from .views import *

urlpatterns = [
   path('health/', HealthApiView.as_view(),name="Health check"),
   path('contact/', ContactAPIView.as_view(), name='contact'),
   path('enquiry/', EnquiryAPIView.as_view(), name='enquiry'),

]
