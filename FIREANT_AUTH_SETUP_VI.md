# FireAnt API authorization & secret setup

StockVision cannot grant itself FireAnt licensing. FireAnt must provision a suitable account/plan, client credentials/token and DataFeed specification. FireAnt's public REST API document includes OAuth scopes for some resources, but that alone does not prove that OHLCV/realtime DataFeed redistribution/storage rights are included in every account.

1. Contact FireAnt through official corporate/DataFeed channels and request written authorization for the intended personal use, price history/feed type, storage, retention and display.
2. Obtain the exact technical specification: base URL, HTTP path, parameters, authentication, rate limits, response envelope and timestamp/units.
3. Put secrets only in Render service environment variables/secret manager. Never put them in `index.html`, `manifest.webmanifest`, an iPhone localStorage field or a public repository.
4. Populate `FIREANT_*` settings to match the assigned specification exactly. The adapter intentionally does not guess undocumented paths.
5. Confirm `GET /api/v1/providers/status` reports readiness. This is a configuration check, not a network/authentication test. Then run the approved read-only live test from an authorized server environment.
6. Keep `DEMO_MODE=true` until the live response is normalized and reconciled with an authorized source. Change it to `false` only after data has successfully reached PostgreSQL.

Do not paste the FireAnt API token or database password into a ChatGPT message. Supply them only in your cloud provider's secret environment interface.
