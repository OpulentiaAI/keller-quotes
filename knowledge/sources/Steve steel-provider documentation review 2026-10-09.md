---
type: source::au-base-types
tldr: "Official provider documentation read on 2026-10-09; capability claims are distinct from authenticated access and verified purchasing applicability."
origin: https://help.fastmarkets.com/en_US/fastmarkets-physical-prices-api
---

Based on [[Steve user steel-provider research 2026-10-09]]. Public documentation was retrieved read-only; no licence was purchased and no authenticated steel-price endpoint was called.

- [[Fastmarkets]]: official Physical Prices API documents permissioned bearer scope `fastmarkets.physicalprices.api`, form-encoded `POST https://api.fastmarkets.com/physical/v2/Prices`, required Symbols and optional Dates. Omitting Dates returns latest available assessments. Responses carry symbol, prices, assessmentDate, revision and low/mid/high. The three series pages independently confirm the daily/weekly cadence and USD/cwt FOB-mill basis. [Licensing](https://www.fastmarkets.com/data-licensing/) explicitly covers derived calculations and direct/indirect users; no licence or AI/display rights assumed.
- [[MetalMiner]]: [MCP documentation](https://agmetalminer.com/mcp-metal-prices/) specifies Streamable HTTP `https://mcp.metalminer.com/mcp`, OAuth 2.0 account sign-in, industrial steel coverage, and premium entitlement for forecasts/scenarios/production cost. It does not provide authenticated tool schemas or prove steel-series freshness. [Should-cost overview](https://agmetalminer.com/metals-101/should-cost-model/) describes modeled raw material, manufacturing/conversion and procurement intelligence. These are provider capabilities, not validated Keller costs.
- [[CRU]]: the official [HRC methodology summary](https://www.crugroup.com/en/data/prices-and-indices/steel-prices/the-cru/) says prior-week spot transactions, weekly publication including holidays, and CME settlement use. [DataLab](https://www.crugroup.com/en/solutions/datalab-api/cru-datalab-api/) documents JSON delivery and enterprise licensing with client ID/secret.
- [[Platts]]: [API landing page](https://developer.spglobal.com/energy/delivery-solutions/api) exists; detailed series metadata was not retrieved here. The user's daily-HRC statement remains attributed research, not independently verified metadata.

The initial generic Metals-API experiment was replaced before commit in favor of the user-prioritized Fastmarkets contract. BLS series PCU331110331110 remains a monthly industry index, never dollars per pound; Exa discovery locates public supplier pages, never proves a supplier price. No market/index/search record is accepted directly as a `CostSource` by the costing worksheet.

Implementation/test observations at this checkpoint: new bounded market reader's 12 synthetic tests pass; should-cost and order suites have 66 passing tests and TypeScript build passes. These are local checks, not live provider qualification or price-accuracy evidence. The original worktree remains uncommitted during a pending merge; new WonderSearch lane starts separately from main. Do not infer PR lifecycle or deployment from this record.
