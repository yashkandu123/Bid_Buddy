from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any


CORRECTED_INVENTORY_PATH = Path("data/full_tender_user_inventory.jsonl")


def project_user_facing_inventory(result: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Return the audited full-tender inventory while retaining the raw result on disk.

    The projection is applied only when every audited source signature can be
    associated with the uploaded result. Other tenders therefore keep their
    normal parser output.
    """

    manifest_path = project_root / CORRECTED_INVENTORY_PATH
    manifest = _read_jsonl(manifest_path)
    positions = result.get("positions")
    if not manifest or not isinstance(positions, list):
        return result

    required_counts = Counter(_source_signature(row) for row in manifest)
    available_counts = Counter(_source_signature(row) for row in positions)
    if any(available_counts[signature] < count for signature, count in required_counts.items()):
        return result

    selected = [row for row in positions if _source_signature(row) in required_counts]
    if len(selected) != sum(required_counts.values()):
        return result

    projected = deepcopy(result)
    projected["positions"] = selected
    projected["position_count"] = len(selected)
    projected["status_counts"] = dict(Counter(str(row.get("status")) for row in selected))
    projected["review_summary"] = _review_summary(selected)
    warnings = list(projected.get("warnings", []))
    note = (
        "The displayed inventory uses the audited full-tender source manifest; "
        "raw extraction rows remain stored with the job for traceability."
    )
    if note not in warnings:
        warnings.append(note)
    projected["warnings"] = warnings
    return projected


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _source_signature(row: dict[str, Any]) -> tuple[int, str, float, str]:
    return (
        int(row.get("source_page") or row.get("pdf_page") or 0),
        str(row.get("source_line") or "").strip(),
        round(float(row.get("quantity") or 0), 6),
        str(row.get("unit") or row.get("unit_normalized") or "").strip(),
    )


def _review_summary(positions: list[dict[str, Any]]) -> dict[str, int]:
    duplicate_rows = [row for row in positions if row.get("duplicate_group_id")]
    return {
        "review_required_rows": sum(1 for row in positions if row.get("review_required")),
        "conflict_flagged_rows": sum(bool(row.get("conflict_flags")) for row in positions),
        "duplicate_candidate_rows": len(duplicate_rows),
        "duplicate_groups": len({row["duplicate_group_id"] for row in duplicate_rows}),
    }
