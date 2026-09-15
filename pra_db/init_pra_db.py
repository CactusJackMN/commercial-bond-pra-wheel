#!/usr/bin/env python3
"""Create the split-file PRA database.

portfolio.db              shared / multi-investment fields
investments/<ID>/master.db   investment + common surveillance + scorecard
investments/<ID>/node_*.db   one SQLite file per PRA node (WAL)

A writer opens only the node file it is updating, so other nodes and the
portfolio catalog are not write-locked.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

# Build on local disk then copy into artifacts (overlay FS is slow for many small DBs).
ROOT = Path(__file__).resolve().parent
BUILD = Path("/tmp/pra_db_build")
PORTFOLIO = BUILD / "portfolio.db"
INV_ROOT = BUILD / "investments"
PUBLISH = ROOT

NODES = [
    # key, title, group, scope, extra columns (name, type)
    ("claims", "Bond claims history", "Character", "Specific", [
        ("claim_count", "INTEGER"), ("open_reserves", "REAL"),
        ("paid_losses", "REAL"), ("pattern_note", "TEXT")]),
    ("suits", "Lawsuits, judgments, liens", "Character", "General", [
        ("open_case_count", "INTEGER"), ("total_exposed", "REAL"),
        ("worst_status", "TEXT"), ("docket_refs", "TEXT")]),
    ("taxucc", "Tax liens and UCC filings", "Character", "General", [
        ("tax_lien_count", "INTEGER"), ("ucc_count", "INTEGER"),
        ("priority_secured_party", "TEXT"), ("aggregate_amount", "REAL")]),
    ("bk", "Bankruptcy and insolvency", "Character", "General", [
        ("chapter", "TEXT"), ("filed_on", "TEXT"),
        ("case_status", "TEXT"), ("docket", "TEXT")]),
    ("trade", "Vendor and trade payment history", "Character", "General", [
        ("paydex", "REAL"), ("avg_days_beyond_term", "REAL"),
        ("trade_line_count", "INTEGER"), ("past_due_flag", "INTEGER")]),
    ("integrity", "Management integrity / ownership change", "Character", "General", [
        ("ownership_change", "INTEGER"), ("key_person_exit", "INTEGER"),
        ("kyc_flag", "TEXT"), ("change_date", "TEXT")]),
    ("license", "Regulatory actions and license status", "Character", "Specific", [
        ("license_status", "TEXT"), ("action_type", "TEXT"),
        ("board", "TEXT"), ("action_date", "TEXT")]),
    ("media", "Reputation and adverse media", "Character", "General", [
        ("hit_count_90d", "INTEGER"), ("severity", "TEXT"),
        ("headline", "TEXT"), ("outlet", "TEXT")]),
    ("perform", "Ability to perform the obligation", "Capacity", "Specific", [
        ("still_operating", "INTEGER"), ("line_of_business", "TEXT"),
        ("site_check_date", "TEXT"), ("impediment", "TEXT")]),
    ("experience", "Experience in the bonded line", "Capacity", "Specific", [
        ("years_in_line", "REAL"), ("prior_bond_count", "INTEGER"),
        ("track_record", "TEXT")]),
    ("ops", "Operational stability", "Capacity", "General", [
        ("staffing_note", "TEXT"), ("location_count", "INTEGER"),
        ("systems_note", "TEXT"), ("stability_flag", "TEXT")]),
    ("continuity", "Continuity of management / ownership", "Capacity", "General", [
        ("succession_plan", "INTEGER"), ("key_man_insurance", "INTEGER"),
        ("control_change", "INTEGER")]),
    ("compliance", "Statutory / permit / contract compliance", "Capacity", "Specific", [
        ("obligation_ref", "TEXT"), ("compliance_status", "TEXT"),
        ("last_inspection", "TEXT"), ("finding", "TEXT")]),
    ("stmts", "Financial statements", "Capital", "General", [
        ("stmt_date", "TEXT"), ("stmt_type", "TEXT"),
        ("prepared_by", "TEXT"), ("quality", "TEXT")]),
    ("liquidity", "Working capital and liquidity", "Capital", "General", [
        ("current_ratio", "REAL"), ("working_capital", "REAL"),
        ("cash", "REAL"), ("revolver_availability", "REAL")]),
    ("profit", "Profitability and cash-flow trends", "Capital", "General", [
        ("net_income", "REAL"), ("ebitda", "REAL"),
        ("cfo", "REAL"), ("trend", "TEXT")]),
    ("leverage", "Leverage and debt service", "Capital", "General", [
        ("debt_to_equity", "REAL"), ("dscr", "REAL"),
        ("total_debt", "REAL"), ("near_maturity", "INTEGER")]),
    ("bizcredit", "Business credit scores", "Capital", "General", [
        ("bureau", "TEXT"), ("score", "REAL"),
        ("prior_score", "REAL"), ("direction", "TEXT")]),
    ("perscredit", "Personal credit of owners / indemnitors", "Capital", "General", [
        ("person_name", "TEXT"), ("bureau", "TEXT"),
        ("score", "INTEGER"), ("direction", "TEXT")]),
    ("taxret", "Tax returns and tax-compliance status", "Capital", "General", [
        ("year", "INTEGER"), ("filed", "INTEGER"),
        ("tax_due", "REAL"), ("book_tax_gap_note", "TEXT")]),
    ("distress", "Public-record financial distress signals", "Capital", "General", [
        ("signal_type", "TEXT"), ("alert_source", "TEXT"),
        ("severity", "TEXT")]),
    ("collateral", "Status and value of pledged collateral", "Collateral", "Specific", [
        ("asset_desc", "TEXT"), ("stated_value", "REAL"),
        ("perfected", "INTEGER"), ("custodian", "TEXT")]),
    ("indemnity", "Indemnity agreements still in force", "Collateral", "Specific", [
        ("gai_date", "TEXT"), ("in_force", "INTEGER"),
        ("defect_note", "TEXT"), ("counsel_ok", "INTEGER")]),
    ("guarantor", "Personal guarantor financial condition", "Collateral", "General", [
        ("person_name", "TEXT"), ("stated_nw", "REAL"),
        ("liquid_assets", "REAL"), ("collectability", "TEXT")]),
    ("macro", "Industry and macroeconomic conditions", "Conditions", "General", [
        ("prime_rate", "REAL"), ("unemployment", "REAL"),
        ("unrest_note", "TEXT"), ("political_note", "TEXT"),
        ("sector_cycle", "TEXT")]),
    ("bondform", "Bond-form and obligation changes", "Conditions", "Specific", [
        ("form_id", "TEXT"), ("rider", "TEXT"),
        ("hazardous_clause", "INTEGER"), ("change_note", "TEXT")]),
    ("concentration", "Exposure concentration", "Conditions", "General", [
        ("principal_pct_book", "REAL"), ("industry_pct_book", "REAL"),
        ("geo_pct_book", "REAL"), ("cluster_note", "TEXT")]),
    ("cadence", "Monitoring cadence vs. credit quality", "Conditions", "General", [
        ("policy_cadence", "TEXT"), ("actual_cadence", "TEXT"),
        ("overdue_reviews", "INTEGER"), ("match_flag", "TEXT")]),
]

BASE_COLS = """
  obs_id           TEXT PRIMARY KEY,
  investment_id    TEXT NOT NULL,
  as_of_date       TEXT NOT NULL,
  residual_score   INTEGER NOT NULL CHECK (residual_score BETWEEN 1 AND 10),
  band             TEXT,
  assessor         TEXT,
  material_change  INTEGER DEFAULT 0,
  source_1         TEXT,
  source_2         TEXT,
  source_3         TEXT,
  notes            TEXT,
  created_at       TEXT DEFAULT (datetime('now'))
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10, isolation_level="DEFERRED")
    # Separate files already isolate write locks. DELETE journal avoids WAL/SHM
    # chatter on network/overlay filesystems used in this workspace.
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    return con


