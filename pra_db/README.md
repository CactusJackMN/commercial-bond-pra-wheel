# Commercial Bond PRA database

Split-file SQLite so a write to one PRA node does not lock the portfolio or other nodes.

```
pra_db/
  portfolio.db                  shared entities + investment index
  investments/INV-…/master.db   one investment + common fields + scorecard
  investments/INV-…/node_*.db   28 node files (one table `node_obs` each)
  init_pra_db.py                builder + update_node()
  schema.sql                    documented DDL
```

## Why three layers

| Layer | File | Holds | Shared across investments? |
| --- | --- | --- | --- |
| Portfolio | `portfolio.db` | Principal, people, licenses, court cases, UCC/tax liens, bureau snapshots, macro series (prime, unemployment, unrest, politics), **investment_index** | Yes |
| Investment master | `investments/<ID>/master.db` | Bond terms + package dates + assessor + **node_scorecard** | No |
| Node | `investments/<ID>/node_<key>.db` | Time-stamped observations for that factor only | No |

Fields that belong to the *company* or the *market* (credit scores, licenses, lawsuits, prime rate) live in the portfolio so two bonds on the same principal do not duplicate them. Each bond still has its own residual score on the node that *uses* that shared fact.

## Locking

`update_node(inv_id, node_key, fields)` opens only `node_<key>.db`, writes one row, then briefly updates `master.db` scorecard and aggregate. Other node files stay unlocked. Two desks can score `suits` and `liquidity` at the same time.

SQLite locking is per file. In PostgreSQL the same schema is one database with 28 tables and row-level locks; keep the same table names.

## Portfolio dollars by risk

`refresh_portfolio_risk()` copies each bond’s penal sum and scores into `portfolio.db` so the book can be queried without opening node files.

- `v_dollars_by_band` — asset dollars by **investment-average** band
- `v_dollars_by_worst_node` — same dollars by **hottest spoke** on that bond
- `v_dollars_by_class_band` — class × band
- `v_dollars_by_node_band` — which factor is marking how many dollars
- `v_book_totals` — book size, average score, dollars Elevated or worse

Asset dollars = open penal sum. Sample book is $150,000 average-Moderate; both bonds have an Elevated worst node.

```sql
SELECT risk_band, investment_count, asset_dollars, pct_of_book
FROM v_dollars_by_band;
```

## Seeded sample

- `INV-NPL-001` — MN license/permit bond, Northland Permit Services LLC
- `INV-GCF-014` — CBP customs bond, Gulf Coast Fuel Distributors Inc

Seeded node rows: claims, suits, macro on 001; taxucc, bizcredit on 014.

```python
from init_pra_db import update_node
update_node("INV-NPL-001", "liquidity", {
    "as_of_date": "2026-09-14",
    "residual_score": 4,
    "assessor": "Desk A",
    "current_ratio": 1.6,
    "working_capital": 220000,
    "cash": 81000,
    "source_1": "Interim financials",
})
```
