from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


REQUIRED_FILES = (
    "catalog.csv",
    "productivity.csv",
    "project_parameters.json",
    "example_lv_positions.csv",
    "expected_output_example.json",
)


def find_missing_files(project_root: Path) -> list[str]:
    return [name for name in REQUIRED_FILES if not (project_root / name).exists()]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_project_data(project_root: Path) -> dict[str, Any]:
    missing = find_missing_files(project_root)
    if missing:
        raise FileNotFoundError(f"Missing required input files: {', '.join(missing)}")

    return {
        "catalog": load_csv(project_root / "catalog.csv"),
        "productivity": load_csv(project_root / "productivity.csv"),
        "parameters": load_json(project_root / "project_parameters.json"),
        "examples": load_csv(project_root / "example_lv_positions.csv"),
        "expected": load_json(project_root / "expected_output_example.json"),
    }

