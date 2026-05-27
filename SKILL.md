---
name: metadata-classifier
description: Classify entities (people, brands, companies, athletes, networks, video games, restaurants, etc.) into an exact title_category and title_sub_category using a fixed approved taxonomy bundled with the skill. Use whenever the user provides a list of entities and asks for title_category / title_sub_category mapping, metadata tagging, taxonomy classification, brand/talent/network categorization, or says "classify these names", "tag these entities", "map these to categories", "run taxonomy mapping", or wants a metadata table with title / title_category / title_sub_category columns. Also use to QA, audit, or verify an existing classified file. Trigger when the user attaches a document (CSV, XLSX, DOCX, TXT) of entity names with social handles or URLs alongside a classification or QA request, since handles disambiguate identity. Trigger even when the user does not say "skill", the giveaway is a list of names plus a request for categorical labels or a QA pass.
---

# Metadata Classifier

A strict, taxonomy-bound entity classifier. Given a list of titles (people, brands, companies, athletes, networks, games, etc.), output an Excel-ready 3-column table mapping each to a `title_category` and `title_sub_category` value drawn ONLY from the approved taxonomy in `assets/taxonomy.xlsx`.

## What this skill does and does NOT do

**Does:**
- Maps each input entity to exactly one `title_category` value from the approved taxonomy.
- Builds a multi-line `title_sub_category` cell drawn from approved sub-category prefixes for that category.
- Outputs a strict 3-column table that is Excel-ready.
- Verifies every category and sub-category value against `assets/taxonomy.xlsx` before finalizing.

**Does NOT:**
- Invent categories, sub-categories, prefixes, or values that are not in the taxonomy file.
- Use synonyms, abbreviations, or "close enough" substitutes.
- Add explanations, notes, confidence scores, markdown commentary, or extra columns to the output.
- Guess gender, profession, or organization type without verification.

## The taxonomy file is the single source of truth

The file `assets/taxonomy.xlsx` (bundled inside this skill) contains two columns: `Title category` and `Title Sub Category`. Every valid output value must appear in that file exactly as written. Spelling, capitalization, punctuation, and spacing must match character-for-character.

The compact reference at `references/taxonomy_reference.md` lists every category and most sub-categories for fast in-context scanning. For categories with thousands of values (Video Game developers, Radio stations, Beverage companies, etc.), the reference points you at `scripts/lookup.py` for exact-spelling verification.

## Workflow

### Step 0: Check for an attached handles document

Before reading the taxonomy, check whether the user attached a document along with their classification request. The user often attaches a file (CSV, XLSX, DOCX, TXT) that lists the entity names alongside their official social media handles or profile URLs. When such a file is present:

1. List `/mnt/user-data/uploads/` and identify any file that maps names to handles or profile URLs. Typical column or line patterns: `Name, Instagram` / `Name, Twitter` / `Name, TikTok` / `Title, Handle` / `Title, URL`, or unstructured text like `Aliyah Boston @aliyah.boston`.
2. Parse the file and build an in-memory mapping from each input title to its known handles or profile URLs.
3. Treat handles and profile URLs as the highest-priority verification source for identity, ranking above generic web search. Two people share a name often, but the verified handle resolves it. If a handle is from a platform that signals the person's domain (NBA team account follow lists, official league pages linking to player profiles, the `@nfl` bio line, athlete profile URLs containing sport names, etc.), use that signal directly to fix `Talent Subtype` and `Talent Type`.
4. When the handles file is silent on an entity, fall back to the normal verification chain in Step 3.
5. If you find a handle but it does not load or returns ambiguous content, do not silently guess. Mark the row `UNVERIFIED` and note the handle you tried.

If no document is attached, skip this step and proceed to Step 1.

### Step 1: Read the taxonomy reference

Before classifying anything, read `references/taxonomy_reference.md`. This gives you the full list of valid `title_category` values and the prefix structure of `title_sub_category` for each.

### Step 2: For each input entity, identify primary commercial identity

Use this mapping rule of thumb (always confirm against the actual taxonomy):

