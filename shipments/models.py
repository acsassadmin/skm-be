from urllib.parse import quote
from django.conf import settings
from django.db import models
from django.utils import timezone
from orders.models import Order, ReturnRequest


COURIER_TRACKING_TEMPLATES = {
    "dtdc": "https://www.dtdc.com/trackshipment{awb}",
    "bluedart": "https://bluedart.com{awb}",
    "blue dart": "https://bluedart.com{awb}",
    "indiapost": "https://indiapost.gov.in",
    "india post": "https://indiapost.gov.in",
    "delhivery": "https://delhivery.com{awb}",
    "professional": "https://tpcindia.com{awb}",
    "professional courier": "https://tpcindia.com{awb}",
    "the professional couriers": "https://tpcindia.com{awb}",
    "st courier": "https://stcourier.com{awb}",
    "xpressbees": "https://xpressbees.com{awb}",
    "ecom express": "https://ecomexpress.in{awb}",
}


def build_default_tracking_url(courier_name: str, tracking_number: str) -> str:
    if not courier_name or not tracking_number:
        return ""
    key = courier_name.strip().lower()
    template = COURIER_TRACKING_TEMPLATES.get(key)
    if not template:
        return ""
    return template.format(awb=quote(tracking_number.strip()))


class Shipment(models.Model):
    """Courier dispatch and shipment tracking for forward orders and return pickups."""

    class ShipmentType(models.TextChoices):
        FORWARD = "FORWARD", "Forward Delivery"
        RETURN_PICKUP = "RETURN_PICKUP", "Return Pickup"

    class ShipmentStatus(models.TextChoices):
        LABEL_CREATED = "LABEL_CREATED", "Label Created"
        PICKED_UP = "PICKED_UP", "Picked Up"
        IN_TRANSIT = "IN_TRANSIT", "In Transit"
        OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for Delivery"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED_ATTEMPT = "FAILED_ATTEMPT", "Failed Delivery Attempt"
        RTO_INITIATED = "RTO_INITIATED", "Return to Origin (RTO) Initiated"
        RTO_DELIVERED = "RTO_DELIVERED", "Returned to Origin"

    shipment_type = models.CharField(
        max_length=20,
        choices=ShipmentType.choices,
        default=ShipmentType.FORWARD,
        db_index=True,
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="shipments",
    )
    return_request = models.OneToOneField(
        ReturnRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="pickup_shipment",
    )

    courier_name = models.CharField(max_length=100, db_index=True)
    tracking_number = models.CharField(max_length=100, unique=True, db_index=True)
    tracking_url = models.URLField(max_length=500, blank=True)

    status = models.CharField(
        max_length=25,
        choices=ShipmentStatus.choices,
        default=ShipmentStatus.LABEL_CREATED,
        db_index=True,
    )
    package_weight_kg = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    number_of_boxes = models.PositiveIntegerField(default=1)

    shipped_at = models.DateTimeField(null=True, blank=True)
    estimated_delivery_date = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shipments_shipment"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.courier_name = self.courier_name.strip()
        self.tracking_number = self.tracking_number.strip()
        if not self.tracking_url:
            self.tracking_url = build_default_tracking_url(
                self.courier_name, self.tracking_number
            )

        now = timezone.now()
        if (
            self.status in {
                self.ShipmentStatus.PICKED_UP,
                self.ShipmentStatus.IN_TRANSIT,
                self.ShipmentStatus.OUT_FOR_DELIVERY,
                self.ShipmentStatus.DELIVERED,
            }
            and not self.shipped_at
        ):
            self.shipped_at = now

        if self.status == self.ShipmentStatus.DELIVERED and not self.delivered_at:
            self.delivered_at = now

        super().save(*args, **kwargs)
        self.sync_parent_status()

    def sync_parent_status(self):
        """Automatically sync Order.status or ReturnRequest.status with shipment milestones."""
        if self.shipment_type == self.ShipmentType.FORWARD:
            order = self.order
            new_status = None
            if self.status in {
                self.ShipmentStatus.PICKED_UP,
                self.ShipmentStatus.IN_TRANSIT,
                self.ShipmentStatus.OUT_FOR_DELIVERY,
            } and order.status in {
                Order.Status.PENDING,
                Order.Status.CONFIRMED,
                Order.Status.PROCESSING,
            }:
                new_status = Order.Status.SHIPPED
            elif self.status == self.ShipmentStatus.DELIVERED and order.status != Order.Status.DELIVERED:
                new_status = Order.Status.DELIVERED
            elif self.status == self.ShipmentStatus.RTO_DELIVERED and order.status not in {
                Order.Status.CANCELLED,
                Order.Status.REFUNDED,
                Order.Status.RETURNED,
            }:
                new_status = Order.Status.RETURNED

            if new_status:
                order.status = new_status
                order.save(update_fields=["status", "updated_at"])

        elif self.shipment_type == self.ShipmentType.RETURN_PICKUP and self.return_request:
            ret = self.return_request
            new_ret_status = None
            if self.status in {
                self.ShipmentStatus.LABEL_CREATED,
                self.ShipmentStatus.PICKED_UP,
                self.ShipmentStatus.IN_TRANSIT,
                self.ShipmentStatus.OUT_FOR_DELIVERY,
            } and ret.status in {
                ReturnRequest.Status.REQUESTED,
                ReturnRequest.Status.APPROVED,
            }:
                new_ret_status = ReturnRequest.Status.PICKUP_SCHEDULED
            elif self.status == self.ShipmentStatus.DELIVERED and ret.status == ReturnRequest.Status.PICKUP_SCHEDULED:
                new_ret_status = ReturnRequest.Status.RECEIVED

            if new_ret_status:
                ret.status = new_ret_status
                ret.save(update_fields=["status", "updated_at"])

    def __str__(self):
        return f"{self.order.order_number} [{self.shipment_type}] - {self.courier_name} ({self.tracking_number})"


class ShipmentTrackingEvent(models.Model):
    """Step-by-step tracking timeline checkpoints for a Shipment."""

    class EventSource(models.TextChoices):
        MANUAL = "MANUAL", "Manual Admin Entry"
        WEBHOOK = "WEBHOOK", "Courier Webhook"

    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name="events",
    )
    status = models.CharField(
        max_length=25,
        choices=Shipment.ShipmentStatus.choices,
    )
    location = models.CharField(max_length=150, blank=True)
    remarks = models.CharField(max_length=255, blank=True)
    source = models.CharField(
        max_length=15,
        choices=EventSource.choices,
        default=EventSource.MANUAL,
    )
    event_time = models.DateTimeField(default=timezone.now)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shipment_updates",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shipments_tracking_event"
        ordering = ["-event_time", "-id"]

    def __str__(self):
        return f"{self.shipment.tracking_number} - {self.status} @ {self.location}"
