# -*- coding: utf-8 -*-
"""Shared Flask extensions (instantiated once, bound to the app in the factory).

Keeping the limiter here lets blueprints decorate individual routes with
explicit limits (e.g. the login route) without importing the app factory.
"""

import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Rate-limit counter storage. Defaults to in-process memory, which is per-worker:
# under multiple gunicorn workers the effective login cap becomes (limit × workers)
# and resets on restart. Set RATELIMIT_STORAGE_URI to a shared backend
# (e.g. redis://127.0.0.1:6379) so limits are enforced globally across workers.
RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=RATELIMIT_STORAGE_URI,
)
