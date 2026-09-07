# OpenData Atlas

OpenData Atlas is a deliberately small programmatic-SEO experiment. It proves an unattended, database-free pipeline:

**World Bank API → normalized JSON → static HTML → validation → generated-data commit → GitHub Pages**

After setup, the weekly GitHub Actions job runs without Codex, an LLM, credentials, a CMS, or a runtime server.

## Architecture

- `config/` defines the site URL, countries, and indicators.
- `scripts/fetch_world_bank.py` fetches a recent 10-year window and selects the latest non-null observation.
- `scripts/model.py` contains deterministic selection, ranking, URL, and number-formatting logic.
- `scripts/build.py` writes normalized data to `data/generated/` and renders Jinja templates into `site/`.
- `scripts/validate.py` checks required pages, titles, H1s, attribution, content size, and internal links.
- `.github/workflows/refresh-and-deploy.yml` refreshes, tests, commits changed generated artifacts, and deploys the same run to Pages.

The generated site contains a home page, one profile per configured country, one ranking per configured indicator, a methodology page, a sitemap, and robots directives. Each observation preserves its World Bank indicator code, observation year, retrieval time, and source URL.

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
- `/indicators/{indicator-slug}/` — five-country ranking
- `/methodology/` — source, selection rules, and limitations

Canonical and sitemap URLs come from `config/site.json`. The checked-in value was derived from this repository's GitHub remote and includes the project-site subpath. Edit this single value if the repository owner or name changes; keep the trailing slash.

## Extend the configured scope

To add a country, append its World Bank ISO3 `code`, URL-safe `slug`, and display `name` to `config/countries.json`, then rebuild and validate.

To add an indicator, append its World Bank `code`, `slug`, `name`, human-readable `unit`, and an existing `format` (`population`, `currency`, `currency_per_person`, `percentage`, or `years`) to `config/indicators.json`. The templates automatically add its profile values and ranking page.

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
