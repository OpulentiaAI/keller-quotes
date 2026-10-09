---
type: source::au-base-types
tldr: "Jeremy's supplied MetalMiner reference and Opulent steel-provider shortlist; preserved as research, not a live price feed or purchase decision."
origin: https://app.devin.ai/sessions/df08d2657e8244e2a114050ec459c0b9
---

User requirement: intelligent alternatives when suitable analogs do not exist, without derailing implementation; document everything in Ars Umbris structured format. Reference: https://agmetalminer.com/metals-101/should-cost-model/ . Supplied prior research thread: https://platform.opulentia.ai/thread/m57bejb21v7rgsxr25wv0x6vnx8fyq56 . The external thread was supplied as a reference; its private content was not independently fetched.

## Supplied research, preserved

> Fastmarkets is my first choice if by “Crustdata-quality equivalent” you mean reliable, current steel-pricing data delivered through an API. MetalMiner is also worth shortlisting if you’re building an AI procurement product, while CRU matters if customers’ steel contracts already reference its benchmark.
>
> I’ve assumed you mean [C. Keller Manufacturing in Villa Park, Illinois](https://www.ckellermfg.com/), which does steel fabrication, laser cutting, forming and welding. Its exact purchasing mix isn’t public, so I haven’t assumed particular grades or thicknesses.

| Provider | Supplied rationale | What “live” means in the supplied research |
|---|---|---|
| [Fastmarkets](https://www.fastmarkets.com/platform/api/) | Best starting point for a benchmark-pricing API. Physical Prices API returns latest/historical assessments, timestamps, revisions and instrument IDs. | Midwest HRC daily; CRC and hot-rolled-base galvanized weekly. Fast delivery is not continuous reassessment. |
| [CRU](https://www.crugroup.com/en/data/prices-and-indices/steel-prices/the-cru/) | Established US contract benchmark. Midwest HRC uses actual spot transactions and underpins CME CRU HRC futures settlement. | Weekly, prior-week transactions. [DataLab API](https://www.crugroup.com/en/solutions/datalab-api/cru-datalab-api/) needs enterprise licence. |
| [MetalMiner](https://agmetalminer.com/mcp-metal-prices/) | AI-ready MCP with HRC, CRC, galvanized, plate, forecasts and estimated production costs; procurement-oriented. | Advertises live data; per-series cadence, freshness and accuracy still require testing. |
| [S&P Global / Platts](https://developer.spglobal.com/energy/delivery-solutions/api) | Enterprise benchmark/API alternative with broad commodity coverage. | Supplied research says daily US HRC and entitled REST/JSON delivery; no authenticated call tested. |

> A steel benchmark is not the price a fabricator can actually buy at. A mill-level HRC index won’t by itself capture the grade, thickness, coating, order size, processing, service-centre margin or freight in a delivered sheet quote. For an accurate buying or estimating tool, I’d combine Fastmarkets or CRU benchmarks with the manufacturer’s own supplier quotes and purchase-order history.

Candidate Fastmarkets series supplied:
- [MB-STE-0184: US Midwest hot-rolled coil, daily](https://www.fastmarkets.com/commodity-prices/steel-hot-rolled-coil-index-fob-mill-us-midwest-dollar-cwt-mb-ste-0184/).
- [MB-STE-0185: US cold-rolled coil, weekly](https://www.fastmarkets.com/commodity-prices/steel-cold-rolled-coil-fob-mill-us-dollar-cwt-mb-ste-0185/).
- [MB-STE-0883: US HDG hot-rolled base, weekly](https://www.fastmarkets.com/commodity-prices/steel-hot-dipped-galvanized-coil-hot-rolled-base-fob-mill-us-dollar-cwt-mb-ste-0883/).

> Check licensing before integrating. If this will serve multiple manufacturing customers, ask explicitly for customer-facing display, derived pricing and AI-use rights—not just API access. [Fastmarkets’ published licence guidance](https://www.fastmarkets.com/data-licensing/) restricts sharing and also covers derived data. I haven’t obtained vendor quotes or tested authenticated endpoints, so this is a source-backed shortlist, not a measured API-quality comparison.
>
> My call: evaluate Fastmarkets first for the data foundation and MetalMiner alongside it for the procurement/AI experience. Choose CRU instead where the customer’s existing contracts use CRU. Are you building software for manufacturers, or choosing a tool for one manufacturer’s purchasing team?

This note retains the research question, not a newly answered deployment/licensing assumption. See [[Steve steel-provider documentation review 2026-10-09]] for independently read official sources and [[map - Steve should-cost and retrieval lanes]] for status.
