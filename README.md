# PRA Review Desk

Calm surveillance desk for a commercial investment or project. Hub condition is the **worst** live category, not an average.

## Open

- [Review desk](./index.html) — material changes, $ impact, protection, items to review
- [7-category wheel](./category.html) — categories roll up from child nodes (MAX)
- [28-factor wheel](./factors.html) — original spoke model

If GitHub Pages is on: `https://cactusjackmn.github.io/commercial-bond-pra-wheel/`

Otherwise download the HTML and open it in a browser. GitHub’s file preview does not run the GUI.

## Model

1. **Review desk first.** Four tiles: material changes, potential financial impact, existing protection, items requiring review. Click an alert for trend, supporting data, and the risk-model branch.
2. **Hedges show residual.** Coverage, expiry, settle vs realized, counterparty, collateral. Exposure **after** the hedge is what is watched. Another energy commodity is not a hedge unless the cash-flow link is on file under stress.
3. **Missing data is an alert.** Silence is not Low.
4. **Statistical charts ≠ covenants.** Generation vs weather-adjusted plan is a watch. DSCR lock-up is a contract threshold. Different responses.
5. **Seven categories**, 28 child nodes. Category = worst child. Hub = worst category.

## Database

See [`pra_db/`](./pra_db/). Split SQLite so one node write does not lock the book. `portfolio.db` indexes all investments and rolls **asset dollars by risk band**.

```
python3 pra_db/init_pra_db.py
```

## Pages

Settings → Pages → Source: Deploy from a branch → `gh-pages` or `main` / root. A workflow is in `.github/workflows/pages.yml`.
