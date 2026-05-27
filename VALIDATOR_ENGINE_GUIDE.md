# Data Ops Validator Guide

This guide explains how to set up, run, and use the workbook validation engine from scratch.

## 1. What This Engine Does

The validator lets you:

- upload an Excel workbook (`.xlsx`)
- upload a CSV file (`.csv`)
- load a Google Sheet with a shared URL or spreadsheet id
- apply rule-based checks to your sheet data
- highlight failed cells in red
- add helpful comments directly inside the failed cells
- download the same workbook with a `Validation Summary` sheet added

The validator is available in the app at:

- local only: `http://127.0.0.1:8000/excel-validator`
- same network/LAN: `http://<your-ip>:8000/excel-validator`

## 2. Main Use Case

This engine is designed for workbook-based QA and task verification, especially where teams review:

- title metadata
- category rules
- DAR-specific company and brand rules
- movie release date, release type, and genre recommendations
- Rotten Tomatoes URL validation for `rottentomatoes`
- social/reference fields like Facebook, Wikipedia, and IMDb

## 3. Prerequisites

You need:

- Windows machine
- Python 3.11+ installed
- project folder available locally
- internet access for TMDB, Wikipedia, OMDb, and the IMDb dataset download on first run

Optional but currently used in this project:

- TMDB credentials for movie lookups
- OMDb API key for IMDb verification
- Google service account credentials for validating Google Sheets

## 4. Project Setup

Open PowerShell in the project folder:

```powershell
cd C:\Users\Lenovo\Documents\Playground
```

Install dependencies:

```powershell
python -m pip install -e .[dev]
```

If `python` is not on PATH, use the full Python path instead:

```powershell
& 'C:\Users\Lenovo\AppData\Local\Programs\Python\Python314\python.exe' -m pip install -e .[dev]
```

## 5. Configuration

The project reads settings from `.env`.

Important values:

- `REQUEST_TIMEOUT_SECONDS`
- `CACHE_TTL_SECONDS`
- `WIKIMEDIA_CONTACT`
- `WIKIPEDIA_CACHE_DIR`
- `WIKIPEDIA_REFRESH_HOURS`
- `TMDB_API_KEY`
- `TMDB_READ_ACCESS_TOKEN`
- `OMDB_API_KEY`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `IMDB_TITLE_BASICS_URL`
- `IMDB_NAME_BASICS_URL`
- `IMDB_DATASET_DIR`
- `IMDB_DATASET_REFRESH_HOURS`

If you want to create a fresh config, copy `.env.example` to `.env` and fill in the required keys.

## 6. How To Run The App

### Local-only mode

Use this if only the same computer will open the validator:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

`http://127.0.0.1:8000/excel-validator`

### LAN mode

Use this if other systems on the same network need access:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open from another system using:

`http://<your-local-ip>:8000/excel-validator`

Example:

`http://172.16.16.46:8000/excel-validator`

Note:

- both machines must be on the same network
- Windows Firewall may need to allow port `8000`
- your local IP can change later

### Start automatically at login

If you want the validator engine to come back automatically after signing into Windows, use the included scripts:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_engine.ps1
```

To register automatic startup at logon for the current user:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_engine_startup.ps1
```

This creates a Windows scheduled task named `Playground Validator Engine` that launches the app in the background and reuses `uvicorn.out.log` and `uvicorn.err.log`.

## 7. How To Use The Validator

1. Open the validator page.
2. Upload the Excel workbook or CSV file, or paste the Google Sheets URL.
3. Keep the default rules, or replace them with your own JSON rules if needed.
4. Run validation.
5. Review the summary and download the validated workbook.

The downloaded workbook includes:

- failed cells filled in red
- validator comments inside failed cells
- a `Validation Summary` sheet listing all issues

## 8. What The Current Rules Check

### Core metadata checks

- `title` cannot be blank, `#NA`, or `N/A`
- `title_category` must be in the approved list
- `title_sub_category` is required only for `Talent`, `Movies`, and `TV Shows`
- `genre` is required only for `Movies` and `TV Shows`
- `primary_genre` is required when `genre` is populated

### DAR checks

- if `title` ends with ` - DAR`, `companies` must contain:
  - `Pristine Brand`, or
  - `Pristine Talent`, or
  - `Pristine Film`
- if `title_category = TV Shows`, `companies` can also contain `Pristine TV`
- if `title` ends with ` - DAR`, `brand_set` must contain `Pristine DAR Brands`
- if `title` does not end with ` - DAR`, `brand_set` must contain `Competitive View`

