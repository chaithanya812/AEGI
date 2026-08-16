-- AI Reliability Lab — audit schema
-- No RLS. All access is server-side via the secret key, same posture as CANVAS.
-- The browser never talks to Supabase directly; it talks to FastAPI, which holds the secret.

create extension if not exists pgcrypto;

-- One row per output checked (one tile in the UI).
create table if not exists runs (
  trace_id        text primary key,
  created_at      timestamptz not null default now(),
  request_id      text not null,
  prompt          text,                    -- the question asked, when the lab generated the output
  output_text     text not null,           -- the text that was verified
  output_sha256   text not null,           -- what the certificate binds to
  mode            text not null,           -- 'generate' | 'verify_given'
  model_id        text,
  pipeline_version text not null,
  layers_enabled  jsonb not null,          -- which validators were switched on (the rig)
  band            text not null,           -- VERIFIED | QUALIFIED | UNRELIABLE
  score           int not null,            -- subordinate to the ledger, kept for display
  ledger          jsonb not null,          -- {supported, partial, unsupported, contradicted, unknown, opinion}
  decision        text not null,           -- ALLOW | ALLOW_WITH_WARNING | REVIEW | BLOCK | REFUSE
  risk            text not null,           -- LOW | MEDIUM | HIGH | CRITICAL
  expressed_confidence text,               -- HIGH | MEDIUM | LOW  (what the prose claimed)
  supported_confidence text,               -- HIGH | MEDIUM | LOW  (what evidence justified)
  false_certainty boolean not null default false,
  safe_response   text,                    -- MP-16 output when blocked
  latency_ms      int,
  token_usage     jsonb,
  degraded        boolean not null default false,  -- true when a canned/offline path was used
  error           text
);

create index if not exists runs_created_at_idx on runs (created_at desc);
create index if not exists runs_band_idx on runs (band);

-- One row per extracted claim (MP-04/05 output + MP-09..12 verdicts).
create table if not exists claims (
  id            uuid primary key default gen_random_uuid(),
  trace_id      text not null references runs (trace_id) on delete cascade,
  claim_index   int not null,
  text          text not null,
  source_span   jsonb,                     -- {start, end} into output_text; proves it wasn't invented
  claim_type    text not null,             -- FACT | NUMERIC | TEMPORAL | ENTITY | OPINION | PREDICTION | ...
  checkable     boolean not null,          -- false for opinion/hedged/unverifiable — never scored as wrong
  hedged        boolean not null default false,
  status        text not null,             -- SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED | UNKNOWN
  decided_by    text not null,             -- 'deterministic' | 'grounded' | 'judge'
  reasoning     text,
  evidence      jsonb,                     -- [{doc_id, section, page, quote, authority, recency, score}]
  checks        jsonb,                     -- per-validator results: temporal, numeric, citation, contradiction
  confidence    numeric,
  unique (trace_id, claim_index)
);

create index if not exists claims_trace_idx on claims (trace_id);

-- MP-24 trace engine. Append-only. Every pipeline stage emits one row.
create table if not exists events (
  id          bigserial primary key,
  trace_id    text not null,
  seq         int not null,
  at          timestamptz not null default now(),
  stage       text not null,               -- e.g. 'claims.extract'
  module      text,                        -- e.g. 'MP-04'
  level       text not null default 'info',
  message     text not null,
  data        jsonb,
  duration_ms int
);

create index if not exists events_trace_seq_idx on events (trace_id, seq);

-- Signed verdict certificates. Self-contained: payload + signature verify without this table,
-- which is why the demo survives a serverless cold start with no disk.
create table if not exists certificates (
  trace_id     text primary key references runs (trace_id) on delete cascade,
  issued_at    timestamptz not null default now(),
  algorithm    text not null default 'ed25519',
  key_id       text not null,              -- ed25519:<first 16 hex of pubkey>
  public_key   text not null,              -- base64url raw 32-byte pubkey, embedded for offline verify
  payload      jsonb not null,             -- exactly what was signed, canonical JSON
  payload_sha256 text not null,
  signature    text not null               -- base64url raw 64-byte Ed25519 signature
);

create index if not exists certificates_issued_at_idx on certificates (issued_at desc);
