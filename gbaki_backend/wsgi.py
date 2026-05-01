import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gbaki_backend.settings')

from django.core.wsgi import get_wsgi_application

app = get_wsgi_application()
application = app
