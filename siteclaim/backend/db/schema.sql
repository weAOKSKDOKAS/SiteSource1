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
DROP TABLE IF EXISTS meta;

-- One row per firm — the fused identity (public record + private closeout archive).
CREATE TABLE firms (
    firm_id           TEXT PRIMARY KEY,
    name_en           TEXT NOT NULL,
    name_zh           TEXT,
    registered_grade  TEXT,
    value_band        TEXT,
    registers         TEXT,   -- JSON array of registration schemes (lossless for the scrape)
    trades            TEXT,   -- JSON array of canonical taxonomy keys (discovery/shortlist)
    registered_trades TEXT,   -- JSON array of {code, group, specialty} from the CIC register
    closeout_summary  TEXT,
    description       TEXT,   -- short factual blurb generated from register data
    enquiry_email     TEXT,   -- the real Office E-mail (Dispatch reads this to draft enquiries)
    br_no             TEXT,   -- Business Registration No.
    address           TEXT,
    phone             TEXT,
    fax               TEXT,
    reg_date          TEXT,   -- Date of Registration
    expiry_date       TEXT,   -- Expiry Date of Current Registration
    profile           TEXT,   -- JSON curated profile (overview, services, notable_projects, ...) for known firms
    provenance        TEXT NOT NULL DEFAULT 'illustrative'  -- 'public_register' (real) | 'illustrative' (demo)
);
CREATE INDEX idx_firms_provenance ON firms(provenance);
CREATE INDEX idx_firms_name       ON firms(name_en);

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

-- Build metadata: which embedder baked the vectors, their dimension, seed version.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX idx_public_flags_firm  ON public_flags(firm_id);
CREATE INDEX idx_closeouts_firm     ON project_closeouts(firm_id);
CREATE INDEX idx_awards_firm        ON award_history(firm_id);
CREATE INDEX idx_pricing_trade      ON trade_pricing(trade);
CREATE INDEX idx_embeddings_firm    ON closeout_embeddings(firm_id);
