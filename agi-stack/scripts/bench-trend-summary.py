#!/usr/bin/env python3
"""Render the agi-stack bench scorecard as a compact Markdown trend summary."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]


def load_json(path: Path) -> JsonObject:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as error:
        raise ValueError(f"missing JSON report: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON report: {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"JSON report must be an object: {path}")
    return data


def as_object(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.0f}"
        if abs(value) >= 10:
            return f"{value:.2f}"
        return f"{value:.3f}"
    return str(value)


def row_labels(report: JsonObject) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in as_list(report.get("rows")):
        row_object = as_object(row)
        row_id = row_object.get("id")
        label = row_object.get("label")
        if isinstance(row_id, str) and isinstance(label, str):
            labels[row_id] = label
    return labels


def sorted_comparisons(report: JsonObject, limit: int) -> list[JsonObject]:
    comparison = as_object(report.get("baseline_comparison"))
    entries = [as_object(entry) for entry in as_list(comparison.get("comparisons"))]

    def sort_key(entry: JsonObject) -> tuple[int, float]:
        change_pct = entry.get("change_pct")
        comparable_change = change_pct if isinstance(change_pct, (int, float)) else 0.0
        return (1 if entry.get("regression") is True else 0, float(comparable_change))

    return sorted(entries, key=sort_key, reverse=True)[:limit]


def render_summary(report: JsonObject, baseline_path: Path | None, limit: int) -> str:
    summary = as_object(report.get("summary"))
    comparison = as_object(report.get("baseline_comparison"))
    labels = row_labels(report)

    lines = [
        "## agi-stack Bench Scorecard",
        "",
        f"- Recommendation: `{report.get('recommendation', 'unknown')}`",
        f"- Threshold failures: `{format_value(summary.get('fail'))}`",
        f"- Baseline regressions: `{format_value(summary.get('baseline_regressions', 0))}`",
        f"- Total failures: `{format_value(summary.get('total_failures', summary.get('fail')))}`",
    ]

    if comparison.get("enabled") is True:
        lines.extend(
            [
                f"- Baseline: `{baseline_path or 'restored scorecard'}`",
                f"- Compared metrics: `{format_value(comparison.get('compared'))}` at `{format_value(comparison.get('tolerance_pct'))}%` tolerance",
                "",
                "| Row | Metric | Current | Baseline | Allowed | Change | Status |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for entry in sorted_comparisons(report, limit):
            row_id = entry.get("row_id")
            row_label = labels.get(row_id, str(row_id))
            status = "regression" if entry.get("regression") is True else "ok"
            lines.append(
                "| "
                + " | ".join(
                    [
                        row_label,
                        str(entry.get("metric")),
                        format_value(entry.get("current")),
                        format_value(entry.get("baseline")),
                        format_value(entry.get("allowed")),
                        f"{format_value(entry.get('change_pct'))}%",
                        status,
                    ]
                )
                + " |"
            )
    else:
        lines.append("- Baseline: not restored for this run")

    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="current bench scorecard JSON path")
    parser.add_argument("--baseline", type=Path, help="restored baseline scorecard JSON path")
    parser.add_argument(
        "--output",
        type=Path,
        help="Markdown output path; defaults to $GITHUB_STEP_SUMMARY or stdout",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="maximum metric comparisons to include in the trend table",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        return 2

    try:
        report = load_json(args.report)
        rendered = render_summary(report, args.baseline, args.limit)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    output = args.output or (
        Path(summary_path) if (summary_path := os.environ.get("GITHUB_STEP_SUMMARY")) else None
    )
    if output is None:
        print(rendered, end="")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(rendered)
        handle.write("\n")
    print(f"wrote bench trend summary to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
