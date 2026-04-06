from django.urls import path
from .views import LandingPageView

app_name = 'core'

urlpatterns = [
    path('', LandingPageView.as_view(), name='landing'),
    # para las vistas despues del login si o si requieren revisar auth 
]
