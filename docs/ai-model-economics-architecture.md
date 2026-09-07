# AI Model Economics architecture report

## Outcome

AI Model Economics is a second production-oriented site built from the same repository and shared pSEO core. It has its own site definition, provider adapter, generated-data boundary, quality report, templates, sitemap, validation entry point, and static output under `site/ai-model-economics/`. OpenData Atlas keeps its existing URL paths, configuration, provider, templates, sitemap, and build entry point.

## Deployment decision

The MVP uses **one repository and one Pages artifact, with the second site isolated under `/ai-model-economics/`**. This is the simplest reliable design because GitHub Pages provides one deployment per repository, the existing workflow already publishes `site/`, and the pSEO core is local to this repository. A second repository would add packaging/versioning overhead before the shared core has a stable external API.

The workflow builds OpenData Atlas first, then adds AI Model Economics beneath the existing output directory. Each site has a separate sitemap and validator. OpenData Atlas does not link to, depend on, or import the new vertical. Its validator explicitly ignores the separately validated subsite boundary.

If the second site later needs an independent domain, release cadence, or owner, the cleaner next step is a separate repository consuming a versioned package of `platform/core` and the generic recipes—not a second ad hoc copy of the code.

## Dependency direction

```text
sites/ai-model-economics/ config + templates
                 │
                 ▼
sites/ai-model-economics/build.py
       │                       │
       ▼                       ▼
platform/providers/       platform/recipes/
  ai_models/              model_economics.py
       └────────────┬──────────┘
                    ▼
              platform/core/
```

The provider adapter owns the curated input schema, official-source allow-list, validation, unit translation, and normalization. The recipe owns model-economics derivations, comparison compatibility, paths, release ordering, rankings, and domain wording. Core remains provider-neutral and supplies provenance, quality evaluation, URL handling, rendering, and the deterministic insight pipeline.

## Canonical records

- `Provider`: stable ID, slug, name, and dated provenance.
- `Model`: stable ID and slug, provider, family, release date, lifecycle status, open/closed status, verified context window, capabilities, external IDs, and dated provenance.
- `Benchmark`: stable ID, version, unit, direction, comparability description, and dated provenance.
- `PricingObservation`: model, normalized input/output USD per 1M tokens, tier and threshold qualifiers, and dated provenance.
- `PerformanceObservation`: model, benchmark, value, unit, evaluation configuration, explicit comparison group, and dated provenance.

Every canonical record requires source name, source URL, source metric ID, observation date, effective date, retrieved timestamp, source type, confidence, and status. The adapter rejects missing provenance, unknown relationships, unsupported pricing units, non-USD observations, duplicate IDs/slugs, and sources outside the official-domain allow-list.

## Derivations

- Input and output prices normalize only from explicit USD per token, 1,000 tokens, or 1M tokens.
- `blended-workload-v1` prices 800,000 input tokens plus 200,000 output tokens.
- Relative price difference is `(A - B) / B × 100`, with model B documented as the baseline.
- `intelligence-per-dollar-v1` is `benchmark score / blended workload cost`. It currently includes only `agents-last-exam-v1` observations from one shared launch-table comparison group. It is not a cross-benchmark composite.

All formulas, included benchmarks, versions, and comparison-group identifiers persist in normalized or derived output. Missing input remains missing. No interpolation, guessed price, or model-generated inference enters the catalog.

## Quality and comparison safety

Potential model, provider, comparison, ranking, and release pages pass through the shared quality evaluator. Model pages require complete canonical facts and current pricing. Comparisons additionally require compatible normalized units, pricing within the configured freshness window, complete provenance, and enough deterministic insights. Performance and value leaders are emitted only when both observations match on benchmark ID/version, unit, evaluation configuration, and comparison group.

Only eligible pages are rendered, linked, listed in `generated_urls.json`, and included in the site sitemap. Every potential recipe page receives a generated/skipped record in `page_quality_report.json`.

## Local preview

From the repository root:

```shell
python scripts/build.py --offline
python scripts/build_ai_model_economics.py
python scripts/validate.py
python scripts/validate_ai_model_economics.py
python -m unittest discover -s tests
python -m http.server 8000 --directory site
```

Open `http://localhost:8000/ai-model-economics/`. On this Windows Codex host, use the bundled Python executable if `python` is not on `PATH`.

## Next-phase backlog

1. Replace individual curated observations with authenticated official provider API adapters where stable price/model metadata is available.
2. Add point-in-time price history and effective-date change pages without overwriting prior observations.
3. Add independently governed benchmark sources only after licensing, methodology, and model-configuration comparability are explicit.
4. Add benchmark-specific rankings; do not add a general intelligence composite unless its formula and limitations can survive review.
5. Add automated freshness alerts and source-change review queues.
6. Package and version the shared core if an independent repository or deployment cadence becomes necessary.
7. Add custom-domain deployment only when ownership and release requirements justify separating the Pages artifact.

GPU, data-center, energy, cooling, capex, and company-financial data remain explicitly out of scope.
