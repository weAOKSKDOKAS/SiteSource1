-- SiteSource proprietary database — schema (v1)
--
-- Stores the FUSED subcontractor record. The public-signal record shape is kept
-- lossless (name_en, name_zh, registers, dated/sourced flags) so a real Hong Kong
-- public-records scrape from AI Research drops into the same tables unchanged.
-- closeout_embeddings holds one baked vector per closeout-text chunk so the
-- runtime needs no embedding model and no network.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS firms;
DROP TABLE IF EXISTS public_flags;
DROP TABLE IF EXISTS project_closeouts;
DROP TABLE IF EXISTS award_history;
DROP TABLE IF EXISTS trade_pricing;
DROP TABLE IF EXISTS closeout_embeddings;
DROP TABLE IF EXISTS contacts;
DROP TABLE IF EXISTS staged_firms;
DROP TABLE IF EXISTS staged_flags;
DROP TABLE IF EXISTS meta;
-- Benchmark estimator (Phase B1) — dropped child-first so the FKs unwind cleanly.
DROP TABLE IF EXISTS rubric_items;
DROP TABLE IF EXISTS project_eos;
DROP TABLE IF EXISTS variance_records;
DROP TABLE IF EXISTS actual_items;
DROP TABLE IF EXISTS tender_items;
DROP TABLE IF EXISTS reason_codes;
DROP TABLE IF EXISTS projects;
-- Unified engine (Phase 1+).
DROP TABLE IF EXISTS package_routes;

-- One row per firm — the fused identity (public record + private closeout archive).
CREATE TABLE firms (
    firm_id          TEXT PRIMARY KEY,
    name_en          TEXT NOT NULL,
    name_zh          TEXT,
    registered_grade TEXT,
    value_band       TEXT,
    br_number        TEXT,   -- Business Registration number, when known (entity resolution for partner ingest)
    registers        TEXT,   -- JSON array of registration schemes (lossless for the scrape)
    trades           TEXT,   -- JSON array of canonical taxonomy keys
    closeout_summary TEXT,
    provenance       TEXT NOT NULL DEFAULT 'illustrative'  -- 'public_register' (real scrape) | 'illustrative' (demo stub) | 'partner_archive' (closeout ingest)
);

-- Public-record signals (winding-up, safety prosecutions, debarment, adjudication,
-- distress filings, …). No severity here — severity is adjudicated by the rules engine.
CREATE TABLE public_flags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id     TEXT NOT NULL REFERENCES firms(firm_id),
    signal_type TEXT NOT NULL,   -- grade|award_history|safety_prosecution|winding_up|debarment|adjudication|distress_filing
    label       TEXT NOT NULL,
    date        TEXT,
    source      TEXT,            -- e.g. "Companies Registry", "Labour Department"
    reference   TEXT             -- a citable locator
);

-- Per-project closeouts from the private End-of-Site (EOS) archive.
CREATE TABLE project_closeouts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id   TEXT NOT NULL REFERENCES firms(firm_id),
    project   TEXT,
    client    TEXT,
    year      INTEGER,
    delayed   INTEGER NOT NULL DEFAULT 0,  -- 1 = delayed-closeout note (a warning signal)
    note      TEXT,
    source    TEXT,
    reference TEXT
);

-- Public award history.
CREATE TABLE award_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id   TEXT NOT NULL REFERENCES firms(firm_id),
    project   TEXT,
    client    TEXT,
    year      INTEGER,
    source    TEXT
);

-- Historical rate / awarded-package samples per trade (for the recommendation band).
CREATE TABLE trade_pricing (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    trade     TEXT NOT NULL,
    value     REAL NOT NULL,    -- an awarded subcontract value (HKD) on a past project
    project   TEXT,
    year      INTEGER,
    source    TEXT,
    reference TEXT
);

-- One baked embedding per closeout-text chunk. vector is a JSON array of floats.
CREATE TABLE closeout_embeddings (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id  TEXT NOT NULL REFERENCES firms(firm_id),
    chunk_id INTEGER NOT NULL,
    text     TEXT NOT NULL,
    vector   TEXT NOT NULL      -- JSON array of floats (baked at seed time)
);

-- Subcontractor address book — where a trade's RFQ email is sent (Phase A). Keyed
-- by (firm_id, trade): a firm bidding two trades can carry a different desk for each.
CREATE TABLE contacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id      TEXT NOT NULL REFERENCES firms(firm_id),
    trade        TEXT NOT NULL,
    contact_name TEXT,
    email        TEXT NOT NULL,
    phone        TEXT,
    note         TEXT,
    UNIQUE (firm_id, trade)
);

