#!/usr/bin/env bash
# Render runs this on every deploy (see render.yaml). Each step is safe to
# repeat - nothing here duplicates or overwrites existing data.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py setup_groups
python manage.py import_youtube_streams sermons/data/youtube_streams.json
python manage.py seed_church_schedule

# First deploy only: creates the admin login from DJANGO_SUPERUSER_USERNAME /
# DJANGO_SUPERUSER_EMAIL / DJANGO_SUPERUSER_PASSWORD if those are set. Fails
# harmlessly (and is ignored) once that user already exists.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    python manage.py createsuperuser --noinput || true
fi
