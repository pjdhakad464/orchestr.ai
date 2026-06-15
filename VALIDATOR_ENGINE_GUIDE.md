# Data Ops Validator Guide & Playbook

This document is the official playbook for setting up, operating, and extending the Workbook Validation Engine. It defines the validation workflows, quality assurance standards, and criteria used to verify metadata and social platform links.

---

## 1. What This Engine Does
The validator lets you:
- Upload an Excel workbook (`.xlsx`) or CSV file (`.csv`), or paste a Google Sheets URL.
- Apply rule-based schema checks and content lookups.
- Run configurable **Smart Review Filters** to validate only specific scopes.
- Classify external links (such as Facebook profiles) into official vs. unofficial/fan/community pages.
- Highlight validation issues directly in the workbook (Red for errors, Orange for warnings) and add comment annotations.
- Download the validated workbook with a **Validation Summary** sheet added.

The validator is available in the app at:
- Local only: `http://127.0.0.1:8000/excel-validator`
- Same network/LAN: `http://<your-ip>:8000/excel-validator`

---

## 2. Validation Workflows & QA Standards
Reviewers must adhere to the following metadata lifecycle:
1. **Rule Setup**: Define validation schemas and exceptions in JSON format.
2. **Review Filter Selection**: Select the review mode matching your verification scope.
3. **Execution**: Run the validation engine to identify errors, format mismatches, and conflicts.
4. **Exception Handling**: Review red-highlighted cells in the exported file or dashboard table.
5. **Corrections**: Correct data rows and re-run validation until no issues remain.

---

## 3. Metadata Review Hierarchy
When verifying records, prioritize resolving fields in the following order:
1. **Primary Entity Validation**: Establish title category, title sub-category, and spelling conventions.
2. **Authority Lookup Matching**:
   - **Wikidata ID**: Verify QID aliases and sitelinks to confirm the identity.
   - **IMDb ID**: Verify IMDb ID types (`tt...` for movies/shows, `nm...` for names/talent) against the dataset.
3. **Official website presence**: Locate the official domain.
4. **Social Handles**: Verify social handles using verified badge indicators or cross-platform links.

---

## 4. Platform-Specific Social Review Criteria

### Facebook Validation Rules
The validator classifies Facebook page URLs into eight distinct authenticity types based on page text and structure:

| Category | Description |
| :--- | :--- |
| **Official** | Verified blue badge present, or confirmed official link from website/trusted bio. |
| **Official Regional** | Official regional page localized for countries/cities (e.g. "Facebook France"). |
| **Fan Page** | Page explicitly declared as fan-made, unofficial, backup, or tribute page. |
| **Community Page** | Standard community forum or group. |
| **Unofficial** | Active profile with correct name but lacking official verification indicators. |
| **Auto-generated** | Facebook topic page created automatically by Facebook. |
| **Suspicious/Impersonation** | Misleading branding or handle mismatch suggesting impersonation. |
| **Unable to Verify** | Private timeline, geoblocked page, or unreachable link. |

### YouTube Validation
- Flag channel usernames containing `%20` or `%7` (space or pipe character syntax errors).
- Verify that the channel display name or handle matches the title name.

---

## 5. Smart Review Filters
Configurable review modes allow checking targeted scopes of the worksheet:

* **Full Metadata Review**: Run all rules across all columns.
* **Social Handle Review Only**: Run rules for social media handles and URL columns.
* **Categorization Review**: Validate classification categories, sub-categories, and genre columns.
* **Platform-Specific Review**: Filter checks to a single platform (e.g. Facebook only).
* **Missing Data Review**: Check rules only on blank or empty cells to identify missing metadata.
* **Existing Data QA Review**: Check rules only on already-populated cells to check for correctness and broken links.
* **Duplicate & Conflict Review**: Perform global duplicate title scans and conflicting handle detection.

---

## 6. Confidence Scoring System
Issues are graded by confidence tiers to prioritize manual reviews:
- **High Confidence**: Clear programmatic proof of an error (e.g., HTTP 404, blocked timeline path segments `/p/`, `/pages/`, or exact database mismatch).
- **Medium Confidence**: Strong statistical indicators of a mismatch (e.g., name-to-handle spelling mismatch, regional branch mismatch).
- **Low Confidence**: Restricted verification context (e.g., connection timeout, HTTP 403 geoblocking, private profile, or unable to verify page quality text). Low-confidence items require descriptive reasons in the report.

---

## 7. Edge-Case Handling & Operational Rules
- **No Guessing**: Never guess handles or links. Leave the field blank or flag it if it cannot be proven.
- **Cross-Platform Cross-Linking**: Check if social accounts link to each other or back to the official site.
- **Inactive/Deprecated Accounts**: Flag accounts that have been inactive or have had no postings for more than 12 months.
- **Deduplication**: Scan handles and IDs globally to find duplicated profiles.

---

## 8. BDR Metadata QA Checks
The Workbook Validation Engine includes specialized audit rules to perform row-level metadata quality assurance of Brand Definition Reports (BDRs):

| Check Name | Target Column | What It Does | Flag Codes |
| :--- | :--- | :--- | :--- |
| `genre_taxonomy_audit` | `primary_genre`, `genre` | Validates genre arrays against TMDB/IMDb genre data for the title. Flags trailing newlines (`\n`), leading/trailing whitespace, blank placeholder spaces, and mismatches. | `GENRE_MISMATCH`, `FORMAT_ERROR`, `PLACEHOLDER` |
| `date_cross_check` | `released_on`, `street_date` | Cross-checks release dates against TMDB premiere/release date. Flags anomalous years (historical typos), blanks, and mismatches. | `DATE_MISMATCH`, `FORMAT_ERROR`, `PLACEHOLDER` |
| `network_platform_audit` | `network` | Validates network/distributor name against TMDB networks (for TV shows) and production companies (for movies). | `NETWORK_MISMATCH`, `FORMAT_ERROR`, `PLACEHOLDER` |
| `wikipedia_url_audit` | `wikipedia_url` | Resolves the Wikipedia article URL and validates that the resolved page title loosely matches the BDR title. | `WIKIPEDIA_MISMATCH`, `FORMAT_ERROR`, `MISSING_WIKIPEDIA` |
| `imdb_url_audit` | `imdb_id` | Resolves the IMDb ID or URL against dataset/TMDB find API and validates that the record title matches the BDR title. | `IMDB_MISMATCH`, `FORMAT_ERROR`, `MISSING_IMDB` |

### Running the BDR QA Script
A dedicated CLI script is provided to audit a workbook against BDR rules:
```bash
python scripts/validate_bdr.py <path-to-bdr.xlsx>
```

Options:
- `--rules <path>`: Custom rules JSON file (defaults to `data/bdr_qa_rules.json`).
- `--output <path>`: Save location of the output QA spreadsheet (defaults to `validated_runs/BrandDefinitionReport_QA.xlsx`).

The generated QA workbook contains three tabs:
1. **QA Findings**: Detailed row-by-row issues with categories, messages, and confidence levels.
2. **Clean Rows**: Rows from the original workbook that passed all validations.
3. **Summary Metrics**: Counts of clean vs. flagged rows, along with an issue code breakdown.
