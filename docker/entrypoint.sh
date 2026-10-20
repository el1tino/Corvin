#!/bin/sh
set -e

echo "Waiting for the database..."
python -c "
import time
import sys
from sqlalchemy import create_engine, text
from app.config import get_settings

settings = get_settings()
for attempt in range(30):
    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('Database is up.')
        sys.exit(0)
    except Exception as exc:
        print(f'Database not ready yet ({exc}); retrying...')
        time.sleep(2)
print('Database never became ready.', file=sys.stderr)
sys.exit(1)
"

echo "Running database migrations..."
alembic upgrade head

# Demo accounts use a password published in the README, so they are never
# created in production. The settings check reads APP_ENV from the
# environment or .env, exactly as the app does.
if python -c "import sys; from app.config import get_settings; sys.exit(0 if get_settings().is_production else 1)"; then
    echo "APP_ENV=production: skipping demo seed."
else
    echo "Seeding demo data (idempotent, no-op if already seeded)..."
    python -m scripts.demo_seed || true
fi

exec "$@"
