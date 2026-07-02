# Apply-BDR diff QA — ticket file 327865 (Paramount international pages)

**Date:** 2026-07-02
**Input:** `20260701ApplyBrandDefinitionReport_327865.xlsx` (BrandIngest sheet, 42 cols,
12 brands × 2 rows: `INGESTED` + `FROM DB`)
**Output:** [`output/20260701ApplyBrandDefinitionReport_327865_QA.xlsx`](output/20260701ApplyBrandDefinitionReport_327865_QA.xlsx)

## Request

Improve the Apply-BDR output format to show **two rows per brand** (ingested vs
database) with change highlighting, add a **URL Manager** section comparing
`url_managers` entries against the URLs maintained in each row's platform columns,
and keep the existing report layout/formatting unchanged.

## Approach

Processed with the **Apply Report QA** mode of the OrchestrAI Data Ops Validator
(`POST /bdr-apply-report`, service `app/services/apply_bdr_report.py`):

- Rows pair on `brand_id`; the INGESTED cell is highlighted where it differs from
  FROM DB — green = added (DB blank), red = removed (DB had value), yellow =
  changed (comment carries the DB value).
- Multi-line fields (`brand_set`, `twitter_search_terms`, `url_managers`, …) are
  compared as unordered line-sets, so the DB's reordered lines never false-flag.
- `url_managers` entries (`platform|url|company`) are cross-checked against the
  row's own maintained columns (facebook_page, twitter_handle, instagram_user,
  youtube_channel_username, tiktok_user, linkedin_page, …). Slug-normalised
  matching (URL vs bare handle); a multi-line maintained cell matches on any line.
- Source file's own formatting (green FROM DB fills, red TST fills) preserved.

## Findings (this file)

- 12/12 pairs diffed: 1 cell added, 16 changed, 0 removed.
- `Paramount Pictures (Australia) - DAR`: DB `url_managers` was **empty**; the
  ingest added all 5 entries (green).
- Most DAR rows: `brand_set` line-set changed vs DB (yellow, DB value in comment).
- 13 URL Manager findings, mostly `tiktok` / `instagram` entries **MISSING in
  url_managers** on FROM DB rows while the handle is maintained in the row.
- Data quirk worth review: `Paramount Pictures (France)` FROM DB `linkedin_page`
  contains a pipe suffix (`viacom-networks-france|DAR`) → flagged MISMATCH.
- Germany rows maintain **two** twitter handles in one cell
  (`paramountGER` + `Paramount_Kino`); url_managers covers the second — treated
  as a match (any-line rule), not flagged.

## Reusable notes

- Apply-BDR exports keep INGESTED/FROM DB adjacency and a `record_type` column —
  pair on `brand_id`, never on row order.
- `twitter_handle` in Apply exports can be a **bare** handle while `url_managers`
  holds full URLs — always slug-normalise before comparing.
- The "URL Manager" sheet in the output lists every platform comparison
  (OK / MISMATCH / MISSING / ORPHAN) — filter the status column for triage.
