# GPT-6 Luna daily-run migration

8 October 2026. GPT-6 Luna replaces GPT-5 Mini for article summaries, digest composition and LinkedIn text. GPT-5 Nano remains the relevance/classification model. LinkedIn images still use the existing template renderer.

Released as **v1.1.0**. Implementation commit: `bcca649161d8f2227065256f8e43991140db0ad1`. See the [detailed release notes](../releases/v1.1.0.md) and [documentation index](../README.md). The code was committed, pushed and promoted; local and server private settings were updated with backups.

## Configuration

Set these in the private local and server `.env` files:

```dotenv
OPENAI_MODEL=gpt-6-luna
LLOYDS_DIGEST_LLM_SUMMARISE_MODEL=gpt-6-luna
OPENAI_LINKEDIN_MODEL=gpt-6-luna
LLOYDS_DIGEST_LLM_RELEVANCE_MODEL=gpt-5-nano
LLOYDS_DIGEST_LLM_CLASSIFY_MODEL=gpt-5-nano
OPENAI_REASONING_EFFORT=none
OPENAI_MAX_COMPLETION_TOKENS=8192
OPENAI_SERVICE_TIER=flex
OPENAI_LINKEDIN_SERVICE_TIER=flex
OPENAI_FALLBACK_SERVICE_TIER=default
```

The 8,192-token completion budget covers the configured 15-article digest chunks. `none` avoids inheriting medium reasoning on short editorial tasks. Empty/truncated responses are rejected. JSON writing paths request JSON object mode and validate the object; this is not a strict application schema. No Responses API or SDK migration is needed because this project uses Chat Completions without tools.

Temperature handling is shared across writing paths and excludes GPT-5/6 requests. Flex capacity failures retry on the API-supported `default` tier; old `standard` configuration is normalised at the request boundary. Returned service tiers, cached reads and cache writes are carried into cost calculations. Writes are removed from ordinary input before applying the write rate. Reusing the application's stored AI response records usage but does not record a new charge. Luna cache keys include reasoning effort and completion budget.

Summary prompt v2 and the digest/LinkedIn instructions prohibit adding unreported facts. Sparse excerpts must remain sparse; a newer model cannot repair missing source material. Source extraction improvements are a separate follow-up.

## Validation and limits

The server Python environment passed 63 tests, with one pre-existing disabled live E2E test skipped. Coverage includes both request paths, fallback payloads, returned tiers, empty/truncated/non-object output, caching, cached-write costing and balance-alert boundaries. Existing pytest/deprecation warnings remain unrelated to this migration.

Small live trials compare current Mini and Luna on identical inputs, without publishing or database writes. The first trial used three navigation-heavy article excerpts and caught unsupported extrapolation, prompting tighter source-grounding instructions. It also demonstrated successful real fallback to ordinary processing. A second trial uses three substantive article excerpts and exercises summary, digest and LinkedIn generation. The substantive trial returned all 10 complete responses; Luna produced four factual bullets per article, a three-item digest and a usable LinkedIn draft. Its five calls cost $0.000438 versus $0.006989 for Mini (93.7% lower in this sample, reflecting zero reasoning tokens). One Luna call used default-tier fallback. Summed call durations were 59.74 seconds for Luna versus 65.84 for Mini; calls overlapped, so these are not end-to-end run times. Candidate-specific output and structure checks passed; baseline Mini returned two bullets for one incomplete excerpt, which is permitted by prompt v2. These are smoke checks, not a statistically reliable quality or speed benchmark; evaluate the next scheduled runs before asserting a speed improvement.

At identical September historical token volumes, retaining Nano and replacing Mini reprices $1.665591 to $0.543909 (67.3% lower). Actual reasoning, output lengths, cache writes and default-tier fallback change real costs. GPT-6 Luna Flex rates per million are $0.05 input, $0.005 cached input, $0.0625 cache writes and $0.25 output; ordinary rates are twice these. The organisation Costs API continues to drive the inclusive $1 balance alert independently of these per-stage rates.

## Deployment and rollback

For subsequent deployments, fast-forward the server checkout, update only the selected private environment settings, and verify tests/model settings/balance dry-run on the server. Keep `.env` out of Git. A mode-600 copy of the preceding environment is saved outside the checkout under `~/.local/state/lloyds-env-backups/` before promotion.

For a model rollback, restore the three writing-model settings to `gpt-5-mini` and remove `OPENAI_MAX_COMPLETION_TOKENS` if the previous configuration had no cap. Nano settings stay unchanged. Keep the request/fallback fixes, source-grounding instructions, cost corrections and balance alerts. The next run reads the restored environment. Never rerun the publishing daily script just to validate a rollback.

Check tomorrow's scheduled run for successful publication, complete digest/LinkedIn output, retries, elapsed time and Costs API spending. The morning schedule remains 08:00 Europe/London.

Official references: [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [migration guide](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra#migration-quickstart), [prompt caching accounting](https://developers.openai.com/api/docs/guides/prompt-caching#monitor-cache-performance), [Flex processing](https://developers.openai.com/api/docs/guides/flex-processing).
