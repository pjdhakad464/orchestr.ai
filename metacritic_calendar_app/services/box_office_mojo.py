from __future__ import annotations

import csv
import html
import io
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import httpx
from openpyxl import Workbook

from metacritic_calendar_app.models import BoxOfficeMojoReleaseItem, BoxOfficeMojoReleaseWindowSnapshot
from title_url_lookup_app.models import TitleLookupQuery
from title_url_lookup_app.services.imdb_dataset import ImdbDatasetLookupError, ImdbDatasetLookupService


class BoxOfficeMojoCalendarError(RuntimeError):
    pass


class BoxOfficeMojoCalendarService:
    BASE_URL = "https://www.boxofficemojo.com"
    DATE_URL_TEMPLATE = BASE_URL + "/calendar/{anchor_date}/"
    TABLE_RE = re.compile(r'<div id="table".*?<table[^>]*>(?P<table>.*?)</table>', re.IGNORECASE | re.DOTALL)
    ROW_RE = re.compile(r"<tr(?P<attrs>[^>]*)>(?P<body>.*?)</tr>", re.IGNORECASE | re.DOTALL)
    CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
    LINK_RE = re.compile(r'<a [^>]*href="(?P<href>[^"]+)"[^>]*>', re.IGNORECASE | re.DOTALL)
    HEADING_RE = re.compile(r"<h3[^>]*>(?P<title>.*?)</h3>", re.IGNORECASE | re.DOTALL)
    SECONDARY_RE = re.compile(
        r'<span[^>]*class="[^"]*a-color-secondary[^"]*"[^>]*>(?P<text>.*?)</span>',
        re.IGNORECASE | re.DOTALL,
    )
    SVG_RE = re.compile(r"<svg\b[^>]*>.*?</svg>", re.IGNORECASE | re.DOTALL)
    IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
    TAG_RE = re.compile(r"<[^>]+>")
    BLOCK_TAG_RE = re.compile(r"</?(?:div|h1|h2|h3|h4|h5|h6|p|li|ul|ol|br|span)\b[^>]*>", re.IGNORECASE)
    WHITESPACE_RE = re.compile(r"\s+")
    RUNTIME_RE = re.compile(r"^\d+\s*hr(?:\s+\d+\s*min)?$|^\d+\s*min$", re.IGNORECASE)

    def __init__(
        self,
        timeout_seconds: int = 12,
        imdb_dataset_lookup: ImdbDatasetLookupService | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.imdb_dataset_lookup = imdb_dataset_lookup or ImdbDatasetLookupService()

    def fetch_last_7_days_snapshot(self, today: date | None = None) -> BoxOfficeMojoReleaseWindowSnapshot:
        reference_day = today or datetime.now().astimezone().date()
        window_end = reference_day - timedelta(days=1)
        window_start = window_end - timedelta(days=6)
        return self.fetch_release_window_snapshot(
            report_key="usa_last_7_days",
            report_label="USA last 7 days",
            window_start=window_start,
            window_end=window_end,
        )

    def fetch_upcoming_12_months_snapshot(self, today: date | None = None) -> BoxOfficeMojoReleaseWindowSnapshot:
        window_start = today or datetime.now().astimezone().date()
        window_end = self._add_months(window_start, 12)
        return self.fetch_release_window_snapshot(
            report_key="usa_upcoming_12_months",
            report_label="USA upcoming 12 months",
            window_start=window_start,
            window_end=window_end,
        )

    def fetch_release_window_snapshot(
        self,
        *,
        report_key: str,
        report_label: str,
        window_start: date,
        window_end: date,
    ) -> BoxOfficeMojoReleaseWindowSnapshot:
        anchor_dates = self._build_anchor_dates(window_start, window_end)
        source_url = self.DATE_URL_TEMPLATE.format(anchor_date=anchor_dates[0].isoformat())
        items = self._fetch_release_items_for_window(window_start, window_end, anchor_dates)

        items.sort(key=lambda item: (item.release_date, item.title.casefold()))
        self._attach_imdb_ids(items)

        notes: list[str] = [
            "Source: Box Office Mojo domestic release schedule, which reflects U.S. theatrical release dates."
        ]
        notes.append(f"Fetched {len(anchor_dates)} Box Office Mojo calendar page(s) for this report window.")
        if not items:
            notes.append(
                f"No domestic releases were listed between {window_start.isoformat()} and {window_end.isoformat()}."
            )

        return BoxOfficeMojoReleaseWindowSnapshot(
            report_key=report_key,
            report_label=report_label,
            generated_at=datetime.now().astimezone(),
            window_start=window_start,
            window_end=window_end,
            source_url=source_url,
            items=items,
            notes=notes,
        )

    def parse_release_page(self, page_html: str) -> list[BoxOfficeMojoReleaseItem]:
        table_match = self.TABLE_RE.search(page_html)
        if table_match is None:
            raise BoxOfficeMojoCalendarError("Box Office Mojo page did not contain the release schedule table.")

        items: list[BoxOfficeMojoReleaseItem] = []
        current_release_date = ""
        for match in self.ROW_RE.finditer(table_match.group("table")):
            attrs = match.group("attrs") or ""
            row_html = match.group("body")
            if "mojo-group-label" in attrs:
                current_release_date = self._extract_release_date(row_html)
                continue

            cells = self.CELL_RE.findall(row_html)
            if len(cells) < 3 or not current_release_date:
                continue

            release_cell, distributor_cell, scale_cell = cells[:3]
            title = self._extract_title(release_cell)
            if not title:
                continue

            title_url = self._extract_title_url(release_cell)
            lines = self._extract_release_lines(release_cell, title)
            release_notes, genres, cast, runtime = self._parse_release_lines(lines)

            items.append(
                BoxOfficeMojoReleaseItem(
                    release_date=current_release_date,
                    title=title,
                    url=title_url,
                    release_notes=release_notes,
                    genres=genres,
                    cast=cast,
                    runtime=runtime,
                    distributor=self._clean_html(distributor_cell),
                    scale=self._clean_html(scale_cell),
                )
            )

        return items

    def _attach_imdb_ids(self, items: list[BoxOfficeMojoReleaseItem]) -> None:
        lookup_cache: dict[tuple[str, str], str] = {}
        for item in items:
            release_year = item.release_date[:4] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.release_date) else ""
            cache_key = (item.title.casefold(), release_year)
            if cache_key not in lookup_cache:
                try:
                    matches = self.imdb_dataset_lookup.lookup_title(
                        TitleLookupQuery(title=item.title, title_type="movie", year=release_year)
                    )
                except (ImdbDatasetLookupError, ValueError):
                    matches = []
                lookup_cache[cache_key] = matches[0].imdb_id if matches else ""
            item.imdb_id = lookup_cache[cache_key]

    def snapshot_to_csv_bytes(self, snapshot: BoxOfficeMojoReleaseWindowSnapshot) -> bytes:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "release_date",
                "title",
                "url",
                "release_notes",
                "genres",
                "cast",
                "runtime",
                "distributor",
                "scale",
                "imdb_id",
            ],
        )
        writer.writeheader()
        for item in snapshot.items:
            writer.writerow(item.model_dump())
        return output.getvalue().encode("utf-8-sig")

    def snapshot_to_xlsx_bytes(self, snapshot: BoxOfficeMojoReleaseWindowSnapshot) -> bytes:
        workbook = Workbook()
        summary_sheet = workbook.active
        summary_sheet.title = "Summary"
        summary_sheet.append(["Item", "Value"])
        summary_sheet.append(["Report", snapshot.report_label])
        summary_sheet.append(["Window Start", snapshot.window_start.isoformat()])
        summary_sheet.append(["Window End", snapshot.window_end.isoformat()])
        summary_sheet.append(["Rows", len(snapshot.items)])
        summary_sheet.append(["Source URL", snapshot.source_url])
        for index, note in enumerate(snapshot.notes, start=1):
            summary_sheet.append([f"Note {index}", note])

        releases_sheet = workbook.create_sheet("Releases")
        releases_sheet.append(
            [
                "Release Date",
                "Title",
                "URL",
                "Release Notes",
                "Genres",
                "Cast",
                "Runtime",
                "Distributor",
                "Scale",
                "IMDb ID",
            ]
        )
        for item in snapshot.items:
            releases_sheet.append(
                [
                    item.release_date,
                    item.title,
                    item.url,
                    item.release_notes,
                    item.genres,
                    item.cast,
                    item.runtime,
                    item.distributor,
                    item.scale,
                    item.imdb_id,
                ]
            )

        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()

    def _extract_release_date(self, row_html: str) -> str:
        label = self._clean_html(row_html)
        try:
            return datetime.strptime(label, "%B %d, %Y").date().isoformat()
        except ValueError as exc:
            raise BoxOfficeMojoCalendarError(f"Unexpected Box Office Mojo release date label: {label}") from exc

    def _extract_title(self, release_cell: str) -> str:
        heading_match = self.HEADING_RE.search(release_cell)
        if heading_match:
            return self._clean_html(heading_match.group("title"))
        for match in self.LINK_RE.finditer(release_cell):
            href = html.unescape(match.group("href"))
            if "/release/" in href:
                title_match = re.search(
                    rf'{re.escape(match.group(0))}(?P<text>.*?)</a>',
                    release_cell,
                    re.IGNORECASE | re.DOTALL,
                )
                if title_match:
                    title = self._clean_html(title_match.group("text"))
                    if title:
                        return title
        return ""

    def _extract_title_url(self, release_cell: str) -> str:
        for match in self.LINK_RE.finditer(release_cell):
            href = html.unescape(match.group("href")).strip()
            if href.startswith("/release/"):
                return urljoin(self.BASE_URL, href.split("?")[0])
        return ""

    def _extract_release_lines(self, release_cell: str, title: str) -> list[str]:
        cleaned = self._clean_html(release_cell, keep_line_breaks=True)
        lines = []
        for line in cleaned.splitlines():
            normalized = line.strip()
            if not normalized or normalized == title or normalized == "Cast, Crew, and Company Info":
                continue
            lines.append(normalized)
        return lines

    def _parse_release_lines(self, lines: list[str]) -> tuple[str, str, str, str]:
        release_notes: list[str] = []
        genres = ""
        cast = ""
        runtime = ""

        for line in lines:
            if line == "Cast, Crew, and Company Info":
                continue
            if line.startswith("With:"):
                cast = line.removeprefix("With:").strip()
                continue
            if self.RUNTIME_RE.fullmatch(line):
                runtime = line
                continue
            if self._looks_like_release_note(line):
                release_notes.append(line)
                continue
            if not genres:
                genres = line
            else:
                release_notes.append(line)

        return " | ".join(release_notes), genres, cast, runtime

    def _looks_like_release_note(self, value: str) -> bool:
        normalized = value.casefold()
        return any(
            token in normalized
            for token in ("re-release", "re release", "anniversary", "program", "special engagement")
        )

    def _clean_html(self, value: str, *, keep_line_breaks: bool = False) -> str:
        if not value:
            return ""
        text = self.SVG_RE.sub("", value)
        text = self.IMG_RE.sub("", text)
        text = self.BLOCK_TAG_RE.sub("\n" if keep_line_breaks else " ", text)
        text = self.TAG_RE.sub("", text)
        text = html.unescape(text)
        if keep_line_breaks:
            lines = []
            for line in text.splitlines():
                normalized = self.WHITESPACE_RE.sub(" ", line).strip(" -\u00a0")
                if normalized:
                    lines.append(normalized)
            return "\n".join(lines)
        return self.WHITESPACE_RE.sub(" ", text).strip(" -\u00a0")

    def _parse_iso_date(self, value: str) -> date:
        return date.fromisoformat(value)

    def _fetch_release_items_for_window(
        self,
        window_start: date,
        window_end: date,
        anchor_dates: list[date],
    ) -> list[BoxOfficeMojoReleaseItem]:
        deduped: dict[tuple[str, str, str, str, str], BoxOfficeMojoReleaseItem] = {}
        with httpx.Client(timeout=self.timeout_seconds, headers=self._build_headers(), follow_redirects=True) as client:
            for anchor_date in anchor_dates:
                response = client.get(self.DATE_URL_TEMPLATE.format(anchor_date=anchor_date.isoformat()))
                if response.status_code >= 400:
                    raise BoxOfficeMojoCalendarError(
                        f"Box Office Mojo returned {response.status_code} for the calendar page starting "
                        f"{anchor_date.isoformat()}."
                    )
                for item in self.parse_release_page(response.text):
                    release_date = self._parse_iso_date(item.release_date)
                    if not window_start <= release_date <= window_end:
                        continue
                    key = (
                        item.release_date,
                        item.title,
                        item.url,
                        item.distributor,
                        item.scale,
                    )
                    deduped.setdefault(key, item)
        return list(deduped.values())

    def _build_anchor_dates(self, window_start: date, window_end: date) -> list[date]:
        anchors = [window_start]
        current = date(window_start.year, window_start.month, 1)
        while True:
            current = self._first_day_of_next_month(current)
            if current > window_end:
                break
            anchors.append(current)
        return anchors

    def _first_day_of_next_month(self, value: date) -> date:
        if value.month == 12:
            return date(value.year + 1, 1, 1)
        return date(value.year, value.month + 1, 1)

    def _add_months(self, value: date, months: int) -> date:
        year = value.year + (value.month - 1 + months) // 12
        month = (value.month - 1 + months) % 12 + 1
        day = min(value.day, self._days_in_month(year, month))
        return date(year, month, day)

    def _days_in_month(self, year: int, month: int) -> int:
        first_of_month = date(year, month, 1)
        first_of_next_month = self._first_day_of_next_month(first_of_month)
        return (first_of_next_month - timedelta(days=1)).day

    def _build_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": self.BASE_URL + "/calendar/",
        }
