from django.db.models import Count
from django.db.models.functions import TruncMonth, TruncWeek
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .filters import SightingFilter
from .models import Sighting
from .regions import CITY_TO_REGION
from .serializers import SightingSerializer


class SightingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Sighting.objects.all()
    serializer_class = SightingSerializer
    filterset_class = SightingFilter
    search_fields = ["location", "species", "latin_name"]
    ordering_fields = ["date", "location", "species"]


def filtered(request):
    """Reports honour the same filters as the list endpoint."""
    return SightingFilter(request.GET, queryset=Sighting.objects.all()).qs


@api_view(["GET"])
def by_city(request):
    rows = (filtered(request).values("location")
            .annotate(count=Count("pk")).order_by("-count", "location"))
    return Response(list(rows))


@api_view(["GET"])
def by_region(request):
    totals = {}
    for row in filtered(request).values("location").annotate(count=Count("pk")):
        region = CITY_TO_REGION.get(row["location"], "Unknown")
        totals[region] = totals.get(region, 0) + row["count"]
    data = [{"region": r, "count": c}
            for r, c in sorted(totals.items(), key=lambda x: -x[1])]
    return Response(data)


@extend_schema(parameters=[OpenApiParameter("interval", str, enum=["weekly", "monthly"])])
@api_view(["GET"])
def trends(request):
    interval = request.GET.get("interval", "monthly")
    trunc = {"weekly": TruncWeek, "monthly": TruncMonth}.get(interval)
    if trunc is None:
        return Response({"error": "interval must be 'weekly' or 'monthly'"}, status=400)
    rows = (filtered(request).annotate(period=trunc("date"))
            .values("period").annotate(count=Count("pk")).order_by("period"))
    return Response([{"period": r["period"].date().isoformat(), "count": r["count"]}
                     for r in rows])