def band(score: int) -> str:
    if score <= 3:
        return "Low"
    if score <= 5:
        return "Moderate"
    if score <= 7:
        return "Elevated"
    return "Critical"


def _rm(path: Path) -> None:
    if path.exists():
        path.unlink()


def init_portfolio() -> sqlite3.Connection:
    _rm(PORTFOLIO)
    _rm(Path(str(PORTFOLIO) + "-wal"))
    _rm(Path(str(PORTFOLIO) + "-shm"))
    con = connect(PORTFOLIO)
    con.executescript("""
    CREATE TABLE industry (
      industry_id INTEGER PRIMARY KEY, naics TEXT, name TEXT NOT NULL UNIQUE, cycle_note TEXT);
    CREATE TABLE geography (
      geo_id INTEGER PRIMARY KEY, country TEXT NOT NULL DEFAULT 'US',
      state TEXT, metro TEXT, name TEXT NOT NULL);
    CREATE TABLE principal (
      principal_id INTEGER PRIMARY KEY, legal_name TEXT NOT NULL, dba TEXT,
      tax_id_last4 TEXT, entity_type TEXT, industry_id INTEGER REFERENCES industry(industry_id),
      hq_geo_id INTEGER REFERENCES geography(geo_id), formed_date TEXT,
      status TEXT DEFAULT 'active', created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE person (
      person_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, role_default TEXT,
      created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE principal_person (
      principal_id INTEGER NOT NULL REFERENCES principal(principal_id),
      person_id INTEGER NOT NULL REFERENCES person(person_id),
      role TEXT NOT NULL, ownership_pct REAL, is_indemnitor INTEGER DEFAULT 0,
      PRIMARY KEY (principal_id, person_id, role));
    CREATE TABLE license_registry (
      license_id INTEGER PRIMARY KEY, principal_id INTEGER NOT NULL REFERENCES principal(principal_id),
      license_type TEXT NOT NULL, license_no TEXT, jurisdiction TEXT, status TEXT,
      issued_on TEXT, expires_on TEXT, board TEXT);
    CREATE TABLE court_case (
      case_id INTEGER PRIMARY KEY, principal_id INTEGER REFERENCES principal(principal_id),
      person_id INTEGER REFERENCES person(person_id), court TEXT, docket TEXT,
      caption TEXT, filed_on TEXT, status TEXT, amount REAL, nature TEXT);
    CREATE TABLE public_lien (
      lien_id INTEGER PRIMARY KEY, principal_id INTEGER REFERENCES principal(principal_id),
      person_id INTEGER REFERENCES person(person_id), lien_type TEXT NOT NULL,
      jurisdiction TEXT, file_no TEXT, filed_on TEXT, amount REAL, status TEXT,
      secured_party TEXT);
    CREATE TABLE business_credit_snapshot (
      snap_id INTEGER PRIMARY KEY, principal_id INTEGER NOT NULL REFERENCES principal(principal_id),
      as_of_date TEXT NOT NULL, bureau TEXT NOT NULL, score REAL, paydex REAL, notes TEXT,
      UNIQUE (principal_id, as_of_date, bureau));
    CREATE TABLE person_credit_snapshot (
      snap_id INTEGER PRIMARY KEY, person_id INTEGER NOT NULL REFERENCES person(person_id),
      as_of_date TEXT NOT NULL, bureau TEXT NOT NULL, score INTEGER, notes TEXT,
      UNIQUE (person_id, as_of_date, bureau));
    CREATE TABLE macro_observation (
      macro_id INTEGER PRIMARY KEY, as_of_date TEXT NOT NULL,
      geo_id INTEGER REFERENCES geography(geo_id),
      industry_id INTEGER REFERENCES industry(industry_id),
      series TEXT NOT NULL, value REAL, unit TEXT, source TEXT, note TEXT);
    CREATE TABLE investment_index (
      investment_id TEXT PRIMARY KEY, principal_id INTEGER NOT NULL REFERENCES principal(principal_id),
      bond_number TEXT, bond_class TEXT, obligee TEXT, penal_sum REAL,
      issue_date TEXT, status TEXT DEFAULT 'open', master_db_path TEXT NOT NULL,
      created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE investment_geo (
      investment_id TEXT NOT NULL REFERENCES investment_index(investment_id),
      geo_id INTEGER NOT NULL REFERENCES geography(geo_id), role TEXT DEFAULT 'operating',
      PRIMARY KEY (investment_id, geo_id, role));
    CREATE TABLE investment_risk_snapshot (
      investment_id TEXT PRIMARY KEY,
      principal_id INTEGER,
      legal_name TEXT,
      bond_number TEXT,
      bond_class TEXT,
      obligee TEXT,
      penal_sum REAL NOT NULL DEFAULT 0,
      residual_agg_score REAL,
      overall_band TEXT,
      max_node_score INTEGER,
      max_node_key TEXT,
      status TEXT,
      refreshed_at TEXT);
    CREATE TABLE node_risk_snapshot (
      investment_id TEXT NOT NULL,
      node_key TEXT NOT NULL,
      title TEXT,
      grp TEXT,
      residual_score INTEGER,
      band TEXT,
      penal_sum REAL NOT NULL DEFAULT 0,
      PRIMARY KEY (investment_id, node_key));
    CREATE VIEW IF NOT EXISTS v_dollars_by_band AS
      SELECT overall_band AS risk_band,
             COUNT(*) AS investment_count,
             SUM(penal_sum) AS asset_dollars,
             ROUND(100.0 * SUM(penal_sum) / NULLIF((SELECT SUM(penal_sum) FROM investment_risk_snapshot), 0), 1) AS pct_of_book
      FROM investment_risk_snapshot
      WHERE status = 'open' OR status IS NULL
      GROUP BY overall_band;
    CREATE VIEW IF NOT EXISTS v_dollars_by_class_band AS
      SELECT bond_class, overall_band AS risk_band,
             COUNT(*) AS investment_count,
             SUM(penal_sum) AS asset_dollars
      FROM investment_risk_snapshot
      GROUP BY bond_class, overall_band;
    CREATE VIEW IF NOT EXISTS v_dollars_by_node_band AS
      SELECT node_key, title, grp, band AS risk_band,
             COUNT(*) AS investment_count,
             SUM(penal_sum) AS asset_dollars
      FROM node_risk_snapshot
      GROUP BY node_key, title, grp, band;
    CREATE VIEW IF NOT EXISTS v_book_totals AS
      SELECT COUNT(*) AS investments,
             SUM(penal_sum) AS asset_dollars,
             AVG(residual_agg_score) AS avg_score,
             SUM(CASE WHEN overall_band IN ('Elevated','Critical') THEN penal_sum ELSE 0 END) AS dollars_elevated_or_worse
      FROM investment_risk_snapshot;
    """)
    return con


