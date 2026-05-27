# Instagram Comment News Filter

This is a standalone prototype that keeps your current application untouched.

It helps you identify Instagram comments that are:

- not related to Spotify
- likely related to world news
- likely related to locale news

## Important platform note

This project does **not** include scraping of public third-party Instagram comments.

Supported collection paths:

- upload a CSV or JSON file that already contains comments
- use the owner-authorized Instagram Graph API route for media you are allowed to manage

## Project layout

- `main.py`: FastAPI app
- `classifier.py`: rule-based classifier
- `io_utils.py`: CSV/JSON parser
- `instagram_api.py`: owner-authorized Meta API collector
- `sample_comments.csv`: quick test input

## Run

From the workspace root:

```powershell
& 'C:\Users\Lenovo\AppData\Local\Programs\Python\Python314\python.exe' -m uvicorn instagram_comment_news_filter.main:app --reload
```

Then open:

- `http://127.0.0.1:8000/docs`

## Endpoints

### 1. Classify JSON comments

`POST /classify`

Example body:

```json
{
  "locale_hint": "Kolkata, India",
  "local_terms": ["kolkata", "west bengal", "india"],
  "candidates_only": true,
  "comments": [
    {"comment_id": "1", "text": "Petrol prices in Kolkata are wild this week."},
    {"comment_id": "2", "text": "Spotify please fix the shuffle."}
  ]
}
```

### 2. Upload a CSV or JSON file

`POST /classify-file`

Accepted fields:

- `comments_file`
- `locale_hint`
- `local_terms`
- `candidates_only`

CSV columns can be flexible. The parser recognizes:

- comment text: `text`, `comment`, `message`, `body`
- comment id: `comment_id`, `id`
- username: `username`, `user`, `author`
- timestamp: `timestamp`, `created_at`, `time`

### 3. Owner-authorized Instagram collection

`POST /instagram/media/{media_id}/comments/classify`

Before using it, set:

```powershell
$env:INSTAGRAM_ACCESS_TOKEN="your-owner-authorized-token"
$env:INSTAGRAM_GRAPH_API_VERSION="vYOUR_VERSION"
```

This endpoint is intended only for Instagram media you are authorized to access through Meta's official API.

## How to use this for your requirement

1. Collect comments through a compliant path.
2. Send them to this app.
3. Keep only records where `category` is `world_news` or `local_news`.
4. Review borderline results manually.

## Suggested next upgrade

The current classifier is heuristic and lightweight. If you want better accuracy later, the clean upgrade path is:

1. keep this collector/parser layer
2. replace the rule-based classifier with an LLM or fine-tuned text classifier
3. add review feedback to improve precision over time

