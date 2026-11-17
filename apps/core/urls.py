from django.contrib import admin
from django.urls import path,include
from .views import *

urlpatterns = [
   path('health/', HealthApiView.as_view(),name="Health check"),
]
