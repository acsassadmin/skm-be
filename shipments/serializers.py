from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from orders.models import Order, ReturnRequest
from .models import Shipment, ShipmentTrackingEvent


class ShipmentTrackingEventSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    updated_by_email = serializers.EmailField(source="updated_by.email", read_only=True)

    class Meta:
        model = ShipmentTrackingEvent
        fields = [
            "id",
            "status",
            "status_display",
            "location",
            "remarks",
            "source",
            "event_time",
            "updated_by_email",
            "created_at",
        ]
        read_only_fields = ["id", "source", "updated_by_email", "created_at"]


class ShipmentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer_name = serializers.CharField(source="order.shipping_full_name", read_only=True)
    customer_phone = serializers.CharField(source="order.shipping_phone", read_only=True)
    shipping_city = serializers.CharField(source="order.shipping_city", read_only=True)
    shipping_state = serializers.CharField(source="order.shipping_state", read_only=True)
    shipping_pincode = serializers.CharField(source="order.shipping_pincode", read_only=True)
    return_number = serializers.CharField(
        source="return_request.return_number", read_only=True, default=None
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    shipment_type_display = serializers.CharField(
        source="get_shipment_type_display", read_only=True
    )
    events = ShipmentTrackingEventSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id",
            "shipment_type",
            "shipment_type_display",
            "order",
            "order_number",
            "return_request",
            "return_number",
            "customer_name",
            "customer_phone",
            "shipping_city",
            "shipping_state",
            "shipping_pincode",
            "courier_name",
            "tracking_number",
            "tracking_url",
            "status",
            "status_display",
            "package_weight_kg",
            "number_of_boxes",
            "shipped_at",
            "estimated_delivery_date",
            "delivered_at",
            "remarks",
            "events",
            "created_at",
            "updated_at",
        ]


class ShipmentCreateSerializer(serializers.ModelSerializer):
    initial_location = serializers.CharField(
        max_length=150, required=False, allow_blank=True, write_only=True
    )
    initial_remarks = serializers.CharField(
        max_length=255, required=False, allow_blank=True, write_only=True
    )

    class Meta:
        model = Shipment
        fields = [
            "id",
            "shipment_type",
            "order",
            "return_request",
            "courier_name",
            "tracking_number",
            "tracking_url",
            "status",
            "package_weight_kg",
            "number_of_boxes",
            "estimated_delivery_date",
            "remarks",
            "initial_location",
            "initial_remarks",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        shipment_type = attrs.get("shipment_type", Shipment.ShipmentType.FORWARD)
        order = attrs.get("order")
        return_request = attrs.get("return_request")

        if shipment_type == Shipment.ShipmentType.FORWARD:
            if return_request is not None:
                raise serializers.ValidationError(
                    {"return_request": "Return request must be empty for forward shipments."}
                )
            if order.status in {Order.Status.CANCELLED, Order.Status.REFUNDED}:
                raise serializers.ValidationError(
                    {"order": f"Cannot create shipment for a {order.status.lower()} order."}
                )
            if Shipment.objects.filter(
                order=order, shipment_type=Shipment.ShipmentType.FORWARD
            ).exists():
                raise serializers.ValidationError(
                    {"order": "A forward shipment already exists for this order."}
                )

        elif shipment_type == Shipment.ShipmentType.RETURN_PICKUP:
            if return_request is None:
                raise serializers.ValidationError(
                    {"return_request": "return_request is required for RETURN_PICKUP shipments."}
                )
            if return_request.order_id != order.id:
                raise serializers.ValidationError(
                    {"return_request": "Return request does not belong to the selected order."}
                )
            if return_request.status in {
                ReturnRequest.Status.REJECTED,
                ReturnRequest.Status.COMPLETED,
            }:
                raise serializers.ValidationError(
                    {"return_request": f"Cannot schedule pickup for a {return_request.status.lower()} return."}
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        initial_location = validated_data.pop("initial_location", "").strip()
        initial_remarks = validated_data.pop("initial_remarks", "").strip()
        user = self.context["request"].user

        shipment = Shipment.objects.create(**validated_data)

        default_remark = (
            f"Shipment created with {shipment.courier_name} (AWB: {shipment.tracking_number})"
        )
        ShipmentTrackingEvent.objects.create(
            shipment=shipment,
            status=shipment.status,
            location=initial_location or "SKM Electronics Dispatch Center",
            remarks=initial_remarks or default_remark,
            source=ShipmentTrackingEvent.EventSource.MANUAL,
            event_time=timezone.now(),
            updated_by=user if user.is_authenticated else None,
        )
        return shipment


class ShipmentUpdateSerializer(serializers.ModelSerializer):
    location = serializers.CharField(
        max_length=150, required=False, allow_blank=True, write_only=True
    )
    event_remarks = serializers.CharField(
        max_length=255, required=False, allow_blank=True, write_only=True
    )

    class Meta:
        model = Shipment
        fields = [
            "courier_name",
            "tracking_number",
            "tracking_url",
            "status",
            "package_weight_kg",
            "number_of_boxes",
            "estimated_delivery_date",
            "remarks",
            "location",
            "event_remarks",
        ]

    @transaction.atomic
    def update(self, instance, validated_data):
        old_status = instance.status
        location = validated_data.pop("location", "").strip()
        event_remarks = validated_data.pop("event_remarks", "").strip()
        user = self.context["request"].user

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if instance.status != old_status or location or event_remarks:
            ShipmentTrackingEvent.objects.create(
                shipment=instance,
                status=instance.status,
                location=location,
                remarks=event_remarks or f"Shipment status updated to {instance.get_status_display()}",
                source=ShipmentTrackingEvent.EventSource.MANUAL,
                event_time=timezone.now(),
                updated_by=user if user.is_authenticated else None,
            )

        return instance


class ShipmentAddEventSerializer(serializers.ModelSerializer):
    shipment_id = serializers.PrimaryKeyRelatedField(
        queryset=Shipment.objects.select_related("order", "return_request"),
        source="shipment",
        write_only=True,
    )

    class Meta:
        model = ShipmentTrackingEvent
        fields = [
            "id",
            "shipment_id",
            "status",
            "location",
            "remarks",
            "event_time",
        ]
        read_only_fields = ["id"]

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        event_time = validated_data.get("event_time") or timezone.now()
        validated_data["event_time"] = event_time
        validated_data["source"] = ShipmentTrackingEvent.EventSource.MANUAL
        validated_data["updated_by"] = user if user.is_authenticated else None

        event = ShipmentTrackingEvent.objects.create(**validated_data)

        shipment = event.shipment
        shipment.status = event.status
        if event.status == Shipment.ShipmentStatus.DELIVERED and not shipment.delivered_at:
            shipment.delivered_at = event.event_time
        shipment.save()

        return event
