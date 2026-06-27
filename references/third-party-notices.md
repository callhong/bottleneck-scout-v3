# Third-party Notices

## Code Adapted

### a-stock-data

- Source: `https://github.com/simonlin1212/a-stock-data`
- License: Apache-2.0
- Adapted files in this repository:
  - `scripts/data_sources/a_stock.py`
  - `scripts/fetch_a_stock_data.py`
  - `scripts/test_a_stock_data.py`

Adaptation scope:

- A-share ticker normalization.
- Tencent quote parsing.
- Eastmoney throttled request helper and public endpoints for research reports, stock info, concepts, fund flow, margin, holder count and dividends.
- Optional endpoints for K-line with MA, minute fund flow, block trades, dragon-tiger lists, lockup expiry, industry comparison, THS hot reasons, northbound flow, stock news and global fast news.
- Sina financial statements.
- CNINFO announcement lookup with dynamic `orgId`.
- Provenance metadata and explicit dataset selection for bottleneck-scout-v3.

Changes from upstream:

- Converted Markdown-embedded snippets into a standalone Python package.
- Added a behavior-oriented error taxonomy.
- Added per-dataset source/date/evidence metadata.
- Kept network fetches explicit; no default all-provider scan.
- Added optional report PDF download via `--download-report-pdfs`; report lists remain the default to avoid clutter and bandwidth.
- Added mock-based tests that do not hit live endpoints.

Not adapted:

- `mootdx` TCP/F10 helpers, because they add optional binary/TCP dependencies and may fail by network region.
- `iwencai`, because it needs a separate key and should stay user-authorized.
- `akshare`, `baostock`, `tushare` provider chains, because this skill does not default to multi-provider scans.

## Methodology Read, Not Copied

The following local projects were inspected for ideas and boundaries, but their
code, corpora, reports, screenshots, personality layers, trading language and
data snapshots were not copied into this repository:

- `TradingAgents`: vendor error/routing discipline.
- `UZI-Skill`: provider health/fallback discipline and trap-detection checklist shape.
- `ai-berkshire`: financial-data cross-check discipline and business-quality checklist ideas.
- `buffett-skills`: moat, owner-earnings and management-quality checklist ideas.
- `financial-services`: task gating, QA findings table and institutional delivery discipline.
- `serenity-skill`: scarce-layer research workflow.
- `zhengxi-views`: separation of quote, verified fact, framework inference and unresolved claim.

These inspirations are reflected only as local rules and documentation. They do
not add fixed multi-agent execution, multi-model voting, paid connectors,
portfolio actions, buy/sell/position sizing, or external runtime dependencies.
