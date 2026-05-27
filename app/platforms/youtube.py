from urllib.parse import urlparse

from app.platforms.base import BasePlatformAdapter


class YouTubeAdapter(BasePlatformAdapter):
    platform = "YouTube"
    allowed_domains = ("youtube.com", "www.youtube.com")

    def extract_handle(self, url: str) -> str | None:
        segments = [segment for segment in urlparse(url).path.split("/") if segment]
        if not segments:
            return None
        if segments[0].startswith("@"):
            return segments[0]
        if segments[0] in {"channel", "user"} and len(segments) > 1:
            return segments[1]
        return None

    def is_valid_profile_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        valid_prefixes = ("/@", "/channel/", "/user/")
        return path.startswith(valid_prefixes)