| Entity type | Likely `title_category` |
|---|---|
| Individual person (athlete, actor, musician, journalist, creator, politician, chef, designer, etc.) | `Talent` |
| Sports team | `Sports Franchise` (or a combined category if the entity is both a team and a governing body) |
| Sports league / governing body | `Sports Franchise, Sports Organizations and Bodies` or similar combined value |
| TV network / channel | `TV Network` |
| Magazine, newspaper, publisher | `Publishers` |
| Restaurant chain | `Restaurants` |
| Beverage brand or company | `Beverages` |
| CPG (household, food, personal care) brand | `CPG` |
| Beauty / cosmetics brand | `Health & Beauty` or combined `CPG, Health & Beauty` / `Health & Beauty, CPG` |
| Fashion brand | `Fashion` |
| Travel brand (airline, hotel, cruise, etc.) | `Travel` |
| Radio station / market | `Radio` |
| Video game title | `Video Game` |
| Video game studio / publisher | `Video Game, Video Game Publishers` |
| Movie title | `Movies` (or combined `TV Shows, Movies` / `Movies, Film Studio`) |
| TV show / series | `TV Shows` (or combined `TV Shows, TV Network` / `TV Shows, Movies`) |
| Consumer electronics brand | `Consumer Electronics` |
| Retail chain | `Retail` |

If a category name in the taxonomy is comma-joined (e.g. `Sports Franchise, Sports Organizations and Bodies`), copy that comma-joined string exactly. Do not split it.

### Step 3: Verify the entity

Apply this source priority order before finalizing each row:
1. User-provided handles or profile URLs from the attached handles document (Step 0), when present
2. Official website
3. Verified social media profiles
4. Wikipedia
5. LinkedIn
6. IMDb
7. Official team / league pages
8. App Store / Google Play
9. Crunchbase
10. Trusted news sources

Use web search when the identity is not common knowledge or when there is any ambiguity (e.g. two people with the same name, a brand that has changed ownership, an athlete whose sport you are unsure of). Never classify based on name similarity alone.

#### Football vs Soccer disambiguation (mandatory check)

The taxonomy treats these as two distinct sports and the most common classification error is mixing them up. Apply this rule on every athlete classification:

- `Talent Subtype - Athlete - Football` means **American Football only**. Use this for NFL, NCAA football (FBS/FCS), CFL, XFL/UFL, USFL, Arena Football League, and any other American-football code. The ball is oval, the field has yard lines, and the league names include NFL, NCAA, CFL, UFL, etc.
- `Talent Subtype - Athlete - Soccer` means **Global Football (association football)**. Use this for Premier League, La Liga, Serie A, Bundesliga, Ligue 1, MLS, NWSL, Liga MX, FIFA World Cup, UEFA, CONCACAF, and any other association football competition worldwide. The ball is round, the field is a pitch, and the league names include EPL, MLS, NWSL, Champions League, etc.
- Australian Football (AFL) is its own subtype and lives under `Sports Type - Australian Football` at the franchise/league level. Do not collapse AFL players into either Football or Soccer.

Before finalizing any athlete row whose subtype would be Football or Soccer, explicitly confirm the sport from a verified source (official league site, team site, verified athlete handle, Wikipedia infobox). If the user is in a region where "football" colloquially means soccer (most of the world outside the US), be especially careful, the user-provided list may use the word "football" loosely while the taxonomy requires the precise mapping above.

Quick examples:
- Patrick Mahomes, Travis Kelce, Caleb Williams → `Talent Subtype - Athlete - Football` (American Football, NFL/NCAA).
- Lionel Messi, Megan Rapinoe, Erling Haaland, Sam Kerr → `Talent Subtype - Athlete - Soccer` (Global Football, MLS/NWSL/EPL/etc.).
- Marcus Bontempelli, Patrick Cripps → Australian Football. There is no `Athlete - Australian Football` Talent Subtype in the taxonomy, so verify with `scripts/lookup.py search "Australian"` and mark the closest valid value or `UNVERIFIED` if none exists.

When you cannot verify with confidence and search is unavailable or returns nothing useful, mark that row's category and sub-category as `UNVERIFIED` rather than guessing. Tell the user at the end which rows were unverified and why.

### Step 4: Build the `title_sub_category` cell

The cell is multi-line inside a single Excel cell (newlines, no commas separating lines, no bullets).

For **Talent** entities, the order is fixed and all three lines are mandatory:
```
Gender - <Man | Woman | Non-Binary>
Talent Subtype - <subtype from taxonomy>
Talent Type - <type from taxonomy>
```

Examples (all verified in the taxonomy):
```
Gender - Woman
Talent Subtype - Athlete - Basketball
Talent Type - Athlete
```
```
Gender - Man
Talent Subtype - Musician - Rapper
Talent Type - Musician
```
```
Gender - Woman
Talent Subtype - Media Personality - TV
Talent Type - Journalist
```

