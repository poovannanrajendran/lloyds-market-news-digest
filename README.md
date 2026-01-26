# Lloyd’s Market News Digest

Local-first news discovery + extraction + AI scoring + HTML/email digest for London Lloyd’s Market.

## Phase 01 — Quickstart
- Conda env: `314` (Python 3.14)
- Copy `.env.example` -> `.env` and set DB + SMTP + Ollama values
- Ensure `config.yaml` exists in the repo root (a minimal sample is included)

### Run the CLI (Phase 01)
```bash
conda activate 314
python -m lloyds_digest --help
python -m lloyds_digest run --now
python -m lloyds_digest run --run-date 2026-01-26
```

### Config overrides via env
Use `LLOYDS_DIGEST__` with double underscores for nesting:
```bash
export LLOYDS_DIGEST__CACHE__ENABLED=true
export LLOYDS_DIGEST__OUTPUT__DIRECTORY=output
```