def init_investment(inv_id: str, principal_id: int, **master) -> Path:
    import shutil
    folder = INV_ROOT / inv_id
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    master_path = folder / "master.db"
    con = connect(master_path)
    con.executescript("""
    CREATE TABLE investment (
      investment_id TEXT PRIMARY KEY, principal_id INTEGER NOT NULL,
      bond_number TEXT, bond_class TEXT, bond_form TEXT, obligee TEXT,
      penal_sum REAL, issue_date TEXT, expiration_date TEXT, producer TEXT,
      underwriter TEXT, monitoring_cadence TEXT, last_full_review TEXT,
      residual_agg_score REAL, status TEXT DEFAULT 'open', notes TEXT);
    CREATE TABLE common_surveillance (
      investment_id TEXT PRIMARY KEY, package_as_of TEXT, financials_as_of TEXT,
      statements_quality TEXT, assigned_assessor TEXT, next_review_due TEXT,
      overall_band TEXT, updated_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE node_scorecard (
      node_key TEXT PRIMARY KEY, residual_score INTEGER,
      band TEXT, last_obs_id TEXT, last_as_of TEXT, last_updated TEXT);
    CREATE TABLE node_catalog (
      node_key TEXT PRIMARY KEY, title TEXT, grp TEXT, scope TEXT, db_file TEXT);
    """)
    cols = "investment_id, principal_id, bond_number, bond_class, bond_form, obligee, penal_sum, issue_date, expiration_date, producer, underwriter, monitoring_cadence, last_full_review, residual_agg_score, status, notes"
    con.execute(
        f"INSERT INTO investment ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            inv_id, principal_id,
            master.get("bond_number"), master.get("bond_class"), master.get("bond_form"),
            master.get("obligee"), master.get("penal_sum"), master.get("issue_date"),
            master.get("expiration_date"), master.get("producer"), master.get("underwriter"),
            master.get("monitoring_cadence", "quarterly"), master.get("last_full_review"),
            master.get("residual_agg_score"), master.get("status", "open"), master.get("notes"),
        ),
    )
    con.execute(
        "INSERT INTO common_surveillance (investment_id, package_as_of, financials_as_of, statements_quality, assigned_assessor, next_review_due, overall_band) VALUES (?,?,?,?,?,?,?)",
        (
            inv_id, master.get("package_as_of"), master.get("financials_as_of"),
            master.get("statements_quality", "CPA compiled"),
            master.get("assigned_assessor", "desk"),
            master.get("next_review_due"), master.get("overall_band", "Moderate"),
        ),
    )
    for key, title, grp, scope, extra in NODES:
        db_name = f"node_{key}.db"
        ncon = connect(folder / db_name)
        extra_sql = "".join(f",\n  {n} {t}" for n, t in extra)
        ncon.execute(f"CREATE TABLE node_obs ({BASE_COLS}{extra_sql})")
        ncon.execute("CREATE INDEX ix_obs_inv_date ON node_obs(investment_id, as_of_date)")
        ncon.commit()
        ncon.close()
        con.execute(
            "INSERT INTO node_catalog (node_key, title, grp, scope, db_file) VALUES (?,?,?,?,?)",
            (key, title, grp, scope, db_name),
        )
        con.execute(
            "INSERT INTO node_scorecard (node_key, residual_score, band) VALUES (?,?,?)",
            (key, 5, "Moderate"),
        )
    con.commit()
    con.close()
    return master_path


