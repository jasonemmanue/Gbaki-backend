"""
gbaki_backend/wsgi.py — Vercel (@vercel/python)
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gbaki_backend.settings')

try:
    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()
    app = application   # alias requis par @vercel/python
except Exception as e:
    # Log l'erreur précise dans les logs Vercel au lieu d'un 500 vide
    import traceback
    print("=== WSGI STARTUP ERROR ===", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    print("==========================", file=sys.stderr)

    def application(environ, start_response):
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
        return [f"Startup error: {str(e)}\n\nCheck Vercel logs for details.".encode()]

    app = application
