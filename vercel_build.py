"""
vercel_build.py — exécuté par Vercel pendant le build.
Lance collectstatic, migrate, et crée le superuser si besoin.
"""
import os
import django
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gbaki_backend.settings')
django.setup()

# ── 1. Fichiers statiques ─────────────────────────────────────────────────────
print("==> collectstatic...")
try:
    call_command('collectstatic', '--noinput', verbosity=0)
    print("    collectstatic OK")
except Exception as e:
    print(f"    collectstatic warning (non bloquant): {e}")

# ── 2. Migrations ─────────────────────────────────────────────────────────────
print("==> migrate...")
call_command('migrate', '--noinput', verbosity=1)
print("    migrate OK ✅")

# ── 3. Superuser automatique depuis variables d'environnement ─────────────────
from django.contrib.auth.models import User

ADMIN_EMAIL    = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
ADMIN_PASSWORD = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
ADMIN_USERNAME = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')

if ADMIN_EMAIL and ADMIN_PASSWORD:
    if not User.objects.filter(username=ADMIN_USERNAME).exists():
        User.objects.create_superuser(
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL,
            password=ADMIN_PASSWORD,
        )
        print(f"==> Superuser '{ADMIN_USERNAME}' créé ✅")
    else:
        print(f"==> Superuser '{ADMIN_USERNAME}' existe déjà, skipped.")
else:
    print("==> DJANGO_SUPERUSER_EMAIL ou PASSWORD non défini, superuser skipped.")

print("==> Build complet ✅")