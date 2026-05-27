from urllib.parse import urlparse

from app.platforms.base import BasePlatformAdapter


class WikipediaAdapter(BasePlatformAdapter):
    platform = "Wikipedia"
    allowed_domains = ("wikipedia.org",)

    def build_queries(self, query, entity):
        search_name = query.name if len(query.name) >= len(entity.canonical_name) else entity.canonical_name
        return [f'"{search_name}" site:wikipedia.org']

    def extract_handle(self, url: str) -> str | None:
        segments = [segment for segment in urlparse(url).path.split("/") if segment]
        if len(segments) >= 2 and segments[0] == "wiki":
            return segments[1]
        return None

    def is_valid_profile_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.startswith("/wiki/") and "disambiguation" not in path
