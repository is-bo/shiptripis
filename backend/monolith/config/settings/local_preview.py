"""LOCAL-ONLY settings for previewing the operations admin. Not used in CI.

Same shape as `test_local` (SQLite, no Postgres on this machine) but with a
file-backed database and unhashed static files so `runserver` can render the
admin for a visual review.
"""

from config.settings.test_local import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "build" / "admin_preview.sqlite3",  # noqa: F405
    }
}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
