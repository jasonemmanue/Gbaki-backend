"""
vercel_build.py — exécuté par @vercel/python pendant le build
Lance collectstatic et migrate avant que l'app démarre.
"""
import os
import django
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gbaki_backend.settings')
django.setup()

print("==> collectstatic...")
call_command('collectstatic', '--noinput', verbosity=0)

print("==> migrate...")
call_command('migrate', '--noinput', verbosity=1)

print("==> Build OK ✅")
