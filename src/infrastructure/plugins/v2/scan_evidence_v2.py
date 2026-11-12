"""Security scan evidence. A caller boolean is not a report."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class ScannerReportV2:
    """One report produced by a configured scanner adapter."""

    verdict: str
    digest: str


def resolve_security_scan_status_v2(report: ScannerReportV2 | None) -> str:
    """Return unknown unless a real report digest is present."""
    if report is None:
        return "unknown"
    if report.verdict == "passed" and report.digest.startswith("sha256:") and len(report.digest) == 71:
        return "passed"
    if report.verdict == "failed" and report.digest.startswith("sha256:"):
        return "failed"
    return "unknown"
