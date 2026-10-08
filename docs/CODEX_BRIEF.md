# Codex Brief — Lloyd’s Market News Digest

Current operational references:
- [Documentation index](README.md)
- [v1.1.0 release](releases/v1.1.0.md)
- [Model rollout](deployment/gpt6-luna-rollout.md) and [credit monitoring](deployment/openai-balance-alerts.md)

Historical design documents:
- PRD: docs/prd/Lloyds_News_Digest_PRD_v1_Final.docx
- Implementation Plan: docs/plan/Lloyds_News_Digest_Implementation_Plan_v1_1.docx

Operating rules:
- Historical phase development used one phase per branch. Current maintenance should follow the user-authorised scope and preserve unrelated work.
- For each phase: follow the phase checklist + DoD, write/adjust tests, update README, then open a PR.
- The approved daily production path is OpenAI-first: GPT-5 Nano for filtering/classification, GPT-6 Luna for writing. Keep Luna reasoning at none and its configured completion cap; do not re-enable historical multi-provider defaults inadvertently.
- Do not commit secrets. Use .env.example + .env (gitignored).
- Conda env: `314`. The validated server runtime is Python 3.12; the environment name is not a Python-version assertion. Historical phase plans targeted Python 3.14.