-- Refresh staging (Phase C) — new public records/flags land here first and only
-- reach the live firms/public_flags tables after a human confirms them. A refresh
-- never mutates curated data directly; it stages, a human reviews, then it applies.
CREATE TABLE staged_firms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    TEXT NOT NULL,
    firm_id     TEXT NOT NULL,
    payload     TEXT NOT NULL,   -- JSON of the normalized firm record
    provenance  TEXT NOT NULL DEFAULT 'public_register',
    is_new_firm INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | applied | rejected
    staged_at   TEXT NOT NULL,
    applied_at  TEXT,
    rejected_at TEXT
);

CREATE TABLE staged_flags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    TEXT NOT NULL,
    firm_id     TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    label       TEXT NOT NULL,
    date        TEXT,
    source      TEXT,
    reference   TEXT,
    fingerprint TEXT NOT NULL,   -- stable hash of the flag, for logical dedupe
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | applied | rejected
    staged_at   TEXT NOT NULL,
    applied_at  TEXT,
    rejected_at TEXT
);

-- Build metadata: which embedder baked the vectors, their dimension, seed version.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ===========================================================================
-- Benchmark estimator (Phase B1 — the variance spine).
--
-- For each completed project: the priced tender (tender_items) vs the actual
-- outturn (actual_items), item-matched behind a human confirm gate into
-- variance_records. reason_codes is a fixed ten-code vocabulary seeded in every
-- profile; rubric_items (the B2 estimator's evidence-linked guidance) ships EMPTY
-- because an entry cannot exist without real evidence.
--
-- projects.provenance ('demo' | 'live') separates the fictional pitch scenario
-- from real data so demo rows never count in /benchmark/summary. Cost data is
-- local SQLite only; see docs/PRODUCT_ARCHITECTURE_benchmark_estimator.md.
-- ===========================================================================

-- One row per completed (or in-progress) project we benchmark.
CREATE TABLE projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    trade        TEXT,               -- canonical taxonomy key (e.g. ground_investigation)
    client       TEXT,
    contract_ref TEXT,               -- HK contract number, e.g. GE/2026/14
    status       TEXT NOT NULL DEFAULT 'open',      -- open | closed
    provenance   TEXT NOT NULL DEFAULT 'live',      -- 'demo' (fictional) | 'live' (real). The summary discriminator.
    source       TEXT,               -- tender-upload | pipeline-link | manual | demo
    notes        TEXT,
    created_at   TEXT NOT NULL,
    closed_at    TEXT
);

-- The priced tender snapshot. item_ref is the primary cross-project match key;
-- rates are kept (a priced tender), quantities stay optional (rate-only SoRs).
CREATE TABLE tender_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    item_ref    TEXT NOT NULL,
    description TEXT,
    unit        TEXT,
    qty         REAL,               -- optional
    rate        REAL,               -- the priced tender rate
    amount      REAL,               -- optional (extended where computable)
    section     TEXT,
    source      TEXT,               -- tender-pdf | tender-xlsx | pipeline-link  (provenance)
    source_doc  TEXT,               -- original filename                          (provenance)
    created_at  TEXT NOT NULL
);

-- The actual outturn (final account). granularity records whether the sheet was
-- item-by-item, section-totals-only, or a single project total.
CREATE TABLE actual_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    item_ref    TEXT,               -- optional for section/project granularity
    description TEXT,
    unit        TEXT,
    qty         REAL,
    rate        REAL,
    amount      REAL,
    section     TEXT,
    granularity TEXT NOT NULL DEFAULT 'item',    -- item | section | project
    source      TEXT,               -- actuals-xlsx | actuals-pdf   (provenance)
    source_doc  TEXT,               -- original filename            (provenance)
    created_at  TEXT NOT NULL
);

-- The controlled ten-code reason vocabulary (seeded in every profile).
CREATE TABLE reason_codes (
    code        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT,
    category    TEXT               -- ground | time | quantity | rate | scope | commercial
);

