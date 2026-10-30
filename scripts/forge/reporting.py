"""Persist machine-readable outcomes and concise Actions summaries."""

import json
import os
from pathlib import Path


def write_report(path: str | None, results: list[dict]) -> None:
    if path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as handle:
            handle.write('\n| Recipe | Platform | Result |\n|---|---|---|\n')
            for item in results:
                handle.write(f"| {item['recipe']} | {item.get('platform', '')} | {item['status']} |\n")
