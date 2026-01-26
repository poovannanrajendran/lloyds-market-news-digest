# Codex Brief — Lloyd’s Market News Digest

Source of truth:
- PRD: docs/prd/Lloyds_News_Digest_PRD_v1_Final.docx
- Implementation Plan: docs/plan/Lloyds_News_Digest_Implementation_Plan_v1_1.docx

Operating rules:
- Implement ONE phase per branch (phase-01, phase-02, …).
- For each phase: follow the phase checklist + DoD, write/adjust tests, update README, then open a PR.
- Keep the system local-first (Ollama by default). Cloud AI must be optional + capped.
- Do not commit secrets. Use .env.example + .env (gitignored).
- Python: 3.14; Conda env: 314.
