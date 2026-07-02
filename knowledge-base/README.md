# DataOps Knowledge Base

A reusable history of completed DataOps queries and their outputs. Before starting
a new BDR / QA / enrichment request, **search here first** — if a similar request
was already processed, reuse the query notes and output instead of re-researching.

## Entry convention

One folder per completed request:

```
knowledge-base/
  YYYY-MM-DD_<short-slug>/          e.g. 2026-07-02_apply-bdr-327865
    query.md                        what was asked, decisions made, findings
    output/<result file(s)>         the delivered artifact(s)
```

`query.md` structure:

- **Request** — the ask, verbatim or summarised, plus the input file name.
- **Approach** — how it was processed (tool/mode used, rules applied).
- **Findings / flags** — QA flags, disambiguation risks, NOT FOUND items.
- **Reusable notes** — anything a teammate can lift for a similar request.

## Notes

- Input files are generally **not** duplicated here when the output preserves the
  full input layout (e.g. Apply-BDR QA reports contain every input row).
- This repository is **public** (owner's decision, 2026-07-02). Before committing a
  KB entry, check the output for anything confidential (credentials, unreleased
  titles, private contact info) — brand social URLs/handles are already public data.
- The OrchestrAI tools that generate these outputs live in this same repo
  (Data Ops Validator → Validate / BDR Ingest Builder / Apply Report QA tabs).
