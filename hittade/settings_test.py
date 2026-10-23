"""Settings used by the test suite.

Inherits everything from the normal settings but swaps in a throwaway
in-memory SQLite database so tests run anywhere without a Postgres server.
"""

from .settings import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
