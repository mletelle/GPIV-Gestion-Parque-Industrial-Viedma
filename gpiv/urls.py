"""URL configuration for gpiv project."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render


def handler429_view(request, exception=None):
    """Vista de error HTTP 429 — demasiados intentos (rate limiting)."""
    return render(request, 'core/429.html', status=429)


handler429 = handler429_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

#  archivos de media en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
