-- ============================================================================
-- OrchestrAI — initial schema (v1)
-- Target: Supabase / PostgreSQL. Normalized for long-term growth, not just the
-- current approval queue. Apply in the Supabase SQL editor or via `psql`.
--
-- Conventions: uuid PKs (gen_random_uuid), timestamptz everywhere, updated_at
-- maintained by trigger, jsonb for open-ended payloads, FKs cascade from the
-- owning ticket. Lookup/config tables are seeded so the rules engine can be
-- driven by data.
-- ============================================================================

create extension if not exists "pgcrypto";      -- gen_random_uuid()

-- ---- updated_at trigger ----------------------------------------------------
create or replace function set_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end;
$$ language plpgsql;

-- ---- Intake channels (Zendesk, Slack, Email, Google Sheets, Asana …) -------
create table if not exists channels (
    id           uuid primary key default gen_random_uuid(),
    key          text unique not null,          -- 'zendesk','slack','email','gsheets','asana'
    label        text not null,
    active       boolean not null default true,
    config       jsonb not null default '{}',   -- per-channel settings (no secrets)
    created_at   timestamptz not null default now()
);

-- ---- Request types (config-driven; the rules engine reads these) -----------
create table if not exists request_types (
    id           uuid primary key default gen_random_uuid(),
    key          text unique not null,          -- 'brand_addition','talent_addition',…
    label        text not null,
    matcher      jsonb not null default '{}',   -- keyword/regex rules → classification
    active       boolean not null default true,
    sort_order   int not null default 100,
    created_at   timestamptz not null default now()
);

-- ---- Reusable config: validation rules, QA templates, folder + reply templates
create table if not exists validation_rules (
    id            uuid primary key default gen_random_uuid(),
    request_type  text,                          -- null = applies to all
    check_key     text not null,                 -- maps to a validator function
    severity      text not null default 'warning',
    params        jsonb not null default '{}',
    message       text not null default '',
    active        boolean not null default true
);
create table if not exists qa_templates (
    id            uuid primary key default gen_random_uuid(),
    request_type  text,
    items         jsonb not null default '[]',   -- [{label, required}]
    active        boolean not null default true
);
create table if not exists folder_templates (
    id            uuid primary key default gen_random_uuid(),
    request_type  text,
    subfolders    jsonb not null default '[]',   -- ['Attachments','Research',…]
    active        boolean not null default true
);
create table if not exists response_templates (
    id            uuid primary key default gen_random_uuid(),
    request_type  text,
    kind          text not null default 'customer_reply',  -- customer_reply|clarification|internal
    body          text not null,
    active        boolean not null default true
);

-- ---- Tickets (core) --------------------------------------------------------
create table if not exists tickets (
    id                uuid primary key default gen_random_uuid(),
    channel_key       text references channels(key),
    external_ref      text,                      -- Zendesk ticket #, Asana gid, email id…
    ticket_number     text,
    client            text not null default 'unknown',
    subject           text not null default '',
    request_type      text not null default 'Other',
    request_confidence text not null default 'low',
    priority          text not null default 'Normal',
    status            text not null default 'pending_review',
    confidence        text not null default 'low',
    raw_text          text not null default '',
    due_date          date,
    -- Denormalized snapshot of the full domain object for reliable
    -- reconstruction; the normalized columns/child tables above are for
    -- querying and reporting.
    snapshot          jsonb not null default '{}',
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);
create index if not exists idx_tickets_status on tickets(status);
create index if not exists idx_tickets_created on tickets(created_at desc);
create index if not exists idx_tickets_channel on tickets(channel_key);
create trigger trg_tickets_updated before update on tickets
    for each row execute function set_updated_at();

-- ---- Ticket entities (brands, talent, urls, platforms, handles) — normalized
create table if not exists ticket_entities (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid not null references tickets(id) on delete cascade,
    kind         text not null,                 -- 'brand','talent','url','platform','handle'
    value        text not null,
    meta         jsonb not null default '{}',
    created_at   timestamptz not null default now()
);
create index if not exists idx_entities_ticket on ticket_entities(ticket_id);
create index if not exists idx_entities_kind on ticket_entities(kind);

