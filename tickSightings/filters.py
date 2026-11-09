import django_filters as filters
from .models import Sighting

class SightingFilter(filters.FilterSet):
    location = filters.CharFilter(field_name="location", lookup_expr="iexact")
    species = filters.CharFilter(field_name="species", lookup_expr="iexact")
    date_from = filters.DateFilter(field_name="date", lookup_expr="date__gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="date__lte")

    class Meta:
        model = Sighting
        fields = []