def update_node(inv_id: str, node_key: str, fields: dict) -> str:
    """Write one observation into a single node file. Does not open other node files."""
    folder = INV_ROOT / inv_id
    node_path = folder / f"node_{node_key}.db"
    if not node_path.exists():
        raise FileNotFoundError(node_path)
    spec = next(n for n in NODES if n[0] == node_key)
    extra_names = [c[0] for c in spec[4]]
    obs_id = fields.get("obs_id") or f"{inv_id}-{node_key}-{fields['as_of_date']}"
    score = int(fields["residual_score"])
    base = {
        "obs_id": obs_id,
        "investment_id": inv_id,
        "as_of_date": fields["as_of_date"],
        "residual_score": score,
        "band": fields.get("band") or band(score),
        "assessor": fields.get("assessor"),
        "material_change": int(fields.get("material_change") or 0),
        "source_1": fields.get("source_1"),
        "source_2": fields.get("source_2"),
        "source_3": fields.get("source_3"),
        "notes": fields.get("notes"),
    }
    cols = list(base.keys()) + extra_names
    vals = [base[c] for c in base] + [fields.get(c) for c in extra_names]
    ncon = connect(node_path)
    placeholders = ",".join("?" * len(cols))
    ncon.execute(f"INSERT OR REPLACE INTO node_obs ({','.join(cols)}) VALUES ({placeholders})", vals)
    ncon.commit()
    ncon.close()
    # scorecard lives in master — short lock on master only
    mcon = connect(folder / "master.db")
    mcon.execute(
        "UPDATE node_scorecard SET residual_score=?, band=?, last_obs_id=?, last_as_of=?, last_updated=datetime('now') WHERE node_key=?",
        (score, base["band"], obs_id, fields["as_of_date"], node_key),
    )
    scores = [r[0] for r in mcon.execute("SELECT residual_score FROM node_scorecard WHERE residual_score IS NOT NULL")]
    if scores:
        agg = sum(scores) / len(scores)
        mcon.execute("UPDATE investment SET residual_agg_score=? WHERE investment_id=?", (round(agg, 2), inv_id))
    mcon.commit()
    mcon.close()
    try:
        refresh_portfolio_risk()
    except Exception:
        pass
    return obs_id


