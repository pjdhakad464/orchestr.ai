from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from metacritic_calendar_app.services.calendar import MetacriticCalendarService


DEFAULT_SNAPSHOT_DIR = Path("data") / "snapshots" / "metacritic"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Metacritic calendar data and maintain snapshot CSVs.")
    parser.add_argument(
        "--calendar-type",
        default="all",
        choices=["all", "games", "movies", "tv"],
        help="Which Metacritic calendar to fetch.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=str(DEFAULT_SNAPSHOT_DIR),
        help="Directory where latest and delta CSV files will be stored.",
    )
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file_handle:
        return list(csv.DictReader(file_handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
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
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row_key(row: dict[str, str]) -> str:
    return "|".join(
        [
            row.get("section", ""),
            row.get("release_date", ""),
            row.get("title", ""),
            row.get("url", ""),
        ]
    )


def main() -> None:
    args = parse_args()
    snapshot_dir = Path(args.snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    service = MetacriticCalendarService()
    snapshot = service.fetch_snapshot(args.calendar_type)
    latest_path = snapshot_dir / f"{args.calendar_type}_latest_snapshot.csv"

    new_rows = [
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
            "metascore": "" if item.metascore is None else str(item.metascore),
        }
        for item in snapshot.items
    ]

    old_rows = load_rows(latest_path)
    old_lookup = {row_key(row): row for row in old_rows}
    delta_rows: list[dict[str, str]] = []

    for row in new_rows:
        key = row_key(row)
        if old_lookup.get(key) != row:
            delta_row = dict(row)
            delta_row["change_type"] = "upsert"
            delta_rows.append(delta_row)

    removed_keys = set(old_lookup) - {row_key(row) for row in new_rows}
    for removed_key in sorted(removed_keys):
        delta_row = dict(old_lookup[removed_key])
        delta_row["change_type"] = "removed"
        delta_rows.append(delta_row)

    write_rows(latest_path, new_rows)
    print(f"Latest snapshot saved: {latest_path}")

    if delta_rows:
        delta_path = snapshot_dir / f"{args.calendar_type}_delta_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        fieldnames = list(delta_rows[0].keys())
        with delta_path.open("w", encoding="utf-8-sig", newline="") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(delta_rows)
        print(f"Changes detected: {len(delta_rows)}")
        print(f"Delta saved: {delta_path}")
    else:
        print("No changes detected.")


if __name__ == "__main__":
    main()