Notes on Talent rules:
- `Gender` valid values are exactly: `Man`, `Woman`, `Non-Binary`. Use the person's publicly stated identity from verified sources. If genuinely unknown, write `UNVERIFIED` for that line.
- `Talent Subtype` and `Talent Type` come from the fixed lists in the reference. Cross-check them. For example, a basketball player is `Talent Subtype - Athlete - Basketball` and `Talent Type - Athlete`. A rapper is `Talent Subtype - Musician - Rapper` and `Talent Type - Musician`. The `Talent Type` is always the broader category that the subtype belongs to.
- Actor vs. Actress: the taxonomy has both as distinct `Talent Type` values. Use `Actor` for men and non-binary actors, `Actress` for women, unless the person publicly self-identifies differently.

For **non-Talent** entities, build the multi-line cell using only the prefixes that exist for that category in the taxonomy. Use 1 to 4 of the most informative prefixes. Common patterns:

- `TV Network`: `Region - <region>`, `Community Type - <type>`, `Location: Country - <country>`, `Streaming Type - <type>`. Use only those that apply.
- `Sports Franchise`: `Location: City - <city>`, `Location: State - <state>`.
- `Sports Franchise, Sports Organizations and Bodies`: `League Type - <type>`, `Sports Type - <sport>`, `Team / League Category - <Men's | Women's | Mixed>`, etc.
- `Publishers`: `Publication Type - <type>`.
- `Restaurants`: `Restaurant Category - <category>`, `Restaurant Type - <type>`, `Restaurant Presence - <presence>`, `Restaurant Ownership - <ownership>`.
- `Beverages`: `Beverage Company - <name>`, `Beverage Type - <type>`, plus `Spirits Type` / `Whiskey Type` / `Beer Type` where relevant.
- `Video Game`: `Developer - <name>`, `Publisher - <name>`, `Platform - <platform>`, `Rating - <rating>`. List multiple platforms each on its own line if the game is multi-platform AND each platform is in the taxonomy.
- `Radio`: `Station - <call letters>` and/or `Radio Market - <market>`.
- `Travel`: `Travel Type - <Airlines | Hotels | Cruise Lines | Booking Sites | Car Rental | Amusement Parks>`.

Rule of thumb: every line in the cell must, when prepended to the category, match a real row in `assets/taxonomy.xlsx`. If a prefix has no valid value for this entity in the taxonomy, omit the line. Never invent a prefix.

### Step 5: Validate with the lookup script (mandatory for non-obvious cases)

For any entity where you are not 100% certain of the spelling of a sub-category value (especially Video Game developers/publishers, Radio stations, Beverage companies, Beauty companies, athlete subtype phrasing, or any compound category name), run the lookup script before finalizing:

```bash
# Confirm a specific (category, sub_category) pair exists exactly
python scripts/lookup.py check "Talent" "Talent Subtype - Athlete - Basketball"

# Find the correct spelling of a value by substring
python scripts/lookup.py search "Sony"

# List valid values for a prefix
python scripts/lookup.py values "Talent" "Talent Type"

# List all sub-categories under a category
python scripts/lookup.py subcats "TV Network"

# List all valid title_category values
python scripts/lookup.py categories
```

If `check` returns `MISSING`, the pair is not in the taxonomy and you must either find the correct spelling via `search` or drop that line from the cell.

### Step 6: Produce the output

Output a Markdown table with exactly these three columns and no others:

```
| title | title_category | title_sub_category |
```

Rules for the output:
- Preserve the user's input order.
- One row per input entity.
- The `title_sub_category` cell contains multiple lines. In Markdown, represent line breaks inside the cell with `<br>` so the table renders correctly in chat. When the user wants this in an .xlsx file, use real newlines inside the cell.
- No extra columns, no explanations, no notes, no markdown commentary, no confidence scores, no bullets, no numbering inside cells.
- After the table, if any rows are marked `UNVERIFIED`, add one short paragraph listing those rows and what additional information would resolve them. Do not add any other commentary.

### Step 7: Offer an Excel download

If the user asked for an Excel file, or the list is longer than ~15 rows, also save the result to `/mnt/user-data/outputs/classification.xlsx` with proper newlines inside the `title_sub_category` cell and `wrap_text=True` applied so it displays correctly in Excel. Use openpyxl. Then call `present_files` so the user can download it.

