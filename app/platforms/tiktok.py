from urllib.parse import urlparse

from app.platforms.base import BasePlatformAdapter


class TikTokAdapter(BasePlatformAdapter):
    platform = "TikTok"
    allowed_domains = ("tiktok.com", "www.tiktok.com")

    def extract_handle(self, url: str) -> str | None:
        segments = [segment for segment in urlparse(url).path.split("/") if segment]
        if not segments:
            return None
        return segments[0] if segments[0].startswith("@") else None

    def is_valid_profile_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        if path in {"", "/"}:
            return False
        invalid_prefixes = ("/tag/", "/discover/", "/music/", "/video/")
        return not path.startswith(invalid_prefixes) and path.count("/") <= 2
