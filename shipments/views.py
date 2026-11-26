from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from utils.permissions import HasModulePermission
from utils.pagination import StandardPagination
from utils.responses import error_response, success_response

from .models import Shipment
from .serializers import (
    ShipmentAddEventSerializer,
    ShipmentCreateSerializer,
    ShipmentSerializer,
    ShipmentUpdateSerializer,
)

from core.schema import auto_schema
SHIPMENT_MODULE = "Shipments"


class ShipmentView(APIView):
    """
    Admin CRUD for Shipments:
    - GET /api/shipments/              -> Paginated list (filters: status, shipment_type, courier, search)
    - GET /api/shipments/?id=<id>      -> Single shipment with full tracking timeline
    - POST /api/shipments/             -> Create shipment & auto-sync Order / ReturnRequest status
    - PUT /api/shipments/?id=<id>      -> Update shipment details or status
    - DELETE /api/shipments/?id=<id>   -> Delete shipment (only if LABEL_CREATED)
    """

    def get_permissions(self):
        perm_map = {
            "GET": "is_view",
            "POST": "is_upload",
            "PUT": "is_update",
            "DELETE": "is_delete",
        }
        flag = perm_map.get(self.request.method, "is_view")
        return [IsAuthenticated(), HasModulePermission.for_module(SHIPMENT_MODULE, flag)()]
    @auto_schema(
        summary="List shipments or retrieve a single shipment by ?id=",
        params={
            "id": int,
            "status": str,
            "shipment_type": str,
            "courier": str,
            "order_id": int,
            "search": str,
        },
        response=ShipmentSerializer,
        many=True,
    )
    def get(self, request):
        shipment_id = request.query_params.get("id")
        queryset = Shipment.objects.select_related(
            "order", "order__user", "return_request"
        ).prefetch_related("events", "events__updated_by")

        if shipment_id:
            shipment = get_object_or_404(queryset, pk=shipment_id)
            return success_response(
                data=ShipmentSerializer(shipment).data,
                message="Shipment details fetched successfully.",
            )

        status_filter = request.query_params.get("status")
        shipment_type = request.query_params.get("shipment_type")
        courier = request.query_params.get("courier")
        order_id = request.query_params.get("order_id")
        search = request.query_params.get("search")

        if status_filter:
            queryset = queryset.filter(status=status_filter.upper())
        if shipment_type:
            queryset = queryset.filter(shipment_type=shipment_type.upper())
        if courier:
            queryset = queryset.filter(courier_name__icontains=courier.strip())
        if order_id:
            queryset = queryset.filter(order_id=order_id)
        if search:
            q = search.strip()
            queryset = queryset.filter(
                Q(tracking_number__icontains=q)
                | Q(order__order_number__icontains=q)
                | Q(courier_name__icontains=q)
                | Q(order__shipping_full_name__icontains=q)
                | Q(order__shipping_phone__icontains=q)
            )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ShipmentSerializer(page, many=True)
        return paginator.get_paginated_response(
            serializer.data, message="Shipments fetched successfully."
        )
    @auto_schema(
        summary="Create a shipment and synchronize Order / ReturnRequest status",
        request=ShipmentCreateSerializer,
        response=ShipmentSerializer,
    )
    def post(self, request):
        try:
            serializer = ShipmentCreateSerializer(
                data=request.data, context={"request": request}
            )
            serializer.is_valid(raise_exception=True)
            shipment = serializer.save()
            return success_response(
                data=ShipmentSerializer(shipment).data,
                message="Shipment created and order status synchronized.",
                status_code=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed while creating shipment.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    @auto_schema(
        summary="Update shipment details or status by ?id=",
        params={"id*": int},
        request=ShipmentUpdateSerializer,
        response=ShipmentSerializer,
    )
    def put(self, request):
        shipment_id = request.query_params.get("id")
        if not shipment_id:
            return error_response(
                errors={"id": "Query parameter ?id= is required."},
                message="Shipment ID is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        shipment = get_object_or_404(
            Shipment.objects.select_related("order", "return_request"), pk=shipment_id
        )
        try:
            serializer = ShipmentUpdateSerializer(
                shipment,
                data=request.data,
                partial=True,
                context={"request": request},
            )
            serializer.is_valid(raise_exception=True)
            updated_shipment = serializer.save()
            return success_response(
                data=ShipmentSerializer(updated_shipment).data,
                message="Shipment updated successfully.",
            )
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed while updating shipment.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    @auto_schema(
        summary="Delete a shipment in LABEL_CREATED status by ?id=",
        params={"id*": int},
    )
    def delete(self, request):
        shipment_id = request.query_params.get("id")
        if not shipment_id:
            return error_response(
                errors={"id": "Query parameter ?id= is required."},
                message="Shipment ID is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        shipment = get_object_or_404(Shipment, pk=shipment_id)
        if shipment.status != Shipment.ShipmentStatus.LABEL_CREATED:
            return error_response(
                errors={"status": "Only shipments in LABEL_CREATED status can be deleted."},
                message="Cannot delete shipment once picked up or in transit.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        shipment.delete()
        return success_response(message="Shipment deleted successfully.")


class ShipmentEventView(APIView):
    """
    Admin endpoint to log a new courier tracking scan/milestone:
    - POST /api/shipments/events/
    """

    permission_classes = [
        IsAuthenticated,
        HasModulePermission.for_module(SHIPMENT_MODULE, "is_update"),
    ]
    @auto_schema(
        summary="Log a new shipment tracking milestone/checkpoint",
        request=ShipmentAddEventSerializer,
        response=ShipmentSerializer,
    )
    def post(self, request):
        try:
            serializer = ShipmentAddEventSerializer(
                data=request.data, context={"request": request}
            )
            serializer.is_valid(raise_exception=True)
            event = serializer.save()
            return success_response(
                data=ShipmentSerializer(event.shipment).data,
                message="Tracking milestone added successfully.",
                status_code=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed while adding tracking event.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )


class ShipmentTrackView(APIView):
    """
    Customer & Admin shipment tracking lookup:
    - GET /api/shipments/track/?order_number=ORD-20261126-XXXXXX
    - GET /api/shipments/track/?tracking_number=D12345678
    Customers can only view shipments belonging to their own orders;
    Staff/Admins can view any shipment.
    """

    permission_classes = [IsAuthenticated]
    @auto_schema(
        summary="Track shipment by ?order_number= or ?tracking_number=",
        params={
            "order_number": str,
            "tracking_number": str,
        },
        response=ShipmentSerializer,
        many=True,
    )
    def get(self, request):
        order_number = request.query_params.get("order_number", "").strip()
        tracking_number = request.query_params.get("tracking_number", "").strip()

        if not order_number and not tracking_number:
            return error_response(
                errors={"query": "Provide either ?order_number= or ?tracking_number=."},
                message="Order number or tracking number is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        queryset = Shipment.objects.select_related(
            "order", "order__user", "return_request"
        ).prefetch_related("events", "events__updated_by")

        is_admin = request.user.is_staff or request.user.roles.filter(
            code="ADMIN", is_active=True
        ).exists()
        if not is_admin:
            queryset = queryset.filter(order__user=request.user)

        if tracking_number:
            shipment = queryset.filter(tracking_number__iexact=tracking_number).first()
            if not shipment:
                return error_response(
                    errors={"tracking_number": "No shipment found for this tracking number."},
                    message="Shipment not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            return success_response(
                data=ShipmentSerializer(shipment).data,
                message="Shipment tracking details fetched successfully.",
            )

        shipments = queryset.filter(order__order_number__iexact=order_number)
        if not shipments.exists():
            return error_response(
                errors={"order_number": "No shipments found for this order number."},
                message="No shipments found for this order.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return success_response(
            data=ShipmentSerializer(shipments, many=True).data,
            message="Order shipments fetched successfully.",
        )
