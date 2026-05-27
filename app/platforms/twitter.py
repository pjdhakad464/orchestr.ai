from urllib.parse import urlparse

from app.platforms.base import BasePlatformAdapter


class TwitterAdapter(BasePlatformAdapter):
    platform = "X/Twitter"
    allowed_domains = ("x.com", "www.x.com", "twitter.com", "www.twitter.com")

    def build_queries(self, query, entity):
        search_name = query.name if len(query.name) >= len(entity.canonical_name) else entity.canonical_name
        qualifiers = []
        if query.entity_type:
            qualifiers.append(query.entity_type.replace("_", " "))
        if query.country:
            qualifiers.append(query.country)
        qualifier_suffix = f" {' '.join(qualifiers)}" if qualifiers else ""
        return [f'"{search_name}" (site:x.com OR site:twitter.com){qualifier_suffix}']

    def extract_handle(self, url: str) -> str | None:
        segments = [segment for segment in urlparse(url).path.split("/") if segment]
        return segments[0] if segments else None

    def is_valid_profile_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        invalid_prefixes = ("/i/", "/search", "/hashtag/", "/home", "/status/")
        return not path.startswith(invalid_prefixes) and len([segment for segment in path.split("/") if segment]) == 1
