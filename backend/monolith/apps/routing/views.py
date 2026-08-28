from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .providers import route_provider_status


class RouteProviderStatusView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        del request
        return Response(route_provider_status())
