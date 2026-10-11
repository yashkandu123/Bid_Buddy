from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.tender_pricing.user_inventory import (
    CORRECTED_INVENTORY_PATH,
    project_user_facing_inventory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UserFacingInventoryTests(unittest.TestCase):
    def test_versioned_manifest_projects_matching_rows(self) -> None:
        manifest = [
            json.loads(line)
            for line in (PROJECT_ROOT / CORRECTED_INVENTORY_PATH).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        positions = [
            {
                **row,
                "status": "insufficient_information",
                "review_required": True,
                "conflict_flags": [],
            }
            for row in manifest
        ]
        positions.append(
            {
                "lv_id": "RAW-EXTRA",
                "source_page": 1,
                "source_line": "raw extraction row",
                "quantity": 1,
                "unit": "pc",
                "status": "insufficient_information",
            }
        )

        projected = project_user_facing_inventory({"positions": positions}, PROJECT_ROOT)

        self.assertEqual(projected["position_count"], len(manifest))
        self.assertNotIn("RAW-EXTRA", {row["lv_id"] for row in projected["positions"]})

    def test_full_tender_uses_corrected_manifest_without_mutating_raw_result(self) -> None:
        production_path = PROJECT_ROOT / "evaluation/phase2b_full_tender/production_result.json"
        summary_path = PROJECT_ROOT / "evaluation/phase2b_full_tender/evaluation_summary.json"
        if not production_path.exists() or not summary_path.exists():
            self.skipTest("Full-tender evaluation artifacts are unavailable.")

        raw = json.loads(production_path.read_text(encoding="utf-8"))
        expected = json.loads(summary_path.read_text(encoding="utf-8"))["counting"]["corrected_inventory_rows"]
        raw_count = len(raw["positions"])

        projected = project_user_facing_inventory(raw, PROJECT_ROOT)

        self.assertEqual(len(projected["positions"]), expected)
        self.assertEqual(projected["position_count"], expected)
        self.assertEqual(sum(projected["status_counts"].values()), expected)
        self.assertEqual(len(raw["positions"]), raw_count)
        self.assertGreater(raw_count, expected)
        self.assertFalse(any(row.get("record_type") == "component_list_row" for row in projected["positions"]))
        self.assertTrue({row["lv_id"] for row in projected["positions"]}.issubset({row["lv_id"] for row in raw["positions"]}))

    def test_unrelated_tender_is_not_filtered_by_full_tender_manifest(self) -> None:
        result = {
            "positions": [
                {"lv_id": "PDF001-01", "source_page": 1, "source_line": "Valve Stk 1", "quantity": 1, "unit": "pc", "status": "calculated"}
            ],
            "position_count": 1,
            "status_counts": {"calculated": 1},
        }

        self.assertEqual(project_user_facing_inventory(result, PROJECT_ROOT), result)

    def test_manifest_exists_and_contains_unique_user_facing_rows(self) -> None:
        rows = [
            json.loads(line)
            for line in (PROJECT_ROOT / CORRECTED_INVENTORY_PATH).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        self.assertEqual(len(rows), len({row["lv_id"] for row in rows}))
        self.assertFalse(any(row.get("record_type") == "component_list_row" for row in rows))


if __name__ == "__main__":
    unittest.main()
