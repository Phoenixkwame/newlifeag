"""
Shared logic for the sermon form's free-text tags field - used by both
staff/views.py's sermon_create/sermon_edit, so tag creation/matching only
ever happens in one place.
"""

from .models import SermonProgress, Tag


def set_sermon_tags(sermon, tags_input):
    """
    Parses a comma-separated string of tag names (e.g. "Faith, Family") into
    real Tag rows - matching an existing tag case-insensitively rather than
    creating a near-duplicate ("faith" vs "Faith"), and creating a new one
    otherwise - then sets them as the sermon's tags. An empty/blank input
    clears every tag from the sermon, same as unchecking every box would.
    """
    names = [name.strip() for name in tags_input.split(",") if name.strip()]
    tags = []
    for name in names:
        tag = Tag.objects.filter(name__iexact=name).first()
        if tag is None:
            tag = Tag.objects.create(name=name)
        tags.append(tag)
    sermon.tags.set(tags)


def toggle_sermon_watched(*, member, sermon):
    """
    Flips a member's watched status for one sermon: deletes the
    SermonProgress row if one already exists (un-marking it), creates one
    otherwise (marking it watched as of today). Returns the new watched
    state (True/False) so the calling view can flash the right message.
    """
    deleted, _ = SermonProgress.objects.filter(member=member, sermon=sermon).delete()
    if deleted:
        return False
    SermonProgress.objects.create(member=member, sermon=sermon)
    return True
