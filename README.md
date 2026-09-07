# OpenData Atlas

OpenData Atlas is a deliberately small programmatic-SEO experiment. It proves an unattended, database-free pipeline:

**World Bank API → normalized JSON → static HTML → validation → generated-data commit → GitHub Pages**

After setup, the weekly GitHub Actions job runs without Codex, an LLM, credentials, a CMS, or a runtime server.

## Architecture

- `config/` defines the site URL, countries, indicators, comparison allow-list, and supported change windows and quality thresholds.
- `scripts/fetch_world_bank.py` fetches each series and preserves its newest 15 non-null observations with actual source years.
- `scripts/model.py` contains deterministic selection, ranking, URL, and number-formatting logic.
- `scripts/change_metrics.py` selects real historical endpoints and keeps source facts separate from derived change calculations.
- `scripts/insights.py` generates, scores, selects, and renders deterministic structured insights through a reusable `generate_insights(context)` API.
- `scripts/build.py` writes normalized data and page-quality decisions to `data/generated/` and renders Jinja templates into `site/`.
- `scripts/validate.py` checks required pages, titles, H1s, attribution, content size, and internal links.
- `.github/workflows/refresh-and-deploy.yml` refreshes, tests, commits changed generated artifacts, and deploys the same run to Pages.

The generated site contains a home page, one profile per configured country, one ranking per configured indicator, one page per allowed comparison, quality-gated 5- and 10-year What Changed pages, a methodology page, a sitemap, and robots directives. Each country/indicator series preserves its World Bank indicator code, actual observation years, retrieval time, and source URL. Narratives are selected and rendered from structured evidence without AI or country-specific prose.

## Build locally

Python 3.12 is used in CI; Python 3.10+ is supported locally.

```shell
python -m pip install -r requirements.txt
python scripts/build.py
python scripts/validate.py
python -m unittest discover -s tests
python -m http.server 8000 --directory site
```

Then open <http://localhost:8000/>. To rebuild without calling the API, use `python scripts/build.py --offline` after a snapshot exists.

## URLs

- `/` — index of countries and rankings
- `/countries/{country-slug}/` — latest values for one country
- `/indicators/{indicator-slug}/` — configured-country ranking
- `/compare/{first-country-slug}/{second-country-slug}/` — allow-listed country comparison
- `/countries/{country-slug}/change/{start-year}-{end-year}/` — quality-gated configured change window
- `/methodology/` — source, selection rules, and limitations

Canonical and sitemap URLs come from `config/site.json`. The checked-in value was derived from this repository's GitHub remote and includes the project-site subpath. Edit this single value if the repository owner or name changes; keep the trailing slash.

## Extend the configured scope

To add a country, append its World Bank ISO3 `code`, URL-safe `slug`, and display `name` to `config/countries.json`, then rebuild and validate.

To add an indicator, append its World Bank `code`, `slug`, `name`, human-readable `unit`, and an existing `format` (`population`, `currency`, `currency_per_person`, `percentage`, or `years`) to `config/indicators.json`. The templates automatically add its profile values and ranking page.

To add a comparison, append an ordered pair of existing ISO3 country codes to `config/comparisons.json`. Repeated, reversed, self, malformed, and unknown-country pairs fail the build explicitly. The configured order determines both the URL and signed difference direction.

To change the supported historical windows, requested end year, endpoint tolerance, minimum span, insight thresholds, or publication gate, edit `config/change_windows.json`. Only configured windows are generated.

## Automated refresh and deployment

The workflow runs on pushes to `main`, manual dispatches, and Mondays at 06:17 UTC. It installs pinned dependencies, performs a fresh API build, runs tests and validation, commits `data/generated/` and `site/` only when their diff changes, and deploys the freshly built `site/` artifact in the same run. The bot commit does not need to trigger another workflow.

One-time setup: in GitHub, choose **Settings → Pages → Source → GitHub Actions**. Ensure Actions are allowed to create and approve Pages deployments. No repository secrets are needed.

## Troubleshooting

- **Fetch failure:** rerun after checking network access and the World Bank API; failures are explicit and use bounded retries/timeouts.
- **Wrong canonical URL:** update `base_url` in `config/site.json`, preserving `https://` and the trailing slash, then rebuild.
- **Validation failure:** read the listed missing page or broken-link path; validation exits non-zero.
- **Push rejected in the scheduled job:** confirm workflow `contents: write` permission is permitted in repository Actions settings and branch protection allows the GitHub Actions bot update.

## Possible next phase (not implemented)

After this experiment demonstrates stable refreshes, sensible next steps are freshness monitoring, schema-level snapshot diff reports, a broader but curated country set, and richer accessibility/SEO audits. Those are intentionally outside this MVP.
