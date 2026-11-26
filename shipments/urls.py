from django.urls import path
from .views import ShipmentEventView, ShipmentTrackView, ShipmentView

urlpatterns = [
    path("", ShipmentView.as_view(), name="shipment-list-create"),
    path("events/", ShipmentEventView.as_view(), name="shipment-add-event"),
    path("track/", ShipmentTrackView.as_view(), name="shipment-track"),
]
