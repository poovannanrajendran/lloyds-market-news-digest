from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

from lloyds_digest.config import load_config
from lloyds_digest.utils import load_env_file

import scripts.render_digest_llm_compare as render


def main() -> None:
    load_env_file(Path(".env"))
    config = load_config(Path("config.yaml"))

    items = render.fetch_recent_articles(hours=24, limit=120)
    if not items:
        print("No recent articles found in the last 24 hours.")
        return

    payload = render.build_prompt_payload(items)
    run_date = datetime.now(timezone.utc).date().isoformat()
    template = Path("templates/exec_digest_template.html").read_text(encoding="utf-8")

    chatgpt = render.enrich_output(
        payload,
        render.generate_with_openai(payload, config, run_date),
    )

    linkedin = render.build_linkedin_payload(chatgpt, run_date)
    html = render.render_html(template, linkedin, run_date=run_date)
    out_path = Path("output") / f"digest_{run_date}_linkedin.html"
    render.rotate_existing(out_path)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
