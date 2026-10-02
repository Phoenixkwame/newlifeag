"""
WSGI config for the churchapp project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "churchapp.settings")

application = get_wsgi_application()
