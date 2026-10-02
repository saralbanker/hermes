-- Phase 1 — Data Foundation
-- Additive DDL implementing the canonical opportunity model described in
-- architect-redesign-docs/master-redesign-plan/DATA_MODEL.md §5-§12, §16
-- (post Patch 1-4, see IMPLEMENTATION_READINESS_VERIFICATION_2026-10-01.md §13).
--
-- This migration does NOT touch the legacy `jobs`, `daily_limits`, or `responses`
-- tables. It only creates new structures alongside them. `responses_v2` and
-- `daily_limits_v2` are named with a `_v2` suffix because the old `responses`
-- table is still being written to by `src/response_watcher.py` and the old
-- `daily_limits` table is still read/written by running code until later
-- phases cut over (see DATA_MODEL.md §24 staged-migration sequence).
--
-- Safe to re-run: every statement uses IF NOT EXISTS.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- schema_migrations — bookkeeping only, not part of DATA_MODEL.md's entity
-- set. Used by scripts/migrate_phase1.py to make the data backfill idempotent.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version                     TEXT PRIMARY KEY,
    applied_at                  DATETIME NOT NULL
);

-- ---------------------------------------------------------------------------
-- opportunities  (DATA_MODEL.md §5)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id              INTEGER PRIMARY KEY,
    canonical_key                TEXT UNIQUE NOT NULL,
    identity_version              INTEGER NOT NULL,
    company_normalized            TEXT NOT NULL,
    company_display                TEXT,
    company_domain                 TEXT,
    job_title_normalized          TEXT NOT NULL,
    job_title_display               TEXT,
    location_normalized           TEXT,
    location_display                TEXT,
    employment_type                 TEXT,
    work_mode                        TEXT,
    salary_min                      INTEGER,
    salary_max                      INTEGER,
    salary_currency                 TEXT,
    salary_basis                    TEXT,
    first_seen_at                 DATETIME NOT NULL,
    first_posted_at                DATETIME,
    last_observed_at              DATETIME NOT NULL,
    last_verified_open_at         DATETIME,
    current_open_state            TEXT NOT NULL,
    age_basis                       TEXT NOT NULL,
    age_reference_at               DATETIME NOT NULL,
    age_band                        TEXT,
    hard_eligibility_state        TEXT NOT NULL,
    hard_eligibility_reason       TEXT,
    fit_state                       TEXT,
    fit_score                       REAL,
    fit_confidence                  REAL,
    fit_reasons                     TEXT,
    core_or_stretch                TEXT,
    application_state             TEXT NOT NULL
        CHECK (application_state IN (
            'OBSERVED', 'EVALUATING', 'READY', 'APPLYING',
            'AWAITING_RECONCILIATION', 'COMPLETED', 'EXPIRED', 'MANUAL_REVIEW'
        )),
    current_attempt_id            INTEGER REFERENCES application_attempts(attempt_id),
    terminal_reason                 TEXT,
    selected_resume_variant       TEXT,
    current_cover_letter_ref      TEXT,
    latest_description_hash       TEXT,
    latest_application_route      TEXT,
    created_at                      DATETIME NOT NULL,
    updated_at                      DATETIME NOT NULL
);

-- ---------------------------------------------------------------------------
-- source_observations  (DATA_MODEL.md §6)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_observations (
    observation_id               INTEGER PRIMARY KEY,
    opportunity_id                INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
    source_name                    TEXT NOT NULL,
    source_job_id                  TEXT,
    source_url                      TEXT,
    apply_url                       TEXT,
    observed_at                    DATETIME NOT NULL,
    posted_at                       DATETIME,
    open_state                      TEXT,
    company_raw                     TEXT,
    title_raw                       TEXT,
    location_raw                    TEXT,
    employment_type_raw            TEXT,
    work_mode_raw                   TEXT,
    salary_min_raw                  TEXT,
    salary_max_raw                  TEXT,
    salary_currency_raw            TEXT,
    description_hash                TEXT,
    description_ref                 TEXT,
    raw_metadata                    TEXT,
    observation_status             TEXT NOT NULL,
    failure_reason                  TEXT,
    created_at                      DATETIME NOT NULL
);

