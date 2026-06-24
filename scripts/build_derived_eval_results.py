#!/usr/bin/env python3
"""Build eval_results.json files from structured per-attempt output artifacts."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def load_dataset(path: Path) -> dict[str, dict]:
    # The dataset provides FAIL_TO_PASS/PASS_TO_PASS targets for every instance.
    rows = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            rows[row["instance_id"]] = row
    return rows


def load_official_results(root: Path) -> dict[str, dict[str, bool]]:
    # Support both local result maps and the S3 layout with an output/ subdirectory.
    results = {}
    if not root.exists():
        return results
    result_paths = sorted({*root.glob("*/eval_results.json"), *root.glob("*/output/eval_results.json")})
    for path in result_paths:
        with path.open(encoding="utf-8") as f:
            run = path.parent.parent.name if path.parent.name == "output" else path.parent.name
            results[run] = json.load(f)
    return results


def normalized_test_names(value: object) -> set[str]:
    # Benchmark test lists are sometimes native lists and sometimes serialized lists.
    if isinstance(value, list):
        return {" ".join(str(item).split()) for item in value}
    if isinstance(value, str) and value.strip():
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return {" ".join(str(item).split()) for item in parsed}
    return set()


def load_output_tests(path: Path) -> list[dict] | None:
    # Missing or malformed outputs stay unresolved instead of being guessed.
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        output = json.load(f)
    tests = output.get("tests")
    return tests if isinstance(tests, list) else None


def derive_resolved(dataset_row: dict, tests: list[dict]) -> bool:
    # Resolved requires target tests to be observed and no target/guard failures.
    fail_to_pass = normalized_test_names(dataset_row.get("FAIL_TO_PASS", []))
    pass_to_pass = normalized_test_names(dataset_row.get("PASS_TO_PASS", []))
    seen_names = {
        " ".join(str(test.get("name", "")).split())
        for test in tests
        if isinstance(test, dict)
    }
    failed_names = {
        " ".join(str(test.get("name", "")).split())
        for test in tests
        if isinstance(test, dict) and test.get("status") != "PASSED"
    }
    return bool(fail_to_pass) and fail_to_pass <= seen_names and not ((fail_to_pass | pass_to_pass) & failed_names)


def build_results(args: argparse.Namespace) -> dict[str, dict[str, int]]:
    dataset = load_dataset(Path(args.dataset))
    official_results = load_official_results(Path(args.official_results_root))
    eval_root = Path(args.eval_root)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    summaries = {}
    for eval_dir in sorted(eval_root.glob("*/eval")):
        # Each run receives its own eval_results.json so the analyzer can load it unchanged.
        run = eval_dir.parent.name
        official = official_results.get(run, {})
        run_results = {}
        summary = {
            "attempts": 0,
            "official": 0,
            "derived": 0,
            "missing_dataset_row": 0,
            "missing_or_unstructured_output": 0,
            "resolved_true": 0,
            "resolved_false": 0,
        }

        for attempt_dir in sorted(path for path in eval_dir.iterdir() if path.is_dir()):
            instance_id = attempt_dir.name
            summary["attempts"] += 1
            if args.prefer_official and instance_id in official:
                # Preserve official labels whenever we have them.
                resolved = bool(official[instance_id])
                run_results[instance_id] = resolved
                summary["official"] += 1
            else:
                dataset_row = dataset.get(instance_id)
                if dataset_row is None:
                    summary["missing_dataset_row"] += 1
                    continue
                tests = load_output_tests(attempt_dir / "_output.json")
                if tests is None:
                    summary["missing_or_unstructured_output"] += 1
                    continue
                # Derived labels are a conservative proxy, not a replacement for official scoring.
                resolved = derive_resolved(dataset_row, tests)
                run_results[instance_id] = resolved
                summary["derived"] += 1

            if resolved:
                summary["resolved_true"] += 1
            else:
                summary["resolved_false"] += 1

        if run_results:
            run_out_dir = out_root / run
            run_out_dir.mkdir(parents=True, exist_ok=True)
            with (run_out_dir / "eval_results.json").open("w", encoding="utf-8") as f:
                json.dump(run_results, f, indent=2, sort_keys=True)
                f.write("\n")
        summaries[run] = summary

    with (out_root / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=2, sort_keys=True)
        f.write("\n")
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="helper_code/sweap_eval_full_v2.jsonl")
    parser.add_argument("--eval-root", default="traj_s3/all")
    parser.add_argument("--official-results-root", default="traj")
    parser.add_argument("--out-root", default="analysis/output/derived_eval_results")
    parser.add_argument(
        "--prefer-official",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use official labels when present and derive only missing labels.",
    )
    args = parser.parse_args()

    summaries = build_results(args)
    attempts = sum(summary["attempts"] for summary in summaries.values())
    official = sum(summary["official"] for summary in summaries.values())
    derived = sum(summary["derived"] for summary in summaries.values())
    missing = sum(summary["missing_or_unstructured_output"] for summary in summaries.values())
    print(f"Wrote derived eval results for {len(summaries)} runs to {args.out_root}")
    print(f"Attempts: {attempts}")
    print(f"Official labels reused: {official}")
    print(f"Derived labels: {derived}")
    print(f"Missing/unstructured outputs: {missing}")


if __name__ == "__main__":
    main()
