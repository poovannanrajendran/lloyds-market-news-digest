# Temporary Nano/Luna relevance shadow audit

This one-off audit is enabled only for daily run dates **10, 11, and 12 October 2026** (Europe/London). The dates are fixed in code; after 12 October, the pipeline stops capturing Nano inputs and the daily runner stops launching the comparison.

## Isolation from the published digest

The production pipeline still uses GPT-5 Nano as the only relevance decision-maker. On eligible dates it records the exact Nano prompt, raw and parsed response, cache status, latency, token usage, and the production decision in an ignored, mode-restricted `logs/model_shadow/` file. Capture errors are logged and fail open. No Nano behavior, acceptance threshold, digest content, or publication decision is changed.

The daily runner starts a separate worker alongside Nano. As each relevance prompt is queued, the worker evaluates it through GPT-6 Luna with at most four calls in flight. The worker cannot change Nano's acceptance result. After GitHub Pages publication succeeds, `run_daily.sh` closes the queue, waits for outstanding shadow calls, and invokes the comparison report generator. This can add post-publication time while Luna calls finish; the successful-publication heartbeat is recorded before that wait. Luna raw and parsed output, errors, latency, token usage, and returned service tier go to a separate JSONL file. Audit/API failures produce an operational warning and do not roll back or block an already-published digest.

The audit adds GPT-6 Luna API usage and cost. It does not add any capture of non-relevance stages. Captured prompts contain article text and are kept on the runner under ignored `logs/`; they are not published to the digest site or committed to Git.

Audit setup failures skip the worker and allow the normal run to continue. The runner uses GNU `timeout` to stop the worker after one hour, with a ten-second forced-termination grace period, including time spent waiting on outstanding API requests. Outside the fixed dates, no shadow prompt is constructed or captured. Both models use the same OpenAI account, so concurrent shadow calls consume shared API quota; content and filtering decisions remain controlled by Nano.

## Report and interpretation

On the runner, reports are written to:

```text
logs/model_shadow/reports/model_comparison_<date>_<run-id>.md
```

Input evidence (`inputs_<run-id>.jsonl`) contains the exact prompt and Nano output. Paired results (`results_<run-id>.jsonl`) add Luna output and usage details. These files can be inspected on the runner after each successful publication.

Each report lists agreement, Nano-only acceptances, Luna-only acceptances, unknown/error cases, latency and estimated cost, with per-article reasons for review. Agreement is not accuracy: no independent human-labelled truth set exists. A Luna-only acceptance is a candidate story Nano excluded; a Nano-only acceptance is a candidate Luna would exclude. Review both groups and the articles in the published digest before deciding whether to change the production filter.

The cost figure is an estimate using model token rates and the returned service tier; the organisation Costs API is authoritative and may lag. The audit is intentionally limited to three runs and does not change production model configuration.
