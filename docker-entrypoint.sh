#!/bin/bash

sleep 2

# In production, turn off DEBUG before collectstatic so the manifest
# (cache-busting) static storage is used for the collected files.
if [ "$PRODUCTION" = "true" ]; then
    export DEBUG=false
fi

# Apply database migrations
echo "Apply database migrations"
python manage.py migrate

# Initial CSS build
echo "Building styles"
bash ./scripts/sass.sh build

# Collect static files for WhiteNoise to serve (must run after the CSS build).
echo "Collecting static files"
python manage.py collectstatic --noinput

# Start server
if [ "$PRODUCTION" = "true" ]; then
    echo "Starting granian (production)"
    granian --interface wsgi \
        --host 0.0.0.0 \
        --port 8000 \
        --workers 3 \
        hittade.wsgi:application
else
    echo "Starting Django development server"
    python manage.py runserver 0.0.0.0:8000
fi