A minimal Python pattern:
```python
import openpyxl
from openpyxl.styles import Alignment
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["title", "title_category", "title_sub_category"])
for title, cat, sub in rows:
    ws.append([title, cat, sub])
wrap = Alignment(wrap_text=True, vertical="top")
for row in ws.iter_rows(min_row=1):
    for cell in row:
        cell.alignment = wrap
ws.column_dimensions['A'].width = 30
ws.column_dimensions['B'].width = 25
ws.column_dimensions['C'].width = 50
wb.save("/mnt/user-data/outputs/classification.xlsx")
```

## Output format example

Input:
```
Aliyah Boston
Allie LaForce
Andre Drummond
```

Output:

| title | title_category | title_sub_category |
|---|---|---|
| Aliyah Boston | Talent | Gender - Woman<br>Talent Subtype - Athlete - Basketball<br>Talent Type - Athlete |
| Allie LaForce | Talent | Gender - Woman<br>Talent Subtype - Media Personality - TV<br>Talent Type - Journalist |
| Andre Drummond | Talent | Gender - Man<br>Talent Subtype - Athlete - Basketball<br>Talent Type - Athlete |

## QA mode: auditing an existing classified file

When the user uploads a file that already has `title_category` and `title_sub_category` columns filled in and asks you to QA, check, audit, review, or verify the classifications (instead of producing new ones), switch to QA mode:

1. Read the file. Identify the columns for title, title_category, title_sub_category, and any social media handle / URL columns (Twitter, Instagram, TikTok, Facebook, YouTube, Wikipedia, IMDb, etc.).
2. Strip any trailing suffix the user calls out (e.g. " - DAR") from each title.
3. For every row, run all five checks below. A row can have more than one issue. Capture all of them, not just the first.
   - **Check A: Does the title_category exist in the taxonomy?** Run `python scripts/lookup.py categories` to enumerate valid values. Invalid categories like `Podcasts`, bare `Sports Organizations and Bodies`, `Influencer`, etc. are immediate flags.
   - **Check B: Is the title_category appropriate for the entity?** A person (coach, creator, athlete, journalist) almost always belongs in `Talent`, not in a brand category like `Fashion` or `Sports Organizations and Bodies`.
   - **Check C: Is the title_sub_category blank or missing?** A blank sub-category on any row is a flag. Use handles and Wikipedia URLs to propose what it should be.
   - **Check D: For Talent rows, is the sub-category complete?** Every Talent row must have all three lines: `Gender - <...>`, `Talent Subtype - <...>`, and `Talent Type - <...>`. Flag any Talent row missing any of the three. The Talent Type is almost always derivable from the existing Talent Subtype (e.g. `Talent Subtype - Athlete - Football` implies `Talent Type - Athlete`, `Talent Subtype - Musician - Rapper` implies `Talent Type - Musician`), so the proposed fix should fill that in deterministically. Gender requires verification from handles/Wikipedia.
   - **Check E: Is the title_sub_category internally consistent and substantively correct?** For Talent rows, the Athlete subtype must match the actual sport (Football vs Soccer disambiguation applies). Use the Wikipedia URL qualifier and the verified social handles as the primary identity signals.
4. Produce a findings workbook at `/mnt/user-data/outputs/<original-filename>_QA_findings.xlsx` with **multiple sheets**, one per issue category, so the user can triage:
   - Sheet 1: Wrong category or wrong sub-category (substantive misclassification, Checks A, B, E).
   - Sheet 2: Talent rows with BLANK sub-category (Check C on Talent).
   - Sheet 3: Talent rows with INCOMPLETE sub-category, i.e. missing one of Gender / Talent Subtype / Talent Type (Check D). Include a "Proposed fix" column that fills in the deterministic pieces.
   - Add other sheets as needed for non-Talent rows with blank sub-categories.
   Each sheet has its own column set tailored to the issue, but every row is identified by Row # and Title.
5. Do not edit the input file. Issue a findings file the user can review and apply manually.
6. Be exhaustive on systematic errors (Football vs Soccer especially, plus incomplete Talent rows) but do not invent issues. If a row passes all five checks, do not include it in the findings.
7. Summarize the findings briefly in chat: total rows audited, total flagged, and a one-line description of each issue category. Note which findings are deterministic fixes (e.g. derive Talent Type from Talent Subtype) vs which require external verification (e.g. Gender from handles).

## Common pitfalls to avoid

