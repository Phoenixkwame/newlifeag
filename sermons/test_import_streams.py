import json
from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command, CommandError
from django.test import TestCase

from .models import Sermon


class StreamImportTests(TestCase):
    def run_import(self, rows):
        with TemporaryDirectory() as folder:
            catalog = Path(folder) / "streams.json"
            catalog.write_text(json.dumps(rows), encoding="utf-8")
            call_command("import_youtube_streams", str(catalog), stdout=StringIO())

    def test_import_preserves_existing_edits_and_is_repeatable(self):
        existing = Sermon.objects.create(title="Edited title", speaker="Named speaker", date=date(2026, 10, 1), media_url="https://youtu.be/avfQCAACW7c")
        rows = [
            {"id": "avfQCAACW7c", "title": "Source title", "service_date": "2026-10-01"},
            {"id": "x6pFb2tPv5c", "title": "Other service", "service_date": "2026-09-27"},
        ]
        self.run_import(rows)
        self.run_import(rows)
        self.assertEqual(Sermon.objects.count(), 2)
        existing.refresh_from_db()
        self.assertEqual(existing.title, "Edited title")
        self.assertEqual(existing.speaker, "Named speaker")

    def test_missing_date_rejects_catalog_without_partial_import(self):
        with self.assertRaises(CommandError):
            self.run_import([
                {"id": "avfQCAACW7c", "title": "Valid", "service_date": "2026-10-01"},
                {"id": "x6pFb2tPv5c", "title": "Undated"},
            ])
        self.assertFalse(Sermon.objects.exists())