-- DATA_MODEL.md §15: "Where reliable source IDs exist: (source_name, source_job_id) UNIQUE".
-- A source without a stable ID (source_job_id NULL) is excluded, per §6.3/§15, and this
-- partial unique index also satisfies the §16 lookup index on the same column pair.
CREATE UNIQUE INDEX IF NOT EXISTS ux_source_observations_source_job
    ON source_observations(source_name, source_job_id)
    WHERE source_job_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- application_attempts  (DATA_MODEL.md §7)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS application_attempts (
    attempt_id                   INTEGER PRIMARY KEY,
    opportunity_id                INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
    channel                         TEXT NOT NULL,
    attempt_number                  INTEGER NOT NULL,
    worker_id                       TEXT,
    claimed_at                      DATETIME NOT NULL,
    lease_until                     DATETIME,
    started_at                      DATETIME,
    finished_at                     DATETIME,
    attempt_state                  TEXT NOT NULL,
    execution_phase                TEXT NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (execution_phase IN (
            'NOT_STARTED', 'EXTERNAL_WORK_STARTED', 'SUBMIT_INTENT', 'OBSERVED'
        )),
    outcome                         TEXT
        CHECK (outcome IS NULL OR outcome IN (
            'SUBMITTED', 'ALREADY_APPLIED', 'SUBMISSION_UNCONFIRMED',
            'RETRYABLE_FAILURE', 'CHANNEL_BLOCKED', 'UNSUPPORTED_CHANNEL',
            'TERMINAL_FAILURE'
        )),
    error_code                      TEXT,
    error_class                     TEXT,
    retry_eligible                  INTEGER NOT NULL DEFAULT 0,
    resolved_apply_url             TEXT,
    confirmation_url                TEXT,
    confirmation_text               TEXT,
    authenticated_session_ref      TEXT,
    evidence_json                   TEXT,
    screenshot_ref                  TEXT,
    email_evidence_ref              TEXT,
    browser_signals                 TEXT,
    network_signals                 TEXT,
    request_trace_ref               TEXT,
    notes                           TEXT,
    created_at                      DATETIME NOT NULL,
    updated_at                      DATETIME NOT NULL
);

-- ---------------------------------------------------------------------------
-- channel_health  (DATA_MODEL.md §8)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channel_health (
    channel_id                   INTEGER PRIMARY KEY,
    channel_key                    TEXT UNIQUE NOT NULL,
    scope                           TEXT NOT NULL,
    provider                        TEXT,
    status                           TEXT NOT NULL
        CHECK (status IN (
            'HEALTHY', 'DEGRADED', 'AUTH_EXPIRED', 'RATE_LIMITED',
            'FORM_SCHEMA_CHANGED', 'ACCOUNT_WALL', 'ANTIBOT_BLOCKED',
            'NETWORK_UNAVAILABLE', 'UNSUPPORTED', 'PAUSED'
        )),
    failure_streak                  INTEGER NOT NULL DEFAULT 0,
    success_count                   INTEGER NOT NULL DEFAULT 0,
    blocked_count                   INTEGER NOT NULL DEFAULT 0,
    rate_limit_count                INTEGER NOT NULL DEFAULT 0,
    last_success_at                 DATETIME,
    last_failure_at                 DATETIME,
    cooldown_until                  DATETIME,
    last_error_class                TEXT,
    last_error_code                 TEXT,
    health_reason                   TEXT,
    capability_version              TEXT,
    updated_at                      DATETIME NOT NULL
);
-- NOTE: no row is ever seeded for `linkedin` — LinkedIn is permanently
-- unsupported per ARCHITECTURE_REDESIGN_FINAL...FROZEN.md and DATA_MODEL.md §8.1.

-- ---------------------------------------------------------------------------
-- work_queue  (DATA_MODEL.md §9) — purely derived/rebuildable projection.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS work_queue (
    queue_id                     INTEGER PRIMARY KEY,
    opportunity_id                INTEGER UNIQUE NOT NULL REFERENCES opportunities(opportunity_id),
    ready_state                     TEXT NOT NULL,
    age_band                        TEXT NOT NULL,
    priority_score                  REAL,
    next_attempt_at                 DATETIME,
    lease_until                     DATETIME,
    candidate_channel               TEXT,
    queue_reason                    TEXT,
    updated_at                      DATETIME NOT NULL
);

-- ---------------------------------------------------------------------------
-- evaluation_history  (DATA_MODEL.md §10)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evaluation_history (
    evaluation_id                INTEGER PRIMARY KEY,
    opportunity_id                INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
    evaluation_type                TEXT NOT NULL,
    evaluated_at                    DATETIME NOT NULL,
    policy_version                  TEXT,
    input_hash                      TEXT,
    result                          TEXT,
    score                            REAL,
    confidence                      REAL,
    reason                          TEXT,
    model_name                      TEXT,
    model_version                   TEXT,
    metadata                        TEXT
);