- **Inventing prefixes.** The taxonomy uses a fixed set of prefixes per category. Do not invent `Entity Type`, `Network Type`, `Industry`, `Content Type`, `Business Model`, or any other prefix that does not appear in the taxonomy file for that category. (The example "ESPN" sub-category given in the user's onboarding prompt uses invented prefixes that are NOT in the taxonomy. Use the real prefixes from `references/taxonomy_reference.md`.)

- **Wrong Talent Type / Subtype pairing.** Every `Talent Subtype` belongs under one specific `Talent Type`. Examples: `Athlete - Basketball` pairs with `Talent Type - Athlete`; `Musician - Rapper` pairs with `Talent Type - Musician`; `Media Personality - TV` pairs with `Talent Type - Journalist` OR `Talent Type - Media Personality` depending on the person. Verify the pairing using sources.

- **Comma in category name vs comma in cell.** Some `title_category` values literally contain commas (e.g. `Sports Franchise, Sports Organizations and Bodies`). That is part of the value, not a list separator. Copy it whole.

- **Compound entities.** Some entities are both a team and a league body, or both a TV show and a network. Check the taxonomy for the matching combined category before defaulting to a single-category one.

- **Football vs Soccer mix-up.** `Athlete - Football` is American Football only (NFL, NCAA, CFL, UFL, etc.). `Athlete - Soccer` is Global Football / association football (EPL, La Liga, MLS, NWSL, FIFA, etc.). The user's list may say "football" when they mean either one, depending on the region. Always confirm the sport from a verified source before locking in the subtype. Australian Football is a third, separate code and does not map to either subtype.

- **Ignoring an attached handles document.** When the user attaches a CSV, XLSX, DOCX, or TXT file alongside the name list, it almost always contains the official handles or profile URLs and is the single fastest way to disambiguate identity. Always read it before web searching.

- **Incomplete Talent sub-category.** Every Talent row needs all three lines: `Gender`, `Talent Subtype`, and `Talent Type`. Two-line or one-line Talent rows are incomplete. The Talent Type is deterministically derivable from the Talent Subtype (everything before the second hyphen, e.g. `Athlete - Football` → `Athlete`, `Musician - Rapper` → `Musician`), so missing Talent Type is always fixable mechanically. Missing Gender requires identity verification from handles/Wikipedia.

- **Skipping verification.** Two athletes with the same name can play different sports. A brand named "Apollo" could be a streaming service, a music label, or a restaurant chain. Always verify identity before classifying.

- **Person mistaken for organization (especially coaches).** A coach is a person, so the category is `Talent`, not `Sports Organizations and Bodies`. Use `Talent Subtype - Athlete - Coach` and `Talent Type - Athlete`. Apply the same logic to general managers, team executives, and league commissioners only if they are explicitly named as individuals.

- **Content creator mistaken for the brand they create content about.** A fashion influencer, beauty creator, or food vlogger is `Talent` (typically `Talent Subtype - Internet Personality - Influencer` or `- Content Creator` plus `Talent Type - Internet Personality`), NOT `Fashion`, `Health & Beauty`, or `Restaurants`. The brand categories are for the underlying companies and labels, not the people who review or promote them. Check bios on the verified handle: "creator", "content", "host", "blogger", or "personality" language is a tell.

- **Invalid title_category values.** Always confirm the category itself exists in the taxonomy. `Podcasts`, `Sports Organizations and Bodies` (alone), `Influencer`, `Creator`, etc. look reasonable but are not in `assets/taxonomy.xlsx`. Run `python scripts/lookup.py categories` if in doubt. If no valid category fits the entity, mark it `UNVERIFIED` and flag for review.

- **Wikipedia URL disambiguator is gold.** When an entity's Wikipedia URL ends with a qualifier in parentheses, e.g. `Cole_Turner_(soccer)`, `Corey_Brown_(American_football)`, `John_Smith_(actor)`, that qualifier resolves identity definitively. Read the qualifier before classifying. A bare URL like `Eli_Manning` (no qualifier) signals there is only one notable person with that exact name on Wikipedia, also useful.

- **Adding explanations.** The final deliverable is just the table. Do not pad it with prose, headers, or summaries. The only allowed addition is a brief list of `UNVERIFIED` rows at the end if any exist.

## Bundled files

- `assets/taxonomy.xlsx` — the authoritative taxonomy. Do not edit.
- `references/taxonomy_reference.md` — compact human-readable list of every category and most sub-categories. Read this at the start of every task.
- `scripts/lookup.py` — CLI helper to verify spelling and existence of taxonomy values. Call this whenever you are unsure of a sub-category's exact wording.
