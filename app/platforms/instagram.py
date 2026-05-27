from urllib.parse import urlparse

from app.platforms.base import BasePlatformAdapter


class InstagramAdapter(BasePlatformAdapter):
    platform = "Instagram"
    allowed_domains = ("instagram.com", "www.instagram.com")

    def extract_handle(self, url: str) -> str | None:
        segments = [segment for segment in urlparse(url).path.split("/") if segment]
        return segments[0] if segments else None

    def is_valid_profile_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        if path in {"", "/"}:
            return False
        invalid_prefixes = (
            "/p/",
            "/reel/",
            "/stories/",
            "/explore/",
            "/accounts/",
            "/tv/",
        )
        return not path.startswith(invalid_prefixes)
