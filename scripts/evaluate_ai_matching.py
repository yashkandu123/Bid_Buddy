from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT_ON_DISK = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_ON_DISK) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_ON_DISK))

from src.tender_pricing.ai_matching_experiment import (
    create_provider,
    load_project_env,
    load_jsonl,
    run_experiment,
    run_page_batched_experiment,
    write_json,
)
from src.tender_pricing.data_loading import load_project_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the isolated Phase 5 AI matching experiment.")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--sample",
        type=Path,
        default=Path("outputs/phase2_review_sample.jsonl"),
        help="JSONL review sample with machine values and optional human labels.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/ai_matching_results.json"),
        help="Output JSON file for experiment results.",
    )
    parser.add_argument("--provider", choices=("fake", "openai"), default="fake")
    parser.add_argument("--fake-decision", choices=("accept", "review", "abstain"), default="review")
    parser.add_argument("--max-positions", type=int, default=None)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument(
        "--page-batched",
        action="store_true",
        help="Send positions from the same source page in one structured provider request.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("evaluation/ai_matching_cache"),
        help="Local successful-response cache used by the real page-batched provider.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = (
        args.project_root
        if args.project_root.is_absolute()
        else PROJECT_ROOT_ON_DISK / args.project_root
    ).resolve()
    sample_path = args.sample if args.sample.is_absolute() else project_root / args.sample
    output_path = args.output if args.output.is_absolute() else project_root / args.output

    load_project_env(project_root)
    data = load_project_data(project_root)
    sample_records = load_jsonl(sample_path)
    if args.provider == "openai":
        from src.tender_pricing.ai_matching_experiment import OpenAIResponsesProvider

        cache_dir = args.cache_dir if args.cache_dir.is_absolute() else project_root / args.cache_dir
        provider = OpenAIResponsesProvider(cache_dir=cache_dir)
    else:
        provider = create_provider(args.provider, fake_decision=args.fake_decision)
    runner = run_page_batched_experiment if args.page_batched else run_experiment
    payload = runner(
        sample_records,
        data["catalog"],
        provider,
        max_candidates=args.max_candidates,
        max_positions=args.max_positions,
    )
    write_json(output_path, payload)
    print(f"Wrote {output_path}")
    print(f"records: {payload['record_count']}")
    print(f"evaluation: {payload['evaluation']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
