from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .models import Flyer

# A minimal valid 1x1 GIF, same tiny fixture pattern used elsewhere in this
# project for ImageField tests (see members/tests.py's member photo tests) -
# real image bytes so Pillow's ImageField validation doesn't reject it.
TINY_GIF = (
    b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def make_flyer(**kwargs):
    kwargs.setdefault("title", "VBS 2027")
    kwargs.setdefault("image", SimpleUploadedFile("flyer.gif", TINY_GIF, content_type="image/gif"))
    return Flyer.objects.create(**kwargs)


class FlyerModelTests(TestCase):
    def test_str_is_the_title(self):
        flyer = make_flyer(title="Building Fund Drive")
        self.assertEqual(str(flyer), "Building Fund Drive")

    def test_default_ordering_is_by_order_then_newest_first(self):
        first = make_flyer(title="Second Shown", order=5)
        second = make_flyer(title="First Shown", order=1)
        third = make_flyer(title="Also order 1, newer", order=1)
        self.assertEqual(list(Flyer.objects.all()), [third, second, first])

    def test_defaults_to_active(self):
        flyer = make_flyer()
        self.assertTrue(flyer.is_active)
