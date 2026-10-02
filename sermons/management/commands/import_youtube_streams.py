import json
import re
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sermons.models import Sermon


class Command(BaseCommand):
    help = "Import a verified YouTube stream catalog with id, title and service_date; preserve existing sermons."

    def add_arguments(self, parser):
        parser.add_argument("catalog", type=Path)

    def handle(self, *args, **options):
        rows = json.loads(options["catalog"].read_text(encoding="utf-8"))
        prepared = []
        for row in rows:
            video_id = row.get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                raise CommandError("Invalid video ID in catalog")
            try:
                service_date = date.fromisoformat(row["service_date"])
            except (KeyError, ValueError):
                raise CommandError(f"Missing or invalid date for {video_id}")
            title = " ".join(row.get("title", "").split())
            if not title or len(title) > 200:
                raise CommandError(f"Missing or oversized title for {video_id}")
            prepared.append((video_id, title, service_date, row.get("date_source", "YouTube")))

        created = 0
        with transaction.atomic():
            existing = {s.video_embed_url for s in Sermon.objects.exclude(media_url="")}
            for video_id, title, service_date, source in prepared:
                embed = f"https://www.youtube.com/embed/{video_id}"
                if embed in existing:
                    continue
                Sermon.objects.create(
                    title=title, date=service_date,
                    media_url=f"https://www.youtube.com/watch?v={video_id}",
                    notes=f"Stream recording from Newlife Chapel AG. Date source: {source}.",
                )
                existing.add(embed)
                created += 1
        self.stdout.write(f"Added {created}; already present {len(prepared) - created}.")