-- ---------------------------------------------------------------------------
-- responses_v2  (DATA_MODEL.md §11) — new table; the old ad hoc `responses`
-- table (created by src/response_watcher.py:ensure_responses_table) keeps
-- being written to by running code until Phase 6 cuts it over.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS responses_v2 (
    message_id                   TEXT PRIMARY KEY,
    from_addr                      TEXT,
    subject                         TEXT,
    received_at                     DATETIME,
    classification                  TEXT,
    opportunity_id                  INTEGER REFERENCES opportunities(opportunity_id),
    attempt_id                      INTEGER REFERENCES application_attempts(attempt_id),
    job_url_observed                TEXT,
    notified_at                     DATETIME,
    notification_level              TEXT
        CHECK (notification_level IS NULL OR notification_level IN (
            'Ignore', 'Log', 'Telegram Notification', 'High Priority Telegram Notification'
        )),
    message_hash                    TEXT,
    correlation_reason               TEXT,
    raw_message_ref                 TEXT,
    created_at                      DATETIME NOT NULL
);

-- ---------------------------------------------------------------------------
-- daily_limits_v2  (DATA_MODEL.md §12.2) — new shape; old `daily_limits`
-- (with `linkedin_count`) stays live until a later phase cuts over.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_limits_v2 (
    date                          TEXT PRIMARY KEY,
    indeed_count                    INTEGER NOT NULL DEFAULT 0,
    other_count                     INTEGER NOT NULL DEFAULT 0,
    total_count                     INTEGER NOT NULL DEFAULT 0,
    confirmed_count                 INTEGER NOT NULL DEFAULT 0,
    attempt_count                   INTEGER NOT NULL DEFAULT 0,
    updated_at                      DATETIME NOT NULL
);

-- ---------------------------------------------------------------------------
-- Indexes — DATA_MODEL.md §16, verbatim for every table above.
-- (canonical_key, channel_key, work_queue.opportunity_id and responses_v2's
-- message_id are already covered by their UNIQUE/PRIMARY KEY constraints,
-- which SQLite backs with an implicit unique index, so no duplicate
-- single-column index is created for those.)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_opportunities_open_age ON opportunities(current_open_state, age_band);
CREATE INDEX IF NOT EXISTS idx_opportunities_eligibility_age ON opportunities(hard_eligibility_state, age_band);
CREATE INDEX IF NOT EXISTS idx_opportunities_appstate_age ON opportunities(application_state, age_band);
CREATE INDEX IF NOT EXISTS idx_opportunities_last_observed ON opportunities(last_observed_at);
CREATE INDEX IF NOT EXISTS idx_opportunities_last_verified_open ON opportunities(last_verified_open_at);
CREATE INDEX IF NOT EXISTS idx_opportunities_fit_score ON opportunities(fit_score);
CREATE INDEX IF NOT EXISTS idx_opportunities_updated_at ON opportunities(updated_at);

CREATE INDEX IF NOT EXISTS idx_source_observations_opportunity ON source_observations(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_source_observations_source_job ON source_observations(source_name, source_job_id);
CREATE INDEX IF NOT EXISTS idx_source_observations_source_observed ON source_observations(source_name, observed_at);
CREATE INDEX IF NOT EXISTS idx_source_observations_url ON source_observations(source_url);

CREATE INDEX IF NOT EXISTS idx_attempts_opportunity_number ON application_attempts(opportunity_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_attempts_opportunity_started ON application_attempts(opportunity_id, started_at);
CREATE INDEX IF NOT EXISTS idx_attempts_state_lease ON application_attempts(attempt_state, lease_until);
CREATE INDEX IF NOT EXISTS idx_attempts_channel_started ON application_attempts(channel, started_at);

CREATE INDEX IF NOT EXISTS idx_channel_health_status_cooldown ON channel_health(status, cooldown_until);

CREATE INDEX IF NOT EXISTS idx_evaluation_history_opportunity_evaluated ON evaluation_history(opportunity_id, evaluated_at);
CREATE INDEX IF NOT EXISTS idx_evaluation_history_opportunity_type_evaluated ON evaluation_history(opportunity_id, evaluation_type, evaluated_at);

CREATE INDEX IF NOT EXISTS idx_work_queue_age_next ON work_queue(age_band, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_work_queue_ready_age_priority ON work_queue(ready_state, age_band, priority_score);

CREATE INDEX IF NOT EXISTS idx_responses_v2_opportunity_received ON responses_v2(opportunity_id, received_at);
CREATE INDEX IF NOT EXISTS idx_responses_v2_classification_received ON responses_v2(classification, received_at);
