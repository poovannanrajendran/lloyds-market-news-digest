# Lloyd's Market News Digest Deployment Guide

Target host: `automation-runner-01`  
VM details: `192.168.1.30` / `100.90.70.30`  
Schedule: Daily at `08:00` (Europe/London)

## 1. Prerequisites

- Ubuntu/Debian host with `sudo` access
- Existing Docker Postgres container with live data (do not reset)
- MongoDB Atlas connection string
- OpenAI API key
- GitHub repo write access (deploy key or PAT)

## 2. Connect to the VM

```bash
ssh <user>@192.168.1.30
# or over Tailscale:
ssh <user>@100.90.70.30
```

## 3. Install base packages

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates bzip2 postgresql-client cron
sudo systemctl enable --now cron
```

## 4. Clone repository

```bash
sudo mkdir -p /opt/automation
sudo chown -R "$USER":"$USER" /opt/automation
cd /opt/automation
git clone https://github.com/poovannanrajendran/lloyds-market-news-digest.git
cd lloyds-market-news-digest
git checkout main
git pull --ff-only
```

## 5. Install Conda and create env `314`

```bash
curl -fsSL -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash /tmp/miniconda.sh -b -p "$HOME/miniconda3"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
conda config --set auto_activate_base false
conda create -y -n 314 python=3.12 pip
conda activate 314
python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
pip install "psycopg[binary]"
```

## 6. Configure environment file

Preferred: copy the validated local `.env` file.

```bash
# run from your workstation
scp /Users/poovannanrajendran/Documents/GitHub/lloyds-market-news-digest/.env <user>@192.168.1.30:/opt/automation/lloyds-market-news-digest/.env
```

On the VM:

```bash
cd /opt/automation/lloyds-market-news-digest
chmod 600 .env
```

Recommended reliability override:

```bash
echo "DIGEST_MIN_ITEMS=1" >> .env
```

## 7. Ensure Postgres is reachable from host (without resetting data)

If Postgres runs in Docker and `POSTGRES_HOST=localhost`, the container must publish port `5432` to loopback.

Check:

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo ss -ltnp | grep 5432
```

If no host port is published, update `/opt/runner/deploy/docker-compose.yml` for service `postgres`:

```yaml
ports:
  - "127.0.0.1:5432:5432"
```

Then recreate only Postgres container (data stays in mounted volume):

```bash
sudo docker compose -f /opt/runner/deploy/docker-compose.yml --env-file /opt/runner/deploy/.env up -d postgres
```

## 8. Apply Postgres migrations (safe)

These migrations use `CREATE ... IF NOT EXISTS` and do not drop data.

```bash
cd /opt/automation/lloyds-market-news-digest
set -a
source .env
set +a
bash scripts/db_init_postgres.sh
```

## 9. Configure Git for automated publish

```bash
cd /opt/automation/lloyds-market-news-digest
git config user.name "automation-runner-01"
git config user.email "<your-email>"
git remote set-url origin git@github.com:poovannanrajendran/lloyds-market-news-digest.git
```

Create deploy key and lock GitHub SSH to that key:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_lloyds -N "" -C "automation-runner-01-lloyds"
cat > ~/.ssh/config <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_lloyds
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
chmod 600 ~/.ssh/config ~/.ssh/id_ed25519_lloyds
chmod 644 ~/.ssh/id_ed25519_lloyds.pub
cat ~/.ssh/id_ed25519_lloyds.pub
```

Add that public key as a **write-enabled deploy key** on the repository, then test:

```bash
ssh -T git@github.com
```

## 10. Validate DB connectivity

```bash
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate 314
cd /opt/automation/lloyds-market-news-digest
export PYTHONPATH="$PWD/src"
python - <<'PY'
from lloyds_digest.storage.postgres_repo import PostgresRepo
from lloyds_digest.storage.mongo_repo import MongoRepo
from lloyds_digest.utils import load_env_file
load_env_file('.env', override=True)
print("Postgres ping:", PostgresRepo.from_env().ping())
print("Mongo ping:", MongoRepo.from_env().ping())
PY
```

## 11. Run a bounded manual pipeline check

```bash
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate 314
cd /opt/automation/lloyds-market-news-digest
set -a; source .env; set +a
export PYTHONPATH="$PWD/src"
python -m lloyds_digest run --now --max-urls 2 --max-candidates 2 --verbose
```

## 12. Run post-pipeline render/publish chain (dry run)

```bash
python scripts/render_digest_llm_compare.py
python scripts/render_linkedin_post.py
python scripts/render_linkedin_image_from_template.py
DRY_RUN=1 ./scripts/publish_github_pages.sh
python scripts/render_run_dashboard.py
```

## 13. Configure cron for 08:00 daily

```bash
crontab -e
```

Add:

```cron
CRON_TZ=Europe/London
0 8 * * * cd /opt/automation/lloyds-market-news-digest && /bin/bash -lc 'source "$HOME/miniconda3/etc/profile.d/conda.sh" && conda activate 314 && export PYTHONPATH=$PWD/src && ./scripts/run_daily.sh' >> /opt/automation/lloyds-market-news-digest/logs/cron.log 2>&1
```

Verify:

```bash
crontab -l
```

`scripts/run_daily.sh` now performs `git pull --ff-only` at startup, so the runner stays in sync with upstream `main` before generating and publishing docs.

## 14. Operational checks

- Confirm GitHub Pages reflects new digest after run
- Check `output/dashboard/index.html` for run metrics and failures
- Keep `.env` out of version control
- Rotate API keys immediately if ever exposed
- Configure alerts using `docs/deployment/alert-notifications.md`

## Troubleshooting quick checks

- OpenAI errors: verify `OPENAI_API_KEY`, model names, and `OPENAI_SERVICE_TIER=flex`
- Postgres auth errors: verify app `.env` matches live Postgres credentials
- Postgres connection refused: verify `127.0.0.1:5432` is published from container
- Mongo errors: verify Atlas URI and IP allowlist
- Git push failures: verify deploy key is added with write access and `ssh -T git@github.com` succeeds
- Git pull failures in cron: verify deploy key auth is working for `origin` and branch is fast-forwardable
- n8n alert checks not firing: verify `N8N_PUBLIC_API_KEY`, workflow ID, and cron entries for `check_n8n_workflow_alerts.sh`
