-- Commercial Bond PRA schema
-- Physical layout (locking):
--   portfolio.db              shared entities + investment index
--   investments/<ID>/master.db   one investment, fields common across nodes
--   investments/<ID>/node_<k>.db one node observation table (write locks only that file)
-- All files use WAL so readers are not blocked by a node writer.

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- ========== PORTFOLIO (portfolio.db) ==========

CREATE TABLE IF NOT EXISTS industry (
  industry_id     INTEGER PRIMARY KEY,
  naics           TEXT,
  name            TEXT NOT NULL UNIQUE,
  cycle_note      TEXT
);

CREATE TABLE IF NOT EXISTS geography (
  geo_id          INTEGER PRIMARY KEY,
  country         TEXT NOT NULL DEFAULT 'US',
  state           TEXT,
  metro           TEXT,
  name            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS principal (
  principal_id    INTEGER PRIMARY KEY,
  legal_name      TEXT NOT NULL,
  dba             TEXT,
  tax_id_last4    TEXT,
  entity_type     TEXT,
  industry_id     INTEGER REFERENCES industry(industry_id),
  hq_geo_id       INTEGER REFERENCES geography(geo_id),
  formed_date     TEXT,
  status          TEXT DEFAULT 'active',
  created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS person (
  person_id       INTEGER PRIMARY KEY,
  full_name       TEXT NOT NULL,
  role_default    TEXT,
  created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS principal_person (
  principal_id    INTEGER NOT NULL REFERENCES principal(principal_id),
  person_id       INTEGER NOT NULL REFERENCES person(person_id),
  role            TEXT NOT NULL,
  ownership_pct   REAL,
  is_indemnitor   INTEGER DEFAULT 0,
  PRIMARY KEY (principal_id, person_id, role)
);

CREATE TABLE IF NOT EXISTS license_registry (
  license_id      INTEGER PRIMARY KEY,
  principal_id    INTEGER NOT NULL REFERENCES principal(principal_id),
  license_type    TEXT NOT NULL,
  license_no      TEXT,
  jurisdiction    TEXT,
  status          TEXT,
  issued_on       TEXT,
  expires_on      TEXT,
  board           TEXT
);

CREATE TABLE IF NOT EXISTS court_case (
  case_id         INTEGER PRIMARY KEY,
  principal_id    INTEGER REFERENCES principal(principal_id),
  person_id       INTEGER REFERENCES person(person_id),
  court           TEXT,
  docket          TEXT,
  caption         TEXT,
  filed_on        TEXT,
  status          TEXT,
  amount          REAL,
  nature          TEXT
);

CREATE TABLE IF NOT EXISTS public_lien (
  lien_id         INTEGER PRIMARY KEY,
  principal_id    INTEGER REFERENCES principal(principal_id),
  person_id       INTEGER REFERENCES person(person_id),
  lien_type       TEXT NOT NULL, -- tax, judgment, UCC
  jurisdiction    TEXT,
  file_no         TEXT,
  filed_on        TEXT,
  amount          REAL,
  status          TEXT,
  secured_party   TEXT
);

CREATE TABLE IF NOT EXISTS business_credit_snapshot (
  snap_id         INTEGER PRIMARY KEY,
  principal_id    INTEGER NOT NULL REFERENCES principal(principal_id),
  as_of_date      TEXT NOT NULL,
  bureau          TEXT NOT NULL,
  score           REAL,
  paydex          REAL,
  notes           TEXT,
  UNIQUE (principal_id, as_of_date, bureau)
);

CREATE TABLE IF NOT EXISTS person_credit_snapshot (
  snap_id         INTEGER PRIMARY KEY,
  person_id       INTEGER NOT NULL REFERENCES person(person_id),
  as_of_date      TEXT NOT NULL,
  bureau          TEXT NOT NULL,
  score           INTEGER,
  notes           TEXT,
  UNIQUE (person_id, as_of_date, bureau)
);

CREATE TABLE IF NOT EXISTS macro_observation (
  macro_id        INTEGER PRIMARY KEY,
  as_of_date      TEXT NOT NULL,
  geo_id          INTEGER REFERENCES geography(geo_id),
  industry_id     INTEGER REFERENCES industry(industry_id),
  series          TEXT NOT NULL, -- prime_rate, unemployment, unrest_index, political_risk
  value           REAL,
  unit            TEXT,
  source          TEXT,
  note            TEXT
);

CREATE TABLE IF NOT EXISTS investment_index (
  investment_id   TEXT PRIMARY KEY,
  principal_id    INTEGER NOT NULL REFERENCES principal(principal_id),
  bond_number     TEXT,
  bond_class      TEXT,
  obligee         TEXT,
  penal_sum       REAL,
  issue_date      TEXT,
  status          TEXT DEFAULT 'open',
  master_db_path  TEXT NOT NULL,
  created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS investment_geo (
  investment_id   TEXT NOT NULL REFERENCES investment_index(investment_id),
  geo_id          INTEGER NOT NULL REFERENCES geography(geo_id),
  role            TEXT DEFAULT 'operating',
  PRIMARY KEY (investment_id, geo_id, role)
);

-- ========== INVESTMENT MASTER (investments/<ID>/master.db) ==========

CREATE TABLE IF NOT EXISTS investment (
  investment_id         TEXT PRIMARY KEY,
  principal_id          INTEGER NOT NULL,
  bond_number           TEXT,
  bond_class            TEXT,
  bond_form             TEXT,
  obligee               TEXT,
  penal_sum             REAL,
  issue_date            TEXT,
  expiration_date       TEXT,
  producer              TEXT,
  underwriter           TEXT,
  monitoring_cadence    TEXT,
  last_full_review      TEXT,
  residual_agg_score    REAL,
  status                TEXT DEFAULT 'open',
  notes                 TEXT
);

-- Fields reused by many nodes (package date, statement date, assessor of record)
CREATE TABLE IF NOT EXISTS common_surveillance (
  investment_id         TEXT PRIMARY KEY,
  package_as_of         TEXT,
  financials_as_of      TEXT,
  statements_quality    TEXT,
  assigned_assessor     TEXT,
  next_review_due       TEXT,
  overall_band          TEXT,
  updated_at            TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS node_scorecard (
  node_key              TEXT PRIMARY KEY,
  residual_score        INTEGER CHECK (residual_score BETWEEN 1 AND 10),
  band                  TEXT,
  last_obs_id           TEXT,
  last_as_of            TEXT,
  last_updated          TEXT
);

-- ========== NODE OBSERVATION TEMPLATE (each node_<key>.db) ==========
-- Concrete tables are created per node with extra columns; base columns:

-- CREATE TABLE node_obs (
--   obs_id           TEXT PRIMARY KEY,
--   investment_id    TEXT NOT NULL,
--   as_of_date       TEXT NOT NULL,
--   residual_score   INTEGER NOT NULL CHECK (residual_score BETWEEN 1 AND 10),
--   band             TEXT,
--   assessor         TEXT,
--   material_change  INTEGER DEFAULT 0,
--   source_1         TEXT,
--   source_2         TEXT,
--   source_3         TEXT,
--   notes            TEXT,
--   created_at       TEXT DEFAULT (datetime('now'))
-- );
