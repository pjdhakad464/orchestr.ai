# OrchestrAI — Database (Supabase / PostgreSQL)

The platform is **datastore-agnostic**: all persistence goes through the
`Repository` interface in `app/data/`. With no database configured it uses an
in-memory adapter (ephemeral). Point it at Supabase to make everything
durable — **no application code changes required.**

## One-time setup

1. **Create a Supabase project** (free tier is fine).
2. **Run the schema**: open the Supabase SQL Editor and paste
   `db/migrations/0001_initial_schema.sql`, then Run.
3. **Add the driver**: append `psycopg[binary]>=3.1,<4` to `requirements.txt`
   (kept out by default so the app has no hard DB dependency until you attach
   one).
4. **Set the connection string** as an environment variable in Vercel:
   - `DATABASE_URL` = the Supabase **connection pooler** URI
     (Project → Settings → Database → *Connection Pooling*, port **6543**,
     mode **transaction** — this is the serverless-safe endpoint).

That's it. On the next deploy, `get_repository()` detects `DATABASE_URL`,
activates `PostgresRepository`, and the Approval Queue's "ephemeral store"
banner disappears.

## What's stored (normalized, built for growth)
`channels` · `request_types` · `validation_rules` · `qa_templates` ·
`folder_templates` · `response_templates` · `tickets` (+ `snapshot` jsonb) ·
`ticket_entities` · `validation_findings` · `qa_reports`/`qa_items` ·
`research_outputs` · `drive_metadata` · `approvals` · `response_drafts` ·
`activity_log` · `ai_context`.

The config tables (`request_types`, `validation_rules`, `qa_templates`,
`folder_templates`, `response_templates`) are the foundation for the
configuration-driven rules engine — new ticket types / validations / QA
templates / folder structures / reply templates become rows, not code.

## Migrations
Add new files as `000N_description.sql` and run them in order. Keep each
migration additive and idempotent (`create ... if not exists`, `on conflict do
nothing`) so re-running is safe.

## Note on the Postgres adapter
`app/data/postgres.py` reconstructs tickets from the JSONB `snapshot` (reliable
round-trip) while also writing normalized columns + `validation_findings` for
querying. It opens a short-lived connection per call (pooler-friendly). It is
validated by construction and pending a live smoke test once `DATABASE_URL`
is provided.