### Talent checks

When `title_category = Talent`, `title_sub_category` must include:

- `Gender -`
- and either `Talent Type -` or `Talent Subtype -`

### Movie checks

When `title_category = Movies`, the validator can:

- compare `released_on` with the TMDB USA release date
- compare `release_type` with the TMDB release type recommendation
- compare `genre` with TMDB genres

For date and genre mismatches, the workbook comment shows the TMDB value directly so users can correct it faster.

- compare `rottentomatoes` with the Rotten Tomatoes page found from the title and release year from `released_on`
- for Rotten Tomatoes mismatches, the workbook comment shows the correct Rotten Tomatoes URL

### Facebook checks

`facebook_page` can be blank, but if populated it fails when it contains:

- `/p/`
- `/page/`
- `/pages/`
- `/php/`
- `profile.php`

### Social/reference format checks

The validator checks format rules for:

- `twitter_handle`
- `instagram_user`
- `youtube_channel_username`
- `tiktok_user`
- `wikidata_id`
- `imdb_id`

### Wikidata and IMDb truth checks

If these fields are present, the validator also performs lookup-based verification:

- `wikidata_id`
  - validates the `Q...` id or Wikidata item URL format
  - fetches labels, aliases, sitelinks, and entity type from Wikidata
  - uses the Wikipedia sitelink and aliases to compare against workbook `title`
  - rejects disambiguation items

- `imdb_id`
  - validates the IMDb id/page format
  - first checks `tt...` ids against the official IMDb `title.basics.tsv.gz` dataset
  - first checks `nm...` ids against the official IMDb `name.basics.tsv.gz` dataset
  - stores a local cached SQLite index so repeated validations stay fast
  - falls back to OMDb or the IMDb page only when the dataset lookup is unavailable
  - compares the returned title or name with workbook `title`

## 9. How The Rule Engine Works

The rule engine is driven by JSON.

Each rule defines:

- `sheet`
- `column`
- `check`
- optional `when`
- optional `message`
- optional `values`, `value`, `tokens`, `pattern`, `min`, `max`

Example:

```json
{
  "sheet": "*",
  "column": "brand_set",
  "check": "contains",
  "value": "Competitive View",
  "when": [
    {
      "column": "title",
      "operator": "not_endswith",
      "value": " - DAR"
    }
  ],
  "message": "Non-DAR titles must include Competitive View in brand_set."
}
```

## 10. Key Files

Main application entry:

- `app/main.py`

Routes and validator endpoint:

- `app/routes.py`

Validation engine:

- `app/services/workbook_validator.py`

Rule definitions/models:

- `app/models.py`

Validator UI:

- `app/templates/validator.html`
- `app/templates/_validator_panel.html`
- `app/templates/_validation_results.html`

Styling:

- `app/static/styles.css`

Tests:

- `tests/test_workbook_validator.py`
- `tests/test_app.py`

## 11. How To Run Tests

```powershell
python -m pytest
```

Or with the known Python path:

```powershell
& 'C:\Users\Lenovo\AppData\Local\Programs\Python\Python314\python.exe' -m pytest
```

## 12. Common Troubleshooting

### App does not open

Check whether port `8000` is listening:

```powershell
netstat -ano | findstr :8000
```

If nothing is listening, start the app again.

### Another system cannot open the app

Check:

- app is started with `--host 0.0.0.0`
- both machines are on the same network
- Windows Firewall is not blocking port `8000`

### Wikipedia shows `HTTP 403`

The validator now falls back to the real article page if the API is blocked. If this still happens, verify:

- the page opens in a browser
- the workbook value points to an actual article path
- there is no proxy/network policy blocking Wikipedia
- `WIKIPEDIA_CACHE_DIR` is writable if you configured a custom cache path

### IMDb does not validate

Check:

- the first dataset download from IMDb completed successfully
- `IMDB_TITLE_BASICS_URL` and `IMDB_NAME_BASICS_URL` are reachable or point to local files
- `OMDB_API_KEY` is present in `.env`
- the value is a valid `tt...` or `nm...` id, or an IMDb title/name URL

### Validation is slow

The first IMDb dataset build can take longer because the validator downloads and indexes the official TSV files. After that, repeated IMDb checks use the local index and are much faster.

## 13. Recommended Team Workflow

1. Keep one standard rule set for the team.
2. Upload the latest workbook.
3. Run validation before manual QA.
4. Review only the red cells and summary items.
5. Correct the workbook and re-run validation.

This keeps the manual review focused on exception handling instead of repetitive checking.
