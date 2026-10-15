"""Settings come from environment variables only; nothing secret is stored in code."""
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dailyoptionassess.db")
if DATABASE_URL.startswith("postgres://"):          # Railway hands out the old scheme
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
# bcrypt hash of the single login password. Create one with: python -m app.hash_password
PASSWORD_HASH = os.environ.get("APP_PASSWORD_HASH", "")
# Random string used to sign the session cookie.
SESSION_SECRET = os.environ.get("APP_SESSION_SECRET", "")
SESSION_DAYS = int(os.environ.get("APP_SESSION_DAYS", "30"))
SECURE_COOKIE = os.environ.get("APP_SECURE_COOKIE", "1") != "0"   # set 0 only for local http
DEFAULT_UNDERLYINGS = ("SPX", "SPXW")
MAX_UPLOAD_MB = 15
# Comma-separated list of front-end origins allowed to call the API, e.g. https://my-app.lovable.app
CORS_ORIGINS = [o.strip() for o in os.environ.get("APP_CORS_ORIGINS", "").split(",") if o.strip()]