-- The confirmed variance. WRITTEN ONLY by the confirm gate (Layer 4). A NULL
-- tender_item_id is an arrived-unpriced line; a NULL actual_item_id is an
-- omission-at-tender line. reason_code stays NULL until a human tags it.
CREATE TABLE variance_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES projects(id),
    tender_item_id    INTEGER REFERENCES tender_items(id),
    actual_item_id    INTEGER REFERENCES actual_items(id),
    item_ref          TEXT,
    granularity       TEXT NOT NULL DEFAULT 'item',   -- item | section | project
    match_tier        INTEGER,          -- 1 exact | 2 embedding | 3 unmatched
    tender_rate       REAL,
    actual_rate       REAL,
    tender_qty        REAL,
    actual_qty        REAL,
    tender_amount     REAL,
    actual_amount     REAL,
    rate_delta        REAL,             -- actual_rate - tender_rate (both present)
    rate_delta_pct    REAL,
    amount_delta      REAL,             -- only where both amounts computable
    amount_delta_qty  REAL,             -- qty-driven component
    amount_delta_rate REAL,             -- rate-driven component
    reason_code       TEXT REFERENCES reason_codes(code),
    reason_note       TEXT,
    tagged_by         TEXT,             -- provenance: who set the reason
    confirmed_at      TEXT,             -- provenance: when the match was confirmed
    source            TEXT,             -- 'demo' | 'confirm-gate'
    created_at        TEXT NOT NULL
);

-- Per-project End-of-Site (EOS) narrative attached to a benchmark project (Phase 2).
-- One report per project: the field account of WHY prices moved between tender and
-- outturn. Narrative-only (a company already keeps this) — it supplies reasons, never
-- numbers, so the cost-data posture is untouched. Images are noted (has_images), not
-- parsed for figures. provenance ('demo' | 'live') keeps the fictional pitch narrative
-- out of any live surface. The reason still comes from a human confirm (variance_records).
CREATE TABLE project_eos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    narrative   TEXT,               -- the field account (narrative sentences joined)
    summary     TEXT,               -- a short headline of the account
    source_doc  TEXT,               -- original filename                (provenance)
    has_images  INTEGER NOT NULL DEFAULT 0,   -- 1 = the report carried images (noted, not parsed)
    provenance  TEXT NOT NULL DEFAULT 'live', -- 'demo' (fictional) | 'live' (real)
    created_at  TEXT NOT NULL
);

-- The B2 estimator's evidence-linked guidance. Ships EMPTY (needs real evidence).
CREATE TABLE rubric_items (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    trade                TEXT,
    item_ref             TEXT,
    guidance             TEXT,
    evidence_variance_id INTEGER REFERENCES variance_records(id),
    source               TEXT,
    created_at           TEXT NOT NULL
);

-- ===========================================================================
-- Routing gate (Phase 1) — after ingest splits a tender into packages, the AI
-- recommends self-perform vs sublet per package (recommended_route + rationale,
-- with the deterministic signals it used); a human confirms (chosen_route,
-- decided_by, decided_at — the Layer-4 gate and the only writer of chosen_route).
-- Scoped to an analysis run (run_ref). Advisory until confirmed.
-- ===========================================================================
CREATE TABLE package_routes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref           TEXT NOT NULL,       -- stable id for the tender/analysis run
    package_key       TEXT NOT NULL,       -- the package identifier (the trade, today)
    trade             TEXT,
    scope_summary     TEXT,
    recommended_route TEXT,                -- self_perform | sublet (advisory)
    rationale         TEXT,
    signals           TEXT,                -- JSON: the deterministic inputs used
    chosen_route      TEXT,                -- self_perform | sublet (human decision; null until decided)
    decided_by        TEXT,                -- provenance: who decided
    decided_at        TEXT,                -- provenance: when
    source            TEXT,                -- route-suggest | fallback | demo
    created_at        TEXT NOT NULL
);

CREATE INDEX idx_public_flags_firm  ON public_flags(firm_id);
CREATE INDEX idx_closeouts_firm     ON project_closeouts(firm_id);
CREATE INDEX idx_awards_firm        ON award_history(firm_id);
CREATE INDEX idx_pricing_trade      ON trade_pricing(trade);
CREATE INDEX idx_embeddings_firm    ON closeout_embeddings(firm_id);
CREATE INDEX idx_contacts_firm      ON contacts(firm_id);
CREATE INDEX idx_staged_firms_status ON staged_firms(status);
CREATE INDEX idx_staged_flags_status ON staged_flags(status);
CREATE INDEX idx_staged_flags_fp     ON staged_flags(fingerprint);
-- Benchmark estimator indexes (Phase B1).
CREATE INDEX idx_tender_items_project ON tender_items(project_id);
CREATE INDEX idx_tender_items_ref     ON tender_items(item_ref);
CREATE INDEX idx_actual_items_project ON actual_items(project_id);
CREATE INDEX idx_actual_items_ref     ON actual_items(item_ref);
CREATE INDEX idx_variance_project     ON variance_records(project_id);
CREATE INDEX idx_variance_reason      ON variance_records(reason_code);
CREATE INDEX idx_project_eos_project  ON project_eos(project_id);
CREATE INDEX idx_projects_provenance  ON projects(provenance);
CREATE INDEX idx_package_routes_run   ON package_routes(run_ref);
