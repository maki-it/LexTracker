from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import get_env

env = get_env()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = env.data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEBUG = env.debug
SECRET_KEY = env.secret_key.get_secret_value()
if not SECRET_KEY:
    if env.environment == "production":
        raise ImproperlyConfigured("APP_SECRET_KEY must be set in production.")
    SECRET_KEY = "insecure-development-key"

ALLOWED_HOSTS = env.allowed_hosts
CSRF_TRUSTED_ORIGINS = env.csrf_trusted_origins

INSTALLED_APPS = [
    "servestatic.runserver_nostatic",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "django_tailwind_cli",
    "core",
    "accounts",
    "customers",
    "projects",
    "tracking",
    "lexware",
    "billing",
    "reports",
    "mcpserver",
    "portal",
    "setup",
]

# All middleware is async-capable, so Django never has to run the whole request in a thread.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Outermost after security, so it compresses what everything below returns.
    "core.compression.CompressionMiddleware",
    "servestatic.middleware.ServeStaticMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "core.middleware.LoginRequiredMiddleware",
    "core.access.RoleAccessMiddleware",
    "core.nav.NavCountsMiddleware",
    "core.dialogs.DialogMiddleware",
]

# Invitation links (accounts.user_views.invite_url) are valid for a week.
PASSWORD_RESET_TIMEOUT = 7 * 24 * 60 * 60

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.preferences",
                "core.dialogs.layout",
            ],
        },
    },
]

# SQLite tuned for a small web app with concurrent readers:
# WAL lets reads run while a write is in progress, IMMEDIATE transactions take the
# write lock up front (avoids "database is locked" on lock upgrades), and the
# busy timeout makes writers wait instead of failing.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 5,
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA temp_store=MEMORY;"
                "PRAGMA mmap_size=134217728;"
                "PRAGMA cache_size=-20000;"
            ),
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"
# Name shown for the account in authenticator apps.
OTP_TOTP_ISSUER = "LexTracker"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "de-de"
TIME_ZONE = env.time_zone
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR.parent / "staticfiles"
# In production, collectstatic writes hashed and compressed files that ServeStatic serves
# with long cache headers. Elsewhere files come straight from the source folders.
IS_PRODUCTION = env.environment == "production"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "servestatic.storage.CompressedManifestStaticFilesStorage"
        if IS_PRODUCTION
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
SERVESTATIC_USE_FINDERS = SERVESTATIC_AUTOREFRESH = not IS_PRODUCTION

# Tailwind's standalone CLI, so no Node.js is needed. Components live in assets/tailwind.css.
TAILWIND_CLI_VERSION = "4.3.3"
TAILWIND_CLI_SRC_CSS = "assets/tailwind.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

LEXWARE_API_KEY = env.lexware_api_key.get_secret_value()
LEXWARE_BASE_URL = env.lexware_base_url

BACKUP_DIR = env.backup_dir or DATA_DIR / "backups"
BACKUP_KEEP = env.backup_keep
BACKUP_TIME = env.backup_time

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
if IS_PRODUCTION:
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = env.secure_cookies
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"default": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
    "root": {"handlers": ["console"], "level": env.log_level.upper()},
}
