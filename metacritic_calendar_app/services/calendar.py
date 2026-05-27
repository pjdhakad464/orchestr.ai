from __future__ import annotations

import csv
import html
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from metacritic_calendar_app.models import MetacriticCalendarItem, MetacriticCalendarSnapshot
from metacritic_calendar_app.services.text import contains_rent_buy, repair_mojibake
from title_url_lookup_app.models import TitleLookupQuery
from title_url_lookup_app.services.imdb_dataset import ImdbDatasetLookupError, ImdbDatasetLookupService


ARTICLE_COMPONENT_PARAMS = {
    "componentName": "article",
    "componentDisplayName": "Article",
    "componentType": "Article",
}


@dataclass(frozen=True)
class CalendarTarget:
    key: str
    label: str
    slug: str
    source_url: str

    @property
    def backend_url(self) -> str:
        return f"https://backend.metacritic.com/articles/metacritic/{self.slug}/web"


class MetacriticCalendarError(RuntimeError):
    pass


class MetacriticCalendarService:
    BASE_URL = "https://www.metacritic.com"
    EXCLUDED_AVAILABILITY_TOKENS = ("rent/buy",)
    SECTION_LABELS = {
        "games": "Games",
        "movies": "Movies",
        "tv": "TV Shows",
    }
    TARGETS = {
        "games": CalendarTarget(
            key="games",
            label="Games",
            slug="major-new-and-upcoming-video-games-ps5-xbox-switch-pc",
            source_url="https://www.metacritic.com/news/major-new-and-upcoming-video-games-ps5-xbox-switch-pc/",
        ),
        "movies": CalendarTarget(
            key="movies",
            label="Movies",
            slug="upcoming-movie-release-dates-schedule",
            source_url="https://www.metacritic.com/news/upcoming-movie-release-dates-schedule/",
        ),
        "tv": CalendarTarget(
            key="tv",
            label="TV Shows",
            slug="tv-premiere-dates",
            source_url="https://www.metacritic.com/news/tv-premiere-dates/",
        ),
    }
    MONTHS = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    DATE_RE = re.compile(
        r"(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?",
        re.IGNORECASE,
    )
    HEADING_RE = re.compile(r"<(h2|h3)[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
    TABLE_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
    LINK_RE = re.compile(r'<a [^>]*href="(?P<href>[^"]+)"[^>]*>(?P<label>.*?)</a>', re.IGNORECASE | re.DOTALL)
    STRONG_RE = re.compile(r"<strong[^>]*>(.*?)</strong>", re.IGNORECASE | re.DOTALL)
    IMG_ALT_RE = re.compile(r'<img\b[^>]*\balt="(?P<alt>[^"]*)"', re.IGNORECASE | re.DOTALL)
    SHORTCODE_API_RE = re.compile(r'api="([^"]+)"', re.IGNORECASE | re.DOTALL)
    TAG_RE = re.compile(r"<[^>]+>")
    SHORTCODE_RE = re.compile(r"<shortcode\b[^>]*>.*?</shortcode>", re.IGNORECASE | re.DOTALL)
    BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
    IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
    WHITESPACE_RE = re.compile(r"\s+")

    def __init__(
        self,
        timeout_seconds: int = 12,
        imdb_dataset_lookup: ImdbDatasetLookupService | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.imdb_dataset_lookup = imdb_dataset_lookup or ImdbDatasetLookupService()

    def fetch_snapshot(self, calendar_type: str | list[str] = "all") -> MetacriticCalendarSnapshot:
        keys, snapshot_type = self.resolve_calendar_types(calendar_type)
        fetch_keys = list(keys)
        include_tv_movie_rows_only = "movies" in keys and "tv" not in keys
        if include_tv_movie_rows_only:
            fetch_keys.append("tv")
        generated_at = datetime.now().astimezone()
        items: list[MetacriticCalendarItem] = []
        notes: list[str] = []

        with httpx.Client(timeout=self.timeout_seconds, headers=self._build_headers(), follow_redirects=True) as client:
            for key in fetch_keys:
                payload = self._fetch_calendar_payload(client, self.TARGETS[key])
                parsed_items = self.parse_payload(self.TARGETS[key], payload)
                if include_tv_movie_rows_only and key == "tv":
                    parsed_items = [item for item in parsed_items if item.section == "movies"]
                items.extend(parsed_items)
                if not parsed_items:
                    notes.append(f"No rows were parsed for {self.SECTION_LABELS[key]}.")

        items = self._dedupe_items(items)
        items.sort(key=lambda item: (item.release_date or "9999-99-99", item.section, item.title.lower()))
        self._attach_imdb_ids(items)
        return MetacriticCalendarSnapshot(
            calendar_type=snapshot_type,
            generated_at=generated_at,
            items=items,
            notes=notes,
        )

    def resolve_calendar_types(self, calendar_type: str | list[str] = "all") -> tuple[list[str], str]:
        raw_values = calendar_type if isinstance(calendar_type, list) else [calendar_type]
        normalized_values: list[str] = []
        for raw_value in raw_values:
            for value in str(raw_value or "").split(","):
                normalized = value.strip().lower()
                if normalized:
                    normalized_values.append(normalized)

        if not normalized_values:
            normalized_values = ["all"]

        valid_values = set(self.TARGETS) | {"all"}
        invalid_values = sorted(set(normalized_values) - valid_values)
        if invalid_values:
            invalid_list = ", ".join(invalid_values)
            raise MetacriticCalendarError(
                f"Unsupported calendar_type value: {invalid_list}. Use any combination of games, movies, tv, or all."
            )

        if "all" in normalized_values:
            keys = list(self.TARGETS)
        else:
            keys = [key for key in self.TARGETS if key in normalized_values]

        if not keys:
            keys = list(self.TARGETS)

        snapshot_type = "all" if len(keys) == len(self.TARGETS) else "_".join(keys)
        return keys, snapshot_type

    def parse_payload(self, target: CalendarTarget, payload: dict[str, Any]) -> list[MetacriticCalendarItem]:
        item = payload.get("data", {}).get("item")
        if not isinstance(item, dict):
            raise MetacriticCalendarError(f"Metacritic payload for {target.key} did not include article data.")

        body_html = str(item.get("body") or "")
        if not body_html:
            raise MetacriticCalendarError(f"Metacritic payload for {target.key} did not include article body HTML.")

        source_title = str(item.get("headline") or item.get("promoHed") or target.label)
        base_year = self._resolve_base_year(item)
        current_year = base_year
        last_release_date: datetime | None = None
        parsed_items: list[MetacriticCalendarItem] = []

        headings = list(self.HEADING_RE.finditer(body_html))
        for index, match in enumerate(headings):
            tag = match.group(1).lower()
            heading_text = self._clean_html(match.group(2))
            body_start = match.end()
            body_end = headings[index + 1].start() if index + 1 < len(headings) else len(body_html)
            section_html = body_html[body_start:body_end]

            if tag == "h2":
                year_match = re.search(r"\b(20\d{2})\b", heading_text)
                if year_match:
                    current_year = int(year_match.group(1))
                    last_release_date = None
                continue

            if not heading_text:
                continue

            rows = self.TABLE_ROW_RE.findall(section_html)
            for row_html in rows:
                item_row, last_release_date, current_year = self._parse_row(
                    target=target,
                    source_title=source_title,
                    heading_text=heading_text,
                    row_html=row_html,
                    current_year=current_year,
                    last_release_date=last_release_date,
                )
                if item_row is not None:
                    parsed_items.append(item_row)

        return parsed_items

    def _attach_imdb_ids(self, items: list[MetacriticCalendarItem]) -> None:
        lookup_cache: dict[tuple[str, str, str], str] = {}
        for item in items:
            title_type = ""
            if item.section == "games":
                title_type = "videoGame"
            elif item.section == "movies":
                title_type = "movie"
            elif item.section == "tv":
                title_type = "tv"

            if not title_type:
                continue

            release_year = item.release_date[:4] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.release_date) else ""
            cache_key = (item.title.casefold(), title_type, release_year)
            if cache_key not in lookup_cache:
                try:
                    matches = self.imdb_dataset_lookup.lookup_title(
                        TitleLookupQuery(title=item.title, title_type=title_type, year=release_year)
                    )
                except (ImdbDatasetLookupError, ValueError):
                    matches = []
                lookup_cache[cache_key] = matches[0].imdb_id if matches else ""
            item.imdb_id = lookup_cache[cache_key]

    def snapshot_to_csv_bytes(self, snapshot: MetacriticCalendarSnapshot) -> bytes:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "section",
                "section_label",
                "source_title",
                "source_url",
                "group_label",
                "release_date",
                "title",
                "url",
                "provider",
                "availability",
                "details",
                "metascore",
                "imdb_id",
            ],
        )
        writer.writeheader()
        for item in snapshot.items:
            writer.writerow(
                {
                    "section": item.section,
                    "section_label": item.section_label,
                    "source_title": item.source_title,
                    "source_url": item.source_url,
                    "group_label": item.group_label,
                    "release_date": item.release_date,
                    "title": item.title,
                    "url": item.url,
                    "provider": item.provider,
                    "availability": item.availability,
                    "details": item.details,
                    "metascore": item.metascore if item.metascore is not None else "",
                    "imdb_id": item.imdb_id,
                }
            )
        return output.getvalue().encode("utf-8-sig")

    def _fetch_calendar_payload(self, client: httpx.Client, target: CalendarTarget) -> dict[str, Any]:
        response = client.get(target.backend_url, params=ARTICLE_COMPONENT_PARAMS)
        if response.status_code >= 400:
            raise MetacriticCalendarError(
                f"Metacritic returned {response.status_code} for the {target.label} calendar."
            )
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise MetacriticCalendarError(f"Metacritic returned invalid JSON for the {target.label} calendar.") from exc

    def _parse_row(
        self,
        *,
        target: CalendarTarget,
        source_title: str,
        heading_text: str,
        row_html: str,
        current_year: int,
        last_release_date: datetime | None,
    ) -> tuple[MetacriticCalendarItem | None, datetime | None, int]:
        cells = self.CELL_RE.findall(row_html)
        if len(cells) < 2:
            return None, last_release_date, current_year

        data_cell = cells[1]
        meta_cell = cells[0] if cells else ""
        trailing_cell = cells[2] if len(cells) > 2 else ""

        title, item_url = self._extract_title_and_url(data_cell, meta_cell)
        if not title:
            return None, last_release_date, current_year

        shortcode_api = self._extract_shortcode_api(meta_cell)
        metascore = shortcode_api.get("metaScore")
        if isinstance(metascore, bool):
            metascore = None
        elif metascore is not None:
            try:
                metascore = int(metascore)
            except (TypeError, ValueError):
                metascore = None

        lines = self._extract_lines(data_cell)
        availability = self._clean_html(trailing_cell)
        provider = ""
        details = ""
        release_date = ""

        if target.key == "games":
            first_line = lines[0] if lines else ""
            provider = first_line.replace(title, "", 1).strip(" -")
            detail_line = " | ".join(lines[1:]).strip()
            release_date, last_release_date, current_year = self._derive_release_date(
                detail_line,
                fallback_text=heading_text,
                current_year=current_year,
                last_release_date=last_release_date,
            )
            details = self._strip_date_from_text(detail_line)
            availability = availability.strip()
        else:
            provider = self._strip_wrapping_parens(lines[1]) if len(lines) > 1 else ""
            details = " | ".join(lines[2:]).strip()
            release_date, last_release_date, current_year = self._derive_release_date(
                heading_text,
                fallback_text="",
                current_year=current_year,
                last_release_date=last_release_date,
            )

        output_section = target.key
        if target.key == "tv" and self._is_movie_row(
            item_url=item_url,
            availability=availability,
            data_cell=data_cell,
        ):
            output_section = "movies"

        if self._should_exclude_item(title=title, availability=availability, section=output_section):
            return None, last_release_date, current_year

        return (
            MetacriticCalendarItem(
                section=output_section,
                section_label=self.SECTION_LABELS[output_section],
                source_title=source_title,
                source_url=target.source_url,
                group_label=heading_text,
                release_date=release_date,
                title=title,
                url=item_url,
                provider=provider,
                availability=availability,
                details=details,
                metascore=metascore,
            ),
            last_release_date,
            current_year,
        )

    def _should_exclude_item(self, *, title: str, availability: str, section: str) -> bool:
        normalized_availability = availability.strip().casefold()
        if (
            section != "movies"
            and normalized_availability
            and any(token in normalized_availability for token in self.EXCLUDED_AVAILABILITY_TOKENS)
        ):
            return True

        normalized_title = title.strip().casefold()
        return section != "movies" and "special" in normalized_title

    def _is_movie_row(self, *, item_url: str, availability: str, data_cell: str = "") -> bool:
        normalized_url = item_url.casefold()
        if "/movie/" in normalized_url:
            return True
        alt_values = [html.unescape(match.group("alt")).casefold() for match in self.IMG_ALT_RE.finditer(data_cell)]
        if any("movie" in alt for alt in alt_values):
            return True
        return contains_rent_buy(availability)

    def _dedupe_items(self, items: list[MetacriticCalendarItem]) -> list[MetacriticCalendarItem]:
        deduped: dict[tuple[str, str, str, str], MetacriticCalendarItem] = {}
        for item in items:
            key = (
                item.section,
                item.release_date,
                item.title.casefold(),
                item.url,
            )
            deduped.setdefault(key, item)
        return list(deduped.values())

    def _derive_release_date(
        self,
        text: str,
        *,
        fallback_text: str,
        current_year: int,
        last_release_date: datetime | None,
    ) -> tuple[str, datetime | None, int]:
        combined_sources = [text, fallback_text]
        match = None
        for candidate in combined_sources:
            if not candidate:
                continue
            current_match = self.DATE_RE.search(candidate)
            if current_match:
                match = current_match
                break

        if match is None:
            return "", last_release_date, current_year

        month_name = match.group("month").lower()
        month = self.MONTHS.get(month_name)
        if month is None:
            return "", last_release_date, current_year

        day = int(match.group("day"))
        explicit_year = match.group("year")
        year = int(explicit_year) if explicit_year else current_year
        parsed_date = datetime(year, month, day)

        if explicit_year is None and last_release_date is not None and parsed_date < last_release_date:
            month_delta = last_release_date.month - parsed_date.month
            if month_delta >= 6 or (last_release_date.month == 12 and parsed_date.month == 1):
                year += 1
                parsed_date = datetime(year, month, day)

        return parsed_date.strftime("%Y-%m-%d"), parsed_date, year

    def _extract_title_and_url(self, data_cell: str, meta_cell: str) -> tuple[str, str]:
        for match in self.LINK_RE.finditer(data_cell):
            href = html.unescape(match.group("href")).strip()
            if "metacritic.com" in href or href.startswith("/"):
                title = self._clean_html(match.group("label"))
                return title, urljoin(self.BASE_URL, href)

        strong_match = self.STRONG_RE.search(data_cell)
        if strong_match:
            return self._clean_html(strong_match.group(1)), ""

        api_payload = self._extract_shortcode_api(meta_cell)
        title = str(api_payload.get("title") or "").strip()
        url = str(api_payload.get("url") or "").strip()
        return title, urljoin(self.BASE_URL, url) if url else ""

    def _extract_shortcode_api(self, fragment: str) -> dict[str, Any]:
        match = self.SHORTCODE_API_RE.search(fragment)
        if not match:
            return {}
        try:
            return json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError:
            return {}

    def _extract_lines(self, fragment: str) -> list[str]:
        cleaned = self._clean_html(fragment, keep_line_breaks=True)
        return [line for line in cleaned.splitlines() if line]

    def _strip_date_from_text(self, text: str) -> str:
        if not text:
            return ""
        stripped = self.DATE_RE.sub("", text, count=1)
        stripped = stripped.replace("  ", " ").strip(" -|")
        return stripped

    def _resolve_base_year(self, item: dict[str, Any]) -> int:
        for key in ("displayDateUpdated", "dateUpdated", "displayDatePublished", "datePublished"):
            candidate = item.get(key)
            if isinstance(candidate, dict):
                raw = str(candidate.get("date") or "")
                if raw:
                    try:
                        return datetime.fromisoformat(raw.replace(" ", "T")).year
                    except ValueError:
                        pass
        return datetime.now().year

    def _build_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": self.BASE_URL,
        }

    def _strip_wrapping_parens(self, value: str) -> str:
        stripped = value.strip()
        if stripped.startswith("(") and stripped.endswith(")"):
            return stripped[1:-1].strip()
        return stripped

    def _clean_html(self, value: str, *, keep_line_breaks: bool = False) -> str:
        if not value:
            return ""
        text = self.SHORTCODE_RE.sub("", value)
        text = self.IMG_RE.sub("", text)
        if keep_line_breaks:
            text = self.BR_RE.sub("\n", text)
        else:
            text = self.BR_RE.sub(" ", text)
        text = self.TAG_RE.sub("", text)
        text = html.unescape(text)
        text = repair_mojibake(text)
        if keep_line_breaks:
            lines = []
            for line in text.splitlines():
                normalized = self.WHITESPACE_RE.sub(" ", line).strip(" -\u00a0")
                if normalized:
                    lines.append(normalized)
            return "\n".join(lines)
        return self.WHITESPACE_RE.sub(" ", text).strip(" -\u00a0")
