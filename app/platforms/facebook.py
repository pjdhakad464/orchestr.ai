from urllib.parse import parse_qs, unquote, urlparse

from app.platforms.base import BasePlatformAdapter


BLOCKED_FACEBOOK_PATH_SEGMENTS = {"p", "page", "pages", "php"}


def has_blocked_facebook_path(url_or_value: str) -> bool:
    candidate = url_or_value.strip()
    if not candidate:
        return False

    normalized_candidate = candidate
    lowered = candidate.casefold()
    if "://" not in candidate and "facebook.com" in lowered:
        normalized_candidate = f"https://{candidate.lstrip('/')}"

    parsed = urlparse(normalized_candidate)
    path = unquote(parsed.path).casefold()
    if not path or path == "/":
        return False
    if path.startswith("/profile.php"):
        return True

    segments = [segment.casefold() for segment in path.split("/") if segment]
    return any(segment in BLOCKED_FACEBOOK_PATH_SEGMENTS for segment in segments)


class FacebookAdapter(BasePlatformAdapter):
    platform = "Facebook"
    allowed_domains = ("facebook.com", "www.facebook.com")

    def extract_handle(self, url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.path == "/profile.php":
            identifier = parse_qs(parsed.query).get("id", [])
            return identifier[0] if identifier else None
        segments = [segment for segment in parsed.path.split("/") if segment]
        return segments[0] if segments else None

    def is_valid_profile_url(self, url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path in {"", "/"}:
            return False
        if has_blocked_facebook_path(url):
            return False
        invalid_prefixes = (
            "/watch",
            "/reel",
            "/share",
            "/plugins",
            "/events",
            "/photo",
            "/photos",
            "/posts",
            "/groups",
            "/marketplace",
        )
        return not path.startswith(invalid_prefixes)
