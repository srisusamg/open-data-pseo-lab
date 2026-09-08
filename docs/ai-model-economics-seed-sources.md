# AI Model Economics catalog source report

Catalog as of 2026-09-07. Schema v2.0 contains 44 models from 15 providers. Entries are curated from allow-listed official provider documentation, announcements, model cards, and first-party weight repositories; model names discussed only in secondary coverage are not admitted.

| Provider | Included families | Primary official source |
|---|---|---|
| OpenAI | GPT-5.6, gpt-oss, ChatGPT-4o | [Models](https://platform.openai.com/docs/models) |
| Anthropic | Claude 5 | [Claude models](https://docs.anthropic.com/en/docs/about-claude/models/overview) |
| Google | Gemini 3 | [Gemini models](https://ai.google.dev/gemini-api/docs/models) |
| xAI | Grok 4 | [xAI models](https://docs.x.ai/developers/models) |
| Meta | Llama 4 | [Llama downloads and model details](https://ai.meta.com/resources/models-and-libraries/llama-downloads/) |
| DeepSeek | DeepSeek V3, R1 | [DeepSeek API documentation](https://api-docs.deepseek.com/) |
| Mistral | Medium, Small, Large, Ministral | [Mistral models](https://docs.mistral.ai/models) |
| Qwen / Alibaba | Qwen3 | [Qwen3 release](https://qwenlm.github.io/blog/qwen3/) |
| Cohere | Command A, Command R | [Cohere models](https://docs.cohere.com/docs/models) |
| Microsoft | Phi-4 | [Microsoft Foundry model documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/model-inference/concepts/models) |
| NVIDIA | Nemotron 3.5, Nemotron Nano | [NVIDIA model catalog](https://build.nvidia.com/explore/discover) |
| Amazon | Nova 2, Nova | [Amazon Bedrock model cards](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-amazon.html) |
| Moonshot / Kimi | Kimi K2 | [Kimi API model list](https://platform.kimi.ai/docs/models) |
| MiniMax | MiniMax M2 | [MiniMax model list](https://platform.minimax.io/docs/guides/models-intro) |
| Zhipu / GLM | GLM-4.5 | [Z.AI GLM documentation](https://docs.z.ai/guides/llm/glm-4.5) |

## Provenance policy

Every normalized model fact carries a provenance object with source name and URL, source metric ID, effective and observation dates, retrieval timestamp, provenance type, confidence, and verification status. A model-level official source supplies the default field provenance; the input format supports per-field overrides when facts come from different official sources. Pricing and benchmark observations always retain their own independent provenance.

Unknown values remain `null`. Release dates, context windows, architecture details, quantizations, and minimum useful hardware are not inferred. Open-model weight links are recorded only for first-party repositories or provider download pages.

## Pricing policy

`pricing_available` is explicit on every model and must agree with the presence of a comparable pricing observation. Input, output, and optional cached-input prices normalize to USD per 1M tokens while preserving the original tier, effective date, source, and any context threshold. A model without public comparable pricing still receives a profile but is ineligible for input-cost, output-cost, and blended-cost rankings.

## Benchmark policy

The catalog keeps the original small set of provider-reported benchmark observations and does not fill the expanded catalog with isolated claims. A benchmark result is comparable only when benchmark ID/version, unit, evaluation configuration, and comparison group all match. Missing benchmark data is displayed as missing and does not block profile or context-ranking eligibility.

The normalized catalog is generated at `data/generated/ai-model-economics/normalized_model_data.json`; versioned derivations and ranking rows are stored separately in `derived_model_economics.json`.