-- ---- Validation findings ---------------------------------------------------
create table if not exists validation_findings (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid not null references tickets(id) on delete cascade,
    check_key    text not null,
    severity     text not null,                 -- ok|info|warning|blocker
    message      text not null,
    detail       text not null default '',
    created_at   timestamptz not null default now()
);
create index if not exists idx_findings_ticket on validation_findings(ticket_id);

-- ---- QA reports + items ----------------------------------------------------
create table if not exists qa_reports (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid not null references tickets(id) on delete cascade,
    confidence   text not null default 'low',
    summary      jsonb not null default '{}',
    created_at   timestamptz not null default now()
);
create table if not exists qa_items (
    id           uuid primary key default gen_random_uuid(),
    qa_report_id uuid not null references qa_reports(id) on delete cascade,
    label        text not null,
    done         boolean not null default false,
    note         text not null default ''
);

-- ---- Research outputs (verified sources only; never fabricated) ------------
create table if not exists research_outputs (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid not null references tickets(id) on delete cascade,
    source       text not null,                 -- 'wikidata','imdb','spotify',…
    query        text not null default '',
    result       jsonb not null default '{}',
    verified     boolean not null default false,
    created_at   timestamptz not null default now()
);
create index if not exists idx_research_ticket on research_outputs(ticket_id);

-- ---- Drive metadata --------------------------------------------------------
create table if not exists drive_metadata (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid not null references tickets(id) on delete cascade,
    folder_id    text,
    folder_url   text,
    path         text,
    subfolders   jsonb not null default '[]',
    created_at   timestamptz not null default now()
);

-- ---- Approvals (human decision audit trail) --------------------------------
create table if not exists approvals (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid not null references tickets(id) on delete cascade,
    decision     text not null,                 -- approved|rejected|completed
    approver     text not null default '',
    note         text not null default '',
    decided_at   timestamptz not null default now()
);
create index if not exists idx_approvals_ticket on approvals(ticket_id);

-- ---- Drafted responses -----------------------------------------------------
create table if not exists response_drafts (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid not null references tickets(id) on delete cascade,
    kind         text not null default 'customer_reply',
    body         text not null default '',
    internal_notes text not null default '',
    sent         boolean not null default false,   -- always false until a human sends
    created_at   timestamptz not null default now()
);

-- ---- Activity log (searchable) ---------------------------------------------
create table if not exists activity_log (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid references tickets(id) on delete set null,
    kind         text not null,                 -- 'ticket_received','folder_created',…
    actor        text not null default 'system',
    title        text not null,
    detail       jsonb not null default '{}',
    at           timestamptz not null default now()
);
create index if not exists idx_activity_at on activity_log(at desc);
create index if not exists idx_activity_kind on activity_log(kind);
create index if not exists idx_activity_ticket on activity_log(ticket_id);

-- ---- AI context (future assistant memory / retrieval) ----------------------
-- Kept generic now; add a pgvector `embedding vector(1536)` column when the
-- assistant needs semantic retrieval (enable the `vector` extension first).
create table if not exists ai_context (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid references tickets(id) on delete cascade,
    scope        text not null default 'ticket',   -- 'ticket'|'global'
    key          text not null,
    content      jsonb not null default '{}',
    created_at   timestamptz not null default now()
);
create index if not exists idx_ai_context_ticket on ai_context(ticket_id);

-- ---- Seed: intake channels + baseline request types ------------------------
insert into channels (key, label) values
    ('zendesk','Zendesk'), ('slack','Slack'), ('email','Email'),
    ('gsheets','Google Sheets'), ('asana','Asana'), ('manual','Manual intake')
on conflict (key) do nothing;

insert into request_types (key, label, sort_order) values
    ('brand_addition','Brand Addition',10),
    ('brand_update','Brand Update',20),
    ('brand_set_upload','Brand Set Upload',30),
    ('talent_addition','Talent Addition',40),
    ('handle_update','Handle Update',50),
    ('social_account','Social Account Request',60),
    ('youtube_channel','YouTube Channel',70),
    ('spotify','Spotify',80),
    ('podcast','Podcast',90),
    ('video_game','Video Game',100),
    ('metadata_update','Metadata Update',110),
    ('film','Film',120),
    ('tv','TV',130),
    ('bug_report','Bug Report',140),
    ('question','Question',150),
    ('other','Other',999)
on conflict (key) do nothing;