def refresh_portfolio_risk(portfolio: Path | None = None, inv_root: Path | None = None) -> dict:
    """Copy each investment's score + penal sum into portfolio.db for book-level dollar views."""
    portfolio = Path(portfolio or PORTFOLIO)
    inv_root = Path(inv_root or INV_ROOT)
    p = connect(portfolio)
    p.execute("DELETE FROM node_risk_snapshot")
    p.execute("DELETE FROM investment_risk_snapshot")
    rows = list(p.execute(
        "SELECT i.investment_id, i.principal_id, pr.legal_name, i.bond_number, i.bond_class, i.obligee, i.penal_sum, i.status, i.master_db_path "
        "FROM investment_index i JOIN principal pr ON pr.principal_id = i.principal_id"
    ))
    for inv_id, pid, name, bnum, bclass, obligee, penal, status, master_path in rows:
        master = inv_root / inv_id / "master.db"
        if not master.exists() and master_path:
            cand = portfolio.parent / master_path
            master = cand if cand.exists() else master
        if not master.exists():
            continue
        m = connect(master)
        inv = m.execute("SELECT residual_agg_score, status, penal_sum FROM investment WHERE investment_id=?", (inv_id,)).fetchone()
        cards = list(m.execute("SELECT node_key, residual_score, band FROM node_scorecard"))
        titles = {r[0]: (r[1], r[2]) for r in m.execute("SELECT node_key, title, grp FROM node_catalog")}
        m.close()
        agg = inv[0] if inv else None
        penal_sum = (inv[2] if inv and inv[2] is not None else penal) or 0
        st = (inv[1] if inv and inv[1] else status) or "open"
        scored = [(k, s, b) for k, s, b in cards if s is not None]
        max_node = max(scored, key=lambda r: r[1]) if scored else (None, None)
        p.execute(
            "INSERT INTO investment_risk_snapshot (investment_id, principal_id, legal_name, bond_number, bond_class, obligee, penal_sum, residual_agg_score, overall_band, max_node_score, max_node_key, status, refreshed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (inv_id, pid, name, bnum, bclass, obligee, penal_sum, agg, band(int(round(agg or 5))), max_node[1], max_node[0], st),
        )
        for key, score, b in cards:
            title, grp = titles.get(key, (key, None))
            p.execute(
                "INSERT INTO node_risk_snapshot (investment_id, node_key, title, grp, residual_score, band, penal_sum) VALUES (?,?,?,?,?,?,?)",
                (inv_id, key, title, grp, score, b or band(score or 5), penal_sum),
            )
    p.commit()
    summary = list(p.execute("SELECT risk_band, investment_count, asset_dollars, pct_of_book FROM v_dollars_by_band"))
    totals = p.execute("SELECT * FROM v_book_totals").fetchone()
    p.close()
    return {"by_band": summary, "totals": totals}


