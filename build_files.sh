#!/bin/bash
set -e

echo "==> Installation des dependances..."
pip install -r requirements.txt

echo "==> collectstatic..."
python manage.py collectstatic --noinput || echo "collectstatic warning (non bloquant)"

echo "==> migrate..."
python manage.py migrate --noinput

echo "==> Superuser..."
python manage.py shell << 'PYEOF'
import os
from django.contrib.auth.models import User

email    = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')

if email and password:
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username, email, password)
        print(f"Superuser '{username}' cree")
    else:
        print(f"Superuser '{username}' existe deja")
else:
    print("Variables superuser non definies, skipped")
PYEOF

echo "==> Build termine OK"