"""
gbaki_backend/wsgi.py — compatible Vercel (@vercel/python)
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gbaki_backend.settings')

# Vercel importe ce fichier et cherche `app` ou `application`
application = get_wsgi_application()
app = application   # alias requis par @vercel/python
