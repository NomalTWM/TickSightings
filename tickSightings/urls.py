from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from . import views

router = DefaultRouter()
router.register("sightings", views.SightingViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("reports/by-city/", views.by_city),
    path("reports/by-region/", views.by_region),
    path("reports/trends/", views.trends),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema")),
]