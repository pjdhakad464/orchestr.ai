# Official Profile Finder

A FastAPI web app that helps you find likely official social profiles and reference pages for companies, celebrities, TV shows, movies, and game publishers or developers.

It now also includes an Excel workbook validator for task-review workflows. You can upload a `.xlsx` file, apply JSON-based checkpoints, and download the same workbook with failed cells highlighted in red plus a `Validation Summary` sheet.

It also includes a standalone title URL finder engine for movies and TV titles. Given a title plus optional year and movie/TV hint, it returns the best matching landing page on IMDb, Wikipedia, Rotten Tomatoes, and Metacritic, and it supports bulk lookup plus CSV/Excel export.

For a full setup and usage walkthrough, see [VALIDATOR_ENGINE_GUIDE.md](VALIDATOR_ENGINE_GUIDE.md).

## Features

- Search by entity name with optional type and country hints
- Separate talent search for influencers and celebrities with profession and DOB hints
- Separate media search for movies, TV shows, and TV networks backed by TMDB
- Bulk lookup for up to 500 lines per run
- Disambiguation step when a query maps to multiple likely entities
- Platform discovery for Facebook, Instagram, YouTube, X/Twitter, TikTok, Wikipedia, and IMDb
- Confidence scoring with short evidence notes and a valid-result threshold of 60
- Alternate candidates per platform when the best match is uncertain
- Results table with CSV, Excel, and optional Google Sheets export
- Lightweight in-memory caching for search sessions and repeated lookups
- Excel workbook validation with rule-based checks and downloadable reviewed files
- IMDb validation backed by the official `title.basics.tsv.gz` and `name.basics.tsv.gz` datasets with local caching

## Stack

- FastAPI
- Jinja2 templates
- HTMX-enhanced server-rendered UI
- Wikimedia APIs for free entity resolution
- TMDB for media title and network metadata
- Wikidata + official website link extraction for free profile discovery

## Configuration

Copy `.env.example` to `.env`.

Optional environment variables:

- `REQUEST_TIMEOUT_SECONDS` default: `12`
- `CACHE_TTL_SECONDS` default: `900`
- `WIKIMEDIA_CONTACT` optional descriptive contact string for Wikimedia API requests
- `WIKIPEDIA_CACHE_DIR` optional local cache folder for persistent Wikipedia lookups
- `WIKIPEDIA_REFRESH_HOURS` default: `24`
- `TMDB_API_KEY` optional TMDB v3 API key for Media Finder
- `TMDB_READ_ACCESS_TOKEN` optional TMDB bearer token for Media Finder
- `GOOGLE_SERVICE_ACCOUNT_FILE` path to a Google service account JSON file for Sheets export
- `GOOGLE_DRIVE_FOLDER_ID` optional Drive folder id for created sheets
- `IMDB_TITLE_BASICS_URL` default: `https://datasets.imdbws.com/title.basics.tsv.gz`
- `IMDB_NAME_BASICS_URL` default: `https://datasets.imdbws.com/name.basics.tsv.gz`
- `IMDB_DATASET_DIR` optional local cache/index folder for IMDb TSV validation data
- `IMDB_DATASET_REFRESH_HOURS` default: `24`

## Run

Once Python 3.11+ is available on your machine:

```bash
pip install -e .[dev]
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000`.

To run the title URL finder instead:

```bash
uvicorn title_url_lookup_app.main:app --reload --port 8001
```

If you pulled a newer version of the project with export features, rerun:

```bash
pip install -e .[dev]
```

## Test

```bash
pytest
```

## Notes

- The app is designed for a single internal user and does not persist history.
- Free mode uses Wikimedia plus official website extraction, so coverage is strongest when the entity has a good Wikidata record or a clearly linked official website.
- Media Finder uses TMDB when configured and is the recommended path for movies, TV shows, and TV networks.
- Confidence is evidence-based and heuristic; it is intended to assist review, not replace it.

## Workbook Validator Rules

The validator expects JSON with a `rules` array. Each rule targets one sheet and one column header.

Supported checks:

- `required`
- `equals`
- `not_equals`
- `in`
- `regex`
- `min`
- `max`
- `between`
- `unique`
- `date_not_past`
- `date_not_future`

Example:

```json
{
  "rules": [
    {
      "sheet": "Tasks",
      "column": "Task ID",
      "check": "unique",
      "message": "Task ID must be unique"
    },
    {
      "sheet": "Tasks",
      "column": "Status",
      "check": "in",
      "values": ["Open", "In Progress", "Done"]
    },
    {
      "sheet": "Tasks",
      "column": "Completion %",
      "check": "between",
      "min": 0,
      "max": 100
    }
  ]
}
```
