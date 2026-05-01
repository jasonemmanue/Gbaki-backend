@'
#!/bin/bash
set -e
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gbaki_backend.settings')
django.setup()
from django.contrib.auth.models import User
e=os.environ.get('DJANGO_SUPERUSER_EMAIL','')
p=os.environ.get('DJANGO_SUPERUSER_PASSWORD','')
u=os.environ.get('DJANGO_SUPERUSER_USERNAME','admin')
if e and p and not User.objects.filter(username=u).exists():
    User.objects.create_superuser(u,e,p)
    print('Superuser cree: '+u)
else:
    print('Superuser skipped')
"
'@ | Set-Content -Encoding UTF8 build_files.sh