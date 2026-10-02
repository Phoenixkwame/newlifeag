from django.core.management.base import BaseCommand

from flyers.models import Flyer


class Command(BaseCommand):
    """
    One-off, safe-to-rerun command that adds two sample flyers so you can
    see the homepage flyer strip (see "Homepage flyer gallery & live
    stream/video section" in README.md) working right away on a fresh
    database, instead of staring at an empty homepage until real graphics
    exist. Skips anything that already exists by title, so running this
    more than once never creates duplicates.

    The two flyer images it points to (media/flyers/sample_sunday_service.png
    and media/flyers/sample_building_fund.png) are clearly watermarked
    "SAMPLE FLYER" - delete both sample Flyer rows from Staff -> Flyers
    whenever you're ready to replace them with your church's own graphics.
    """

    help = "Seeds two sample flyers so the homepage flyer strip has something to show."

    def handle(self, *args, **options):
        flyer, created = Flyer.objects.get_or_create(
            title="Fresh Fire Service (sample)",
            defaults={"image": "flyers/sample_sunday_service.png", "order": 1},
        )
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Already existed'}: {flyer.title}"))

        flyer2, created2 = Flyer.objects.get_or_create(
            title="Building Fund Drive (sample)",
            defaults={"image": "flyers/sample_building_fund.png", "order": 2},
        )
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created2 else 'Already existed'}: {flyer2.title}"))

        self.stdout.write(
            "Visit the homepage to see them, then manage/replace them any time from "
            "Staff Area -> Flyers. To also see the video section, feature a Live "
            "Stream or set a welcome video URL from the visitor-info settings screen "
            "- there's no sample for that since it needs a real video link."
        )
