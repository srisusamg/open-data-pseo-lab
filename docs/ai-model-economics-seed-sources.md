# AI Model Economics seed data source report

Catalog as of 2026-09-07. The MVP contains 12 text-capable models from four providers. Sources are curated official provider documentation and announcements; there is no arbitrary web scraping.

| Provider | Seed models | Official source set | Facts used |
|---|---|---|---|
| OpenAI | GPT-5.6 Sol, Terra, Luna | [Model documentation](https://platform.openai.com/docs/models), [GPT-5.6 launch](https://openai.com/index/gpt-5-6/) | API IDs, status, context, capabilities, current standard prices, release date, two provider-reported benchmark tables |
| Anthropic | Claude Fable 5, Opus 5, Sonnet 5 | [Claude model docs](https://docs.anthropic.com/en/docs/about-claude/models/overview), [Fable 5 launch](https://www.anthropic.com/news/claude-fable-5-mythos-5), [Opus 5 launch](https://www.anthropic.com/news/claude-opus-5), [Sonnet 5 launch](https://www.anthropic.com/news/claude-sonnet-5) | API IDs, active status, context, capabilities, release dates, current standard prices |
| Google | Gemini 3.8 Flash, 3.7 Flash, 3.5 Flash-Lite | [Gemini models](https://ai.google.dev/gemini-api/docs/models), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [3.8 launch](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/), [3.5 Flash-Lite launch](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-6-flash-3-5-flash-lite-3-5-flash-cyber/) | API IDs, status, multimodal capabilities, context, release dates, current/introductory standard prices |
| xAI | Grok 4.6, 4.5, 4.3 | [Models](https://docs.x.ai/developers/models), [Pricing](https://docs.x.ai/developers/pricing), [Release notes](https://docs.x.ai/developers/release-notes) | API IDs, status, context, capabilities, release dates, short-context standard prices and their threshold qualifier |

## Benchmark handling

The seed catalog defines Agents' Last Exam, Artificial Analysis Intelligence Index v4.1, and Terminal-Bench 2.1 as canonical benchmark entities. It stores only six performance observations: two launch-table metrics for the three GPT-5.6 variants. These observations are marked `provider_reported` with medium confidence and an exact shared comparison-group identifier.

The catalog does not import isolated benchmark claims for other models merely to increase coverage. Cross-provider performance claims are suppressed until observations share the same benchmark version, unit, evaluation configuration, and comparison group. `intelligence-per-dollar-v1` includes only Agents' Last Exam inside the GPT-5.6 launch-table cohort; Artificial Analysis values remain visible evidence but are not folded into the value formula.

## Price qualifiers

- Prices are USD list prices per 1M input or output tokens for the named tier.
- Google 3.7/3.8 Flash observations retain their introductory-tier label.
- Grok prices retain the below-200k-prompt threshold; long-context prices are not substituted or averaged.
- Cache, batch, priority, regional, fast-mode, tool, and media charges are excluded.
- Each observation records its effective date separately from retrieval time.

The full normalized records are generated at `data/generated/ai-model-economics/normalized_model_data.json`; versioned derivations and ranking rows are persisted separately in `derived_model_economics.json`.
