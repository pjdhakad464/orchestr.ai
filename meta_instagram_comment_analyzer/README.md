# Instagram Comment Dataset Analyzer

This is a standalone app that leaves your existing application untouched.

It is now built primarily for dataset uploads:

- upload a CSV or JSON file of Instagram comments from a compliant source
- remove comments that are related to Spotify
- keep sentiment and confidence for the remaining comments
- export the filtered results as CSV

An optional Meta path is still available for Instagram Professional accounts that authorize your app.

## Important boundary

For the Spotify Instagram account, use this app with a compliant exported dataset. Without Spotify's authorization, Meta's official API will not provide the comment text for that account.

## Features

- CSV and JSON dataset upload
- Spotify-related comment filtering
- sentiment scoring for off-topic comments
- CSV export for the filtered results
- small web dashboard
- optional Meta OAuth connect flow for accounts you manage

## Setup

1. Start the app.
2. Open the dashboard.
3. Upload a CSV or JSON file that contains Instagram comments.

The Meta credentials are only needed if you want the optional owner-authorized Meta flow.

## Run

```powershell
& 'C:\Users\Lenovo\AppData\Local\Programs\Python\Python314\python.exe' -m uvicorn meta_instagram_comment_analyzer.main:app --host 127.0.0.1 --port 8010 --reload
```

Open:

- `http://127.0.0.1:8010`

## Notes

- The app stores generated CSV exports in memory for a short-lived local workflow.
- Filtering and sentiment are heuristic, so you should review high-value outputs manually.
- The parser recognizes flexible input columns such as `text`, `comment`, `message`, or `body`.
- `META_OAUTH_SCOPES` is still configurable if you use the optional Meta path.

## Suggested production upgrades

- persistent export storage
- richer sentiment model
- dataset validation preview
- long-lived token exchange and refresh handling for the optional Meta path
- review feedback loop to improve the Spotify/off-topic classifier
