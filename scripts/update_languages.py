#!/usr/bin/env python3
"""Publish aggregate language percentages without exposing private repositories.

Requires Python 3.9+ and an authenticated GitHub CLI with access to the user's
personal and organization repositories. No tokens or repository names are saved.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
COLORS = {
    "Python": "#3572a5", "Rust": "#dea584", "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a", "Jupyter Notebook": "#da5b0b", "C++": "#f34b7d",
    "C": "#555555", "Shell": "#89e051", "HTML": "#e34c26", "CSS": "#563d7c",
    "Go": "#00add8", "Java": "#b07219", "Ruby": "#701516", "R": "#198ce7",
    "CUDA": "#3a4e3a", "CMake": "#da3434", "Swift": "#f05138",
    "Objective-C": "#438eff", "Other": "#8b949e",
}
FALLBACK_COLORS = ("#a371f7", "#3fb950", "#db61a2", "#d29922", "#39c5cf")


def github_json(endpoint, paginate=False):
    command = ["gh", "api", endpoint]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    for attempt in range(3):
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            value = json.loads(result.stdout)
            if paginate:
                return [item for page in value for item in page]
            return value
        if attempt < 2:
            time.sleep(2 ** attempt)
    # GitHub's error messages may contain private repository names.
    raise RuntimeError("GitHub request failed; check authentication and repository access.")


def collect_languages():
    repositories = github_json(
        "user/repos?visibility=all&affiliation=owner,organization_member&per_page=100",
        paginate=True,
    )
    repositories = {repo["id"]: repo for repo in repositories}.values()
    totals = Counter()
    for index, repo in enumerate(repositories, 1):
        languages = github_json("repos/" + repo["full_name"] + "/languages")
        if not isinstance(languages, dict) or any(
            not isinstance(value, int) or value < 0 for value in languages.values()
        ):
            raise RuntimeError("GitHub returned invalid language data.")
        totals.update(languages)
        if index % 20 == 0:
            print("Scanned {} repositories.".format(index), flush=True)
    if not sum(totals.values()):
        raise RuntimeError("No language data found; previous published stats were preserved.")
    return totals, len(repositories)


def percentages(totals):
    total_bytes = sum(totals.values())
    return [
        {"name": name, "percentage": value / total_bytes * 100}
        for name, value in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
        if value > 0
    ]


def visible_languages(languages):
    if len(languages) <= 10:
        return languages
    return languages[:9] + [{
        "name": "Other",
        "percentage": sum(item["percentage"] for item in languages[9:]),
    }]


def render_card(languages, date, dark=False):
    shown = visible_languages(languages)
    rows = (len(shown) + 1) // 2
    height = 146 + rows * 30
    bg, border, fg, muted = (
        ("#0d1117", "#30363d", "#e6edf3", "#8b949e") if dark else
        ("#ffffff", "#d1d9e0", "#1f2328", "#59636e")
    )
    description = "; ".join(
        "{}: {:.2f}%".format(item["name"], item["percentage"]) for item in shown
    )
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="{}" viewBox="0 0 600 {}" role="img" aria-labelledby="title description">'.format(height, height),
        '<title id="title">Repository languages</title>',
        '<desc id="description">{}; personal and organization repositories, including private repositories and forks. Percentages reflect code size.</desc>'.format(escape(description)),
        '<rect x="0.5" y="0.5" width="599" height="{}" rx="12" fill="{}" stroke="{}"/>'.format(height - 1, bg, border),
        '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif">',
        '<text x="24" y="36" fill="{}" font-size="18" font-weight="600">Repository languages</text>'.format(fg),
        '<text x="24" y="58" fill="{}" font-size="12">Personal + organization repositories · including private repos</text>'.format(muted),
        '<defs><clipPath id="bar"><rect x="24" y="77" width="552" height="12" rx="6"/></clipPath></defs>',
        '<g clip-path="url(#bar)">',
    ]
    x = 24.0
    for index, item in enumerate(shown):
        color = COLORS.get(item["name"], FALLBACK_COLORS[index % len(FALLBACK_COLORS)])
        width = 552 * item["percentage"] / 100
        parts.append('<rect x="{:.4f}" y="77" width="{:.4f}" height="12" fill="{}"/>'.format(x, width, color))
        x += width
    parts.append('</g>')
    for index, item in enumerate(shown):
        column, row = index % 2, index // 2
        x, y = 24 + column * 288, 117 + row * 30
        color = COLORS.get(item["name"], FALLBACK_COLORS[index % len(FALLBACK_COLORS)])
        parts.extend([
            '<circle cx="{}" cy="{}" r="5" fill="{}"/>'.format(x + 5, y - 4, color),
            '<text x="{}" y="{}" fill="{}" font-size="12">{}</text>'.format(x + 18, y, fg, escape(item["name"])),
            '<text x="{}" y="{}" fill="{}" font-size="12" text-anchor="end">{:.2f}%</text>'.format(x + 250, y, muted, item["percentage"]),
        ])
    parts.extend([
        '<text x="24" y="{}" fill="{}" font-size="11">Share of code by size · includes forks · updated {} UTC</text>'.format(height - 19, muted, escape(date)),
        '</g></svg>',
    ])
    return "\n".join(parts) + "\n"


def write_outputs(totals, destination, date):
    languages = percentages(totals)
    if not languages:
        raise RuntimeError("Cannot publish an empty language card.")
    files = {
        "languages.svg": render_card(languages, date),
        "languages-dark.svg": render_card(languages, date, dark=True),
        "languages.json": json.dumps({
            "updated": date,
            "metric": "share_of_language_bytes",
            "scope": "personal_and_organization_repositories_including_private_and_forks",
            "languages": [
                {"name": item["name"], "percentage": round(item["percentage"], 6)}
                for item in languages
            ],
        }, indent=2) + "\n",
    }
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        temporary = destination / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "assets")
    args = parser.parse_args()
    try:
        totals, count = collect_languages()
        date = datetime.now(timezone.utc).date().isoformat()
        write_outputs(totals, args.output, date)
        print("Updated percentages from {} repositories across {} languages.".format(count, len(totals)))
    except subprocess.TimeoutExpired:
        print("GitHub request timed out; previous published stats were preserved.", file=sys.stderr)
        return 1
    except (RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