def seed():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    p = init_portfolio()
    p.executemany("INSERT INTO industry (naics, name, cycle_note) VALUES (?,?,?)", [
        ("236220", "Commercial building construction", "late-cycle bid pressure"),
        ("424720", "Petroleum wholesale", "spread compression"),
        ("561612", "Security services", "labor tight"),
    ])
    p.executemany("INSERT INTO geography (country, state, metro, name) VALUES (?,?,?,?)", [
        ("US", "MN", "Minneapolis-St. Paul", "Twin Cities"),
        ("US", "FL", "North Port-Sarasota", "Sarasota"),
        ("US", "NV", "Las Vegas", "Las Vegas"),
    ])
    p.execute(
        "INSERT INTO principal (legal_name, dba, entity_type, industry_id, hq_geo_id, formed_date) VALUES (?,?,?,?,?,?)",
        ("Northland Permit Services LLC", "Northland Bonding", "LLC", 1, 1, "2014-03-01"),
    )
    p.execute(
        "INSERT INTO principal (legal_name, dba, entity_type, industry_id, hq_geo_id, formed_date) VALUES (?,?,?,?,?,?)",
        ("Gulf Coast Fuel Distributors Inc", "Gulf Coast Fuel", "C-Corp", 2, 2, "2008-06-15"),
    )
    p.executemany("INSERT INTO person (full_name, role_default) VALUES (?,?)", [
        ("James H. Keller", "managing member"),
        ("Beth Ann Rivera", "indemnitor"),
        ("Marcus Cole", "president"),
    ])
    p.executemany(
        "INSERT INTO principal_person (principal_id, person_id, role, ownership_pct, is_indemnitor) VALUES (?,?,?,?,?)",
        [(1, 1, "managing member", 80, 1), (1, 2, "indemnitor", 20, 1), (2, 3, "president", 60, 1)],
    )
    p.execute(
        "INSERT INTO license_registry (principal_id, license_type, license_no, jurisdiction, status, board) VALUES (?,?,?,?,?,?)",
        (1, "contractor", "MN-BC-44192", "MN", "active", "Minnesota DLI"),
    )
    p.execute(
        "INSERT INTO court_case (principal_id, court, docket, caption, filed_on, status, amount, nature) VALUES (?,?,?,?,?,?,?,?)",
        (1, "Hennepin County", "27-CV-25-11820", "Vendor v Northland", "2025-11-02", "open", 84000, "trade dispute"),
    )
    p.execute(
        "INSERT INTO public_lien (principal_id, lien_type, jurisdiction, file_no, filed_on, amount, status, secured_party) VALUES (?,?,?,?,?,?,?,?)",
        (2, "UCC", "FL", "2026-3088124", "2026-04-18", 250000, "perfected", "Regional Bank NA"),
    )
    p.executemany(
        "INSERT INTO business_credit_snapshot (principal_id, as_of_date, bureau, score, paydex) VALUES (?,?,?,?,?)",
        [(1, "2026-09-01", "D&B", 62, 72), (2, "2026-09-01", "D&B", 54, 65)],
    )
    p.executemany(
        "INSERT INTO person_credit_snapshot (person_id, as_of_date, bureau, score) VALUES (?,?,?,?)",
        [(1, "2026-09-01", "Experian", 718), (3, "2026-09-01", "Equifax", 691)],
    )
    p.executemany(
        "INSERT INTO macro_observation (as_of_date, geo_id, industry_id, series, value, unit, source) VALUES (?,?,?,?,?,?,?)",
        [
            ("2026-09-01", 1, None, "prime_rate", 7.50, "pct", "WSJ Prime"),
            ("2026-08-01", 1, None, "unemployment", 3.8, "pct", "BLS"),
            ("2026-09-01", 2, 2, "sector_cycle", 2, "1-5 weak-strong", "internal"),
        ],
    )
    p.commit()

    invs = [
        dict(
            inv_id="INV-NPL-001", principal_id=1, bond_number="SBA-MN-88421",
            bond_class="license/permit", bond_form="SFAA license",
            obligee="State of Minnesota", penal_sum=50000,
            issue_date="2025-02-01", expiration_date="2026-02-01",
            producer="North Star Agency", underwriter="Desk A",
            package_as_of="2026-09-01", financials_as_of="2025-12-31",
            next_review_due="2026-12-01", notes="Permit bond — contractor license",
        ),
        dict(
            inv_id="INV-GCF-014", principal_id=2, bond_number="CUS-FL-10211",
            bond_class="customs", bond_form="CBP activity",
            obligee="U.S. Customs and Border Protection", penal_sum=100000,
            issue_date="2024-07-15", expiration_date="2027-07-15",
            producer="Gulf Surety", underwriter="Desk B",
            package_as_of="2026-08-15", financials_as_of="2025-12-31",
            next_review_due="2026-11-15", notes="Continuous customs bond",
        ),
    ]
    for inv in invs:
        iid = inv.pop("inv_id")
        pid = inv.pop("principal_id")
        path = init_investment(iid, pid, **inv)
        p.execute(
            "INSERT INTO investment_index (investment_id, principal_id, bond_number, bond_class, obligee, penal_sum, issue_date, status, master_db_path) VALUES (?,?,?,?,?,?,?,?,?)",
            (iid, pid, inv["bond_number"], inv["bond_class"], inv["obligee"], inv["penal_sum"], inv["issue_date"], "open", str(path.relative_to(BUILD))),
        )
        p.execute("INSERT INTO investment_geo (investment_id, geo_id, role) VALUES (?,?,?)", (iid, 1 if pid == 1 else 2, "operating"))
    p.commit()
    p.close()

    # Seed a few node observations (each write opens only that node file)
    update_node("INV-NPL-001", "claims", dict(
        as_of_date="2026-09-01", residual_score=3, assessor="Desk A",
        source_1="Internal loss runs", source_2="Obligee notices", source_3="Prior-surety runs",
        claim_count=0, open_reserves=0, paid_losses=0, pattern_note="clean",
        notes="No claims on this or prior MN permit bonds.",
    ))
    update_node("INV-NPL-001", "suits", dict(
        as_of_date="2026-09-01", residual_score=6, assessor="Desk A",
        source_1="PACER", source_2="Hennepin docket", source_3="Westlaw",
        open_case_count=1, total_exposed=84000, worst_status="open",
        docket_refs="27-CV-25-11820", material_change=1,
        notes="Open trade dispute — watch judgment risk.",
    ))
    update_node("INV-NPL-001", "macro", dict(
        as_of_date="2026-09-01", residual_score=5, assessor="Desk A",
        source_1="WSJ Prime", source_2="BLS", source_3="Sector note",
        prime_rate=7.5, unemployment=3.8, unrest_note=None,
        political_note="state licensing board stable", sector_cycle="late-cycle bid pressure",
    ))
    update_node("INV-GCF-014", "taxucc", dict(
        as_of_date="2026-08-15", residual_score=5, assessor="Desk B",
        source_1="FL UCC", source_2="IRS lien index", source_3="D&B public records",
        tax_lien_count=0, ucc_count=1, priority_secured_party="Regional Bank NA",
        aggregate_amount=250000, notes="Bank UCC only; no tax liens.",
    ))
    update_node("INV-GCF-014", "bizcredit", dict(
        as_of_date="2026-09-01", residual_score=6, assessor="Desk B",
        source_1="D&B", source_2="Experian Business", source_3="Equifax Commercial",
        bureau="D&B", score=54, prior_score=58, direction="down",
    ))

    refresh_portfolio_risk()

    manifest = {
        "portfolio": str(PORTFOLIO),
        "investments": ["INV-NPL-001", "INV-GCF-014"],
        "nodes": [n[0] for n in NODES],
        "locking": "WAL + one SQLite file per node; update_node() opens only that file plus a short master scorecard write",
    }
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=2))
    # Publish into artifacts/
    dest_pf = PUBLISH / "portfolio.db"
    dest_inv = PUBLISH / "investments"
    if dest_pf.exists():
        dest_pf.unlink()
    if dest_inv.exists():
        shutil.rmtree(dest_inv)
    shutil.copy2(PORTFOLIO, dest_pf)
    shutil.copytree(INV_ROOT, dest_inv)
    shutil.copy2(BUILD / "manifest.json", PUBLISH / "manifest.json")
    print(json.dumps(manifest, indent=2))
    print("published", dest_pf, dest_inv)


if __name__ == "__main__":
    seed()
