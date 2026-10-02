"""
ASGI config for the churchapp project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "churchapp.settings")

application = get_asgi_application()
