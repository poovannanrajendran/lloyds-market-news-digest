# OpenAI estimated credit alerts

The daily runner calls `scripts/check_openai_balance.sh` before the pipeline and
on exit, including failures. The checker reads organisation-wide reported costs
without project/model filters, follows pagination, and sends warnings through
the existing Slack/Discord webhook transport at **$1 or less**. Failure to check
or send does not stop the pipeline. Low-balance and unavailable-data alerts are
each deduplicated for the London calendar day; failed delivery is retried.

This is an **estimated prepaid balance**, not a live OpenAI balance endpoint.
Reported costs may lag usage. Purchases, expiring grants and other billing
adjustments do not appear as top-ups in the Costs API. Reconcile after every
top-up and periodically against Billing Overview.

## Configuration

Store the read-only organisation admin key as `OPENAI_API_ADMIN_KEY` in `.env`.
Set these together from one balance observation and cost query:

- `OPENAI_BALANCE_BASELINE_USD`: observed available credit, e.g. `9.98`.
- `OPENAI_COSTS_START_TIME`: Unix UTC start of the cost query, e.g. `1790812800`
  (1 October 2026).
- `OPENAI_COSTS_BASELINE_USD`: total organisation cost reported from that start
  to the time of the balance observation, e.g. `0.342562925` on 8 October 2026.
- `OPENAI_BALANCE_ALERT_THRESHOLD_USD`: `1` by default, inclusive.

Estimated remaining = observed available credit − (current reported costs −
reported costs at observation). Historical charges are not subtracted twice.
Costs below the baseline are treated as unavailable pending reconciliation.

After a top-up, record the new Billing Overview balance and query the current
Costs API total using the same start time. Update both baseline amounts in
`.env`; the checker recognises the changed baseline and resets deduplication.
Never put keys or `.env` in Git. Keep `.env` permissions at `600`.

```bash
cd /opt/automation/lloyds-market-news-digest
bash scripts/check_openai_balance.sh --dry-run
bash scripts/check_openai_balance.sh
tail -n 20 logs/openai_balance.log
```

Dry run fetches costs and prints the result but does not send messages or update
the balance state. It may create the checker lock file. State is stored privately
in `logs/openai_balance_state.json`; logs and state are excluded from Git.

The existing transport now supports `ALERT_REQUIRE_DELIVERY=1`, used by this
checker so missing webhook configuration or failed HTTP delivery cannot mark an
alert as sent. Other alert callers retain best-effort delivery semantics.

References: [Costs API](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs),
[Administration API](https://developers.openai.com/api/reference/administration/overview).

## Model migration and release

The v1.1.0 writing-model migration does not alter the inclusive $1 threshold or the organisation Costs API calculation. Per-stage Luna pricing is diagnostic and does not drive the balance estimate. Trial and fallback charges may appear after billing delay. See [release evidence and limitations](../releases/v1.1.0.md) and [model rollback](gpt6-luna-rollout.md).
