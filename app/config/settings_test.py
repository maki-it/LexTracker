import os
import tempfile

os.environ["APP_ENVIRONMENT"] = "test"
os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp(prefix="lextracker-test-"))

from config.settings import *  # noqa: F403

# Hashing with Argon2 makes every login in a test take noticeable time.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
