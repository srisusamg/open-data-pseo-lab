# Reusable pSEO platform architecture

This repository has two isolated sites, OpenData Atlas and AI Model Economics, on top of a small reusable platform. The structure is intentionally based on ordinary Python functions and data contracts. There is no plugin registry, hook lifecycle, dynamic discovery, or dependency-injection framework.

## Dependency direction

```text
sites/open-data-atlas/ configuration + templates
                    │
                    ▼
              platform/build.py
               │           │
               ▼           ▼
 platform/providers/   platform/recipes/
    world_bank/        profile, ranking,
               │       comparison, change
               └──────┬──────┘
                      ▼
                 platform/core/
```

Dependencies point inward. Core code does not import a provider, a recipe, or a site. Recipes import only core modules. The World Bank provider imports core contracts and derivations, but recipes never import the provider. The build composition root is the only layer that selects both a provider and recipes for a site.

## Provider boundary

`platform/providers/world_bank/` owns everything that is specific to the World Bank Indicators API:

- request URLs, retries, timeouts, response validation, and source field names;
- the checked-in `world_bank_snapshot.json` schema and its validation;
- conversion from `country_code`, `indicator_code`, and API `date` fields into canonical platform entities, metrics, facts, and normalized series.

`client.fetch_snapshot` receives configured source identifiers as arguments. It does not read OpenData Atlas configuration or templates. `normalizer.normalize_snapshot` is the exit from the provider boundary. No World Bank response object is passed into a recipe.

A future provider should produce the same canonical dataset shape. It does not need to emulate the World Bank snapshot format.

## Canonical entity and fact model

The canonical contracts live in `platform/core/entities.py`, `facts.py`, and `provenance.py`.

An entity has an `id`, stable URL `slug`, and display `name`. A metric has an `id`, `slug`, `name`, `unit`, and display `format`. A normalized fact contains:

- `entity_id` and `metric_id`;
- numeric `value` and `unit`;
- the real `observation_year`;
- provenance containing `source_name`, `source_url`, and `source_metric_id`.

A normalized series groups one entity/metric pair, its observations, latest observation, deterministic derivations, and shared provenance. Missing data stays missing; normalization never interpolates, forecasts, or substitutes zero.

The World Bank snapshot remains unchanged on disk for backward compatibility. It is converted to this canonical model in memory before recipe evaluation.

## Recipe boundary

`platform/recipes/` contains four focused page recipes:

- `profile` evaluates one entity across its normalized metric series;
- `ranking` ranks normalized latest facts for one metric;
- `comparison` calculates differences, leaders, periods, and gap direction for two entities;
- `change` selects real endpoints and calculates change over a configured window.

Recipes accept canonical entities or flattened normalized series. They do not read files, call APIs, render HTML, or know the World Bank response schema. A recipe returns derived view data and/or a quality context. The site composition layer decides which recipes to run and which templates render eligible results.

The default path helpers retain the proven URL shapes (`countries/`, `indicators/`, `compare/`, and `change/`). Their prefixes are arguments or isolated helpers rather than provider behavior.

## Deterministic insight pipeline

`platform/core/insights.py` consumes derived recipe metrics through `InsightContext`. The pipeline is fixed and inspectable:

1. generate structured candidates from available evidence;
2. assign explicit scores for the recipe context;
3. deduplicate candidates by stable claim key;
4. select a bounded, deterministic, diverse set;
5. render sentences only from the selected structured evidence.

There is no model call, random choice, country-specific prose, or provider payload access. The same inputs produce the same candidates, selections, and text.

## Quality gate

`platform/core/quality.py` evaluates publication eligibility before rendering. Common checks cover usable facts, historical coverage, provenance, freshness, differentiated content, insight counts, unique intent, required internal links, canonical URLs, and independently verifiable calculations.

Recipe-specific thresholds are represented by `PagePolicy` values and explicit per-site overrides. Every potential page receives a generated or skipped decision in `page_quality_report.json`. Only generated pages are rendered, linked, and included in the sitemap.

## Site configuration boundary

`sites/open-data-atlas/` owns the current vertical's:

- source identifiers and editorial scope in `config/`;
- site name, canonical base URL, comparison allow-list, and change thresholds;
- Jinja templates and World Bank/OpenData Atlas wording;
- static styling.

`sites/open-data-atlas/runtime.py` selects the World Bank provider and supplies the site's paths. `platform/build.py` accepts those provider functions and contains only reusable orchestration. `scripts/build.py` remains the stable command used locally and by GitHub Actions. The generated output locations remain `data/generated/` and `site/`.

AI Model Economics follows that boundary in `sites/ai-model-economics/`, with its curated adapter in `platform/providers/ai_models/` and provider-neutral domain recipes in `platform/recipes/model_economics.py`. See [ai-model-economics-architecture.md](ai-model-economics-architecture.md) for the deployment decision and vertical-specific contracts.

## Compatibility guarantees

- Public URL paths and canonical URLs are unchanged.
- The World Bank snapshot schema and generated artifact paths are unchanged.
- `scripts/build.py`, `scripts/fetch_world_bank.py`, and the former module imports remain compatibility entry points.
- The existing GitHub Actions command sequence and Pages artifact path are unchanged.
- Offline builds are byte-for-byte stable for the same snapshot and configuration.
