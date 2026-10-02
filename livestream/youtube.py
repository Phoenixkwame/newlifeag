import re

# Recognizes a YouTube video link in any of its common shapes (a plain
# watch link, a youtu.be share link, an already-embeddable link, or a
# "live/<id>" link) and pulls out the 11-character video id. Anything else
# (e.g. a Facebook live stream link - LiveStream.stream_url isn't
# guaranteed to be YouTube at all) simply doesn't match, and the caller
# falls back to a plain outbound link instead of a broken embed.
_YOUTUBE_VIDEO_PATTERN = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|live/)|youtu\.be/)([\w-]{11})"
)
_YOUTUBE_PLAYLIST_PATTERN = re.compile(r"youtube\.com/playlist\?list=([\w-]+)")


def youtube_embed_url(url):
    """
    Converts a YouTube video or playlist link into its embeddable
    youtube.com/embed/... form, or returns None if the URL isn't a
    recognizable YouTube link at all.
    """
    if not url:
        return None
    match = _YOUTUBE_VIDEO_PATTERN.search(url)
    if match:
        return f"https://www.youtube.com/embed/{match.group(1)}"
    match = _YOUTUBE_PLAYLIST_PATTERN.search(url)
    if match:
        return f"https://www.youtube.com/embed/videoseries?list={match.group(1)}"
    return None

