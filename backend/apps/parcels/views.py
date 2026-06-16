from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import Parcel
from .serializers import (
    ParcelInboundSerializer,
    ParcelSerializer,
    PickupCodeSerializer,
)
from .services import inbound_parcel, open_by_pickup_code


class ParcelViewSet(viewsets.ModelViewSet):
    queryset = Parcel.objects.select_related("locker_cell").all()
    serializer_class = ParcelSerializer

    @action(detail=False, methods=["post"])
    def inbound(self, request):
        serializer = ParcelInboundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parcel = inbound_parcel(serializer.validated_data)
        return Response(ParcelSerializer(parcel).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def open(self, request):
        serializer = PickupCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            parcel = open_by_pickup_code(serializer.validated_data["pickup_code"])
        except ValidationError as e:
            message = e.detail.get("pickup_code", ["取件失败"])[0] if isinstance(e.detail, dict) else str(e.detail)
            return Response(
                {"success": False, "message": str(message)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "success": True,
                "message": f"柜格 {parcel.locker_cell.code} 已开箱。",
                "parcel": ParcelSerializer(parcel).data,
            }
        )
