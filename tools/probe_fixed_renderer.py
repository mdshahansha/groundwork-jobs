"""Reproduce the fixed-renderer feasibility probe using synthetic data only.

Run from the source checkout with PYTHONPATH=src and the render extra installed.
Outputs are private-draft examples, not evidence of complete document gates.
"""

import argparse
import json
from pathlib import Path

from jw.rendering import render_private_pdf, write_new_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    directory = Path(args.output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    profile = {"name": "Alex Example", "email": "alex@example.invalid"}
    fixtures = {
        "draft_cv": ["Backend engineer with experience building Python services.",
                     "Example Company | Software Engineer | 2022-2024",
                     "Built and tested HTTP APIs with Python and PostgreSQL.",
                     "Documented operational procedures and reviewed service changes.",
                     "Skills: Python, PostgreSQL, automated testing and technical documentation."],
        "draft_letter": ["Dear hiring team,",
                         "I am interested in your backend engineering role. My work includes building and testing Python services with PostgreSQL.",
                         "At Example Company, I documented operational procedures and reviewed service changes. I would welcome a conversation about your team's needs.",
                         "Thank you for considering my application.", "Alex Example"],
    }
    for kind, texts in fixtures.items():
        pdf, report = render_private_pdf(profile, [{"text": text, "claim_id": f"synthetic_{i}"}
                                                  for i, text in enumerate(texts)], kind)
        path = write_new_pdf(directory / (kind + ".pdf"), pdf)
        print(json.dumps(dict(report, path=path), sort_keys=True))


if __name__ == "__main__":
    main()
