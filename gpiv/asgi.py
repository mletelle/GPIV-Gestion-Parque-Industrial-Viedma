"""ASGI config for gpiv project."""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gpiv.settings')
application = get_asgi_application()
