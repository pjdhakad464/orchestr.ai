from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "data" / "social_profile_lookup_2026_04_30.csv"
REVIEWED_CSV = ROOT / "data" / "social_profile_lookup_2026_04_30_reviewed.csv"
PLATFORMS = ("Facebook", "Instagram", "X/Twitter", "TikTok")

MANUAL_ALLOW = {
    ("Avatar S2", "X/Twitter", "@avatarnetflix"),
    ("Criminal Minds S19", "TikTok", "@criminalminds"),
    ("Dexter Resurrection", "TikTok", "@dexteronshowtime"),
    ("Hoppers", "Instagram", "@hopperspixar"),
    ("Industry S4", "Instagram", "@industryhbo"),
    ("Marshals", "Instagram", "@marshalscbs"),
    ("Marshals", "TikTok", "@marshalscbs"),
    ("Only Murders in the Building", "TikTok", "@onlymurdersonhulu"),
    ("Paradise", "X/Twitter", "@paradiseonhulu"),
    ("Scream 7", "Facebook", "screammovies"),
    ("Scream 7", "Instagram", "@screammovies"),
    ("Scream 7", "TikTok", "@screammovies"),
    ("School Spirits S3", "TikTok", "@schoolspirits"),
    ("Scrubs", "Facebook", "scrubs"),
    ("Scrubs", "Instagram", "@scrubs"),
    ("Scrubs", "TikTok", "@official_scrubs"),
    ("Secret Lives of Mormon Wives S4", "Instagram", "@secretlivesonhulu"),
    ("Secret Lives of Mormon Wives S4", "TikTok", "@secretlivesonhulu"),
    ("South Park", "TikTok", "@southpark"),
    ("Survivor 50", "TikTok", "@cbssurvivor"),
    ("Tell Me Lies", "Facebook", "tellmelieshulu"),
    ("Tell Me Lies", "Instagram", "@tellmelieshulu"),
    ("Tell Me Lies", "X/Twitter", "@tellmelieshulu"),
    ("The Hunting Wives", "Instagram", "@thehuntingwives"),
    ("The Smashing Machine", "Instagram", "@thesmashingmachinemovie"),
    ("The Testaments", "TikTok", "@testamentsonhulu"),
}

AMBIGUOUS_TITLES = {
    "Bolero": "Ambiguous title; raw TMDB match points to an older 1981 film.",
    "Market Fish": "Ambiguous title; raw TMDB/search results did not line up with the requested project.",
    "Privileges": "Ambiguous title; no reliable title-specific official social result found.",
    "Vladimir": "Ambiguous title; search results were person accounts, not a project account.",
    "War": "Ambiguous title; raw TMDB/search results disagreed with the requested project.",
}

INVALID_HANDLES = {
    "100076903884453",
    "100067616590743",
    "61571096114515",
    "61574718002078",
    "photo.php",
    "p",
    "@popular",
    "@hbo",
    "@hulu",
    "@netflix",
    "@paramountplusca",
    "@paramountplusuk",
    "@paramountpicturesuk",
    "@rottentomatoes",
    "@sports.illustrated",
    "@thejaredbush",
    "@tvnz.official",
    "@zachbraff",
    "@imogenedenbrown",
    "@lupininlondon",
    "@the.nerdyverse",
    "@vladimir.1377",
    "@vladnicolaofficial",
    "cbrofficialpage",
    "comicbookdotcom",
    "comingsoon",
    "consequence",
    "deadline",
    "digitalspyuk",
    "disneyplus",
    "disneyplussg",
    "disneyplusuk",
    "docnycfest",
    "dwaynejohnson",
    "ellemagazine",
    "esther.ijewere",
    "garygulman",
    "griefspeaks",
    "guerillafilmmakers",
    "historicroyaltheater",
    "hollywoodreporter",
    "ign",
    "jaredleto",
    "journalsentinel",
    "menshealth",
    "narniaweb",
    "netflixfanslivehere",
    "netflixus",
    "netflxupdates",
    "paramountplus",
    "thebrianposehn",
    "theguardian",
    "themonoreport",
    "uscis",
    "whitesox",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "in",
    "of",
    "on",
    "s",
    "season",
    "the",
    "to",
}


def norm(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.lower()))


def title_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token not in STOP_WORDS and len(token) >= 3 and not re.fullmatch(r"s?\d+", token)
    ]


def handle_key(handle: str) -> str:
    return handle.strip().lower()


def likely_title_handle(title: str, handle: str) -> bool:
    handle_norm = norm(handle)
    if not handle_norm:
        return False
    tokens = title_tokens(title)
    if not tokens:
        return False
    hits = [token for token in tokens if token in handle_norm]
    if len(hits) >= 2:
        return True
    if len(tokens) == 1 and len(tokens[0]) >= 5 and tokens[0] in handle_norm:
        return handle_norm in {
            tokens[0],
            f"official{tokens[0]}",
            f"{tokens[0]}official",
            f"{tokens[0]}movie",
            f"{tokens[0]}movies",
            f"{tokens[0]}hulu",
            f"{tokens[0]}hbo",
            f"{tokens[0]}cbs",
            f"{tokens[0]}fx",
            f"{tokens[0]}netflix",
            f"{tokens[0]}pplus",
        }
    return False


def keep_hit(row: dict[str, str], platform: str) -> bool:
    source = row.get(f"{platform} Source", "")
    handle = row.get(f"{platform} Handle", "")
    title = row["Original Title"]
    if not row.get(f"{platform} URL", ""):
        return False
    if (title, platform, handle_key(handle)) in MANUAL_ALLOW:
        return True
    if title in AMBIGUOUS_TITLES:
        return False
    if source == "TMDB external IDs":
        return True
    if handle_key(handle) in INVALID_HANDLES or norm(handle).isdigit():
        return False
    if source == "Google knowledge graph":
        return True
    if likely_title_handle(row.get("Search Title", title), handle):
        evidence = (row.get(f"{platform} Evidence", "") or "").lower()
        if "official" in evidence or row.get(f"{platform} Confidence") == "High":
            return True
    return False


def main() -> None:
    with RAW_CSV.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    fieldnames = list(rows[0].keys())
    if "Review Notes" not in fieldnames:
        fieldnames.append("Review Notes")

    reviewed = []
    for row in rows:
        notes: list[str] = []
        if row["Original Title"] in AMBIGUOUS_TITLES:
            notes.append(AMBIGUOUS_TITLES[row["Original Title"]])
        for platform in PLATFORMS:
            if keep_hit(row, platform):
                continue
            if row.get(f"{platform} URL"):
                dropped = row.get(f"{platform} Handle") or row.get(f"{platform} URL")
                notes.append(f"Dropped weak {platform} candidate: {dropped}")
            for suffix in ("URL", "Handle", "Confidence", "Source", "Evidence"):
                row[f"{platform} {suffix}"] = ""
        if not any(row.get(f"{platform} URL") for platform in PLATFORMS):
            notes.append("No confident official title/franchise social profile found.")
        row["Review Notes"] = " | ".join(notes)
        reviewed.append(row)

    with REVIEWED_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reviewed)

    print(f"Wrote {REVIEWED_CSV}")


if __name__ == "__main__":
    main()
