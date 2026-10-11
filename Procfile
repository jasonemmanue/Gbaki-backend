web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && (sh scripts/background_tasks.sh &) && gunicorn gbaki_backend.wsgi --bind 0.0.0.0:$PORT --workers 3 --timeout 120
