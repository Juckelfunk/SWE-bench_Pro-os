#!/usr/bin/env python3
"""Compute low-complexity SWE-Bench Pro failure signals."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


SIGNALS = [
    "no_patch",
    "empty_or_tiny_patch",
    "test_failure_available",
    "missing_output",
    "wrong_files_touched",
    "partial_file_overlap",
    "all_gold_files_touched",
    "missing_gold_files",
    "extra_files_touched",
    "generated_patch_too_small",
    "generated_patch_too_large",
    "large_refactor",
    "multi_file_gold_patch",
    "single_file_gold_patch",
    "generated_patch_multi_file",
    "tests_only_patch",
    "docs_only_patch",
]

FIELDNAMES = [
    "run",
    "instance_id",
    "resolved",
    "gold_files",
    "generated_files",
    "gold_loc",
    "generated_loc",
    "overlap_files",
    "missing_gold_file_count",
    "extra_file_count",
    *SIGNALS,
]


# Helper functions

def load_dataset(path: Path) -> dict[str, dict]:
    # The benchmark JSONL is keyed by instance_id for fast lookup per attempt.
    rows = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            rows[row["instance_id"]] = row
    return rows


def load_result_maps(root: Path) -> dict[str, dict[str, bool]]:
    # Official result maps are the only source of truth for resolved/failed labels.
    maps = {}
    if not root.exists():
        return maps
    for result_path in root.glob("*/eval_results.json"):
        with result_path.open(encoding="utf-8") as f:
            maps[result_path.parent.name] = json.load(f)
    return maps


def changed_line_count(text: str) -> int:
    # Count changed diff lines while ignoring file header lines.
    count = 0
    for line in text.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def patch_files(text: str) -> set[str]:
    # Extract changed paths from both git diff headers and ---/+++ file headers.
    files: set[str] = set()
    current_old = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                for raw in parts[2:4]:
                    path = raw[2:] if raw.startswith(("a/", "b/")) else raw
                    if path != "/dev/null":
                        files.add(path)
            current_old = None
        elif line.startswith("--- "):
            current_old = clean_patch_path(line[4:].strip())
        elif line.startswith("+++ "):
            new_path = clean_patch_path(line[4:].strip())
            for path in (current_old, new_path):
                if path and path != "/dev/null":
                    files.add(path)
    return files


def clean_patch_path(path: str) -> str:
    # Normalize diff paths like a/foo.py and b/foo.py to foo.py.
    path = path.split("\t", 1)[0]
    path = path.split(" ", 1)[0]
    return path[2:] if path.startswith(("a/", "b/")) else path


def is_docs_path(path: str) -> bool:
    # Treat common documentation directories and markup files as docs-only.
    lower = path.lower()
    parts = lower.split("/")
    return (
        any(part in {"doc", "docs", "documentation"} for part in parts)
        or lower.startswith("readme")
        or lower.endswith((".md", ".rst", ".asciidoc", ".adoc"))
    )


def output_has_failed_tests(path: Path) -> bool | None:
    # Return None when output is missing or not structured enough to classify.
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    tests = data.get("tests")
    if not isinstance(tests, list):
        return None
    return any(test.get("status") != "PASSED" for test in tests)


def bool_cell(value: bool) -> str:
    return "1" if value else "0"


def build_attempt_facts(attempt_dir: Path, dataset_row: dict) -> dict:
    # Build all reusable facts before running individual signal checks.
    gold_patch = dataset_row.get("patch") or ""
    test_patch = dataset_row.get("test_patch") or ""
    gold_files = patch_files(gold_patch)
    test_files = patch_files(test_patch)
    gold_loc = changed_line_count(gold_patch)

    patch_path = attempt_dir / "_patch.diff"
    output_path = attempt_dir / "_output.json"
    generated_patch = patch_path.read_text(encoding="utf-8", errors="replace") if patch_path.exists() else ""
    generated_files = patch_files(generated_patch)
    generated_loc = changed_line_count(generated_patch)
    overlap = gold_files & generated_files
    missing_gold = gold_files - generated_files
    extra_files = generated_files - gold_files

    return {
        "patch_path": patch_path,
        "gold_files": gold_files,
        "test_files": test_files,
        "generated_files": generated_files,
        "gold_loc": gold_loc,
        "generated_loc": generated_loc,
        "overlap": overlap,
        "missing_gold": missing_gold,
        "extra_files": extra_files,
        "failed_tests": output_has_failed_tests(output_path),
    }


# Signal detection functions

def detect_patch_presence_signals(facts: dict) -> dict[str, bool]:
    # Patch-presence signals do not need gold-patch comparison.
    no_patch = not facts["patch_path"].exists()
    return {
        "no_patch": no_patch,
        "empty_or_tiny_patch": (not no_patch) and facts["generated_loc"] < 10,
    }


def detect_eval_output_signals(facts: dict) -> dict[str, bool]:
    # Eval output is used only for observable test-failure signals.
    return {
        "test_failure_available": facts["failed_tests"] is True,
        "missing_output": facts["failed_tests"] is None,
    }


def detect_file_overlap_signals(facts: dict) -> dict[str, bool]:
    # These signals compare generated paths against reference patch paths.
    gold_files = facts["gold_files"]
    generated_files = facts["generated_files"]
    overlap = facts["overlap"]
    return {
        "wrong_files_touched": bool(generated_files) and not overlap,
        "partial_file_overlap": bool(overlap) and overlap != gold_files,
        "all_gold_files_touched": bool(gold_files) and gold_files <= generated_files,
        "missing_gold_files": bool(facts["missing_gold"]),
        "extra_files_touched": bool(facts["extra_files"]),
    }


def detect_patch_size_signals(facts: dict) -> dict[str, bool]:
    # Size thresholds mirror the report heuristics and remain configurable later.
    gold_loc = facts["gold_loc"]
    generated_loc = facts["generated_loc"]
    gold_files = facts["gold_files"]
    generated_files = facts["generated_files"]
    return {
        "generated_patch_too_small": gold_loc >= 20 and generated_loc < max(10, int(0.25 * gold_loc)),
        "generated_patch_too_large": generated_loc > max(50, 3 * gold_loc),
        "large_refactor": (
            len(generated_files) > max(2 * len(gold_files), len(gold_files) + 5)
            or generated_loc > max(500, 4 * gold_loc)
        ),
    }


def detect_file_type_signals(facts: dict) -> dict[str, bool]:
    # test_patch gives benchmark-specific test files; docs remain path-based.
    generated_files = facts["generated_files"]
    test_files = facts["test_files"]
    return {
        "multi_file_gold_patch": len(facts["gold_files"]) > 1,
        "single_file_gold_patch": len(facts["gold_files"]) == 1,
        "generated_patch_multi_file": len(generated_files) > 1,
        "tests_only_patch": bool(generated_files) and bool(test_files) and generated_files <= test_files,
        "docs_only_patch": bool(generated_files) and all(is_docs_path(path) for path in generated_files),
    }


def detect_signals(facts: dict) -> dict[str, bool]:
    # Keep signal groups small so new detectors can be added safely.
    signals = {}
    signals.update(detect_patch_presence_signals(facts))
    signals.update(detect_eval_output_signals(facts))
    signals.update(detect_file_overlap_signals(facts))
    signals.update(detect_patch_size_signals(facts))
    signals.update(detect_file_type_signals(facts))
    return signals


# General functions

def analyze_attempt(
    run: str,
    instance_id: str,
    attempt_dir: Path,
    dataset_row: dict,
    result_map: dict[str, bool] | None,
) -> dict[str, str]:
    # Compare the reference patch and generated patch using simple path/LOC facts.
    facts = build_attempt_facts(attempt_dir, dataset_row)
    signals = detect_signals(facts)

    # Eval output is a signal source, but only official maps label success/failure.
    resolved = result_map.get(instance_id) if result_map and instance_id in result_map else None

    row = {
        "run": run,
        "instance_id": instance_id,
        "resolved": "" if resolved is None else bool_cell(bool(resolved)),
        "gold_files": str(len(facts["gold_files"])),
        "generated_files": str(len(facts["generated_files"])),
        "gold_loc": str(facts["gold_loc"]),
        "generated_loc": str(facts["generated_loc"]),
        "overlap_files": str(len(facts["overlap"])),
        "missing_gold_file_count": str(len(facts["missing_gold"])),
        "extra_file_count": str(len(facts["extra_files"])),
    }
    row.update({signal: bool_cell(value) for signal, value in signals.items()})
    return row


def iter_attempt_dirs(eval_root: Path):
    # The S3 eval-only sync layout is <root>/<run>/eval/<instance_id>/.
    for eval_dir in sorted(eval_root.glob("*/eval")):
        run = eval_dir.parent.name
        for attempt_dir in sorted(path for path in eval_dir.iterdir() if path.is_dir()):
            yield run, attempt_dir.name, attempt_dir


def write_summary(rows: list[dict[str, str]], path: Path) -> None:
    # Summaries report how often each signal appears and how often it fails.
    total = len(rows)
    resolved_known = [row for row in rows if row["resolved"] != ""]
    failed = [row for row in resolved_known if row["resolved"] == "0"]
    with path.open("w", encoding="utf-8") as f:
        f.write(f"attempts,{total}\n")
        f.write(f"attempts_with_result,{len(resolved_known)}\n")
        f.write(f"failed_attempts,{len(failed)}\n")
        f.write("signal,attempts,failed_attempts,failure_rate\n")
        for signal in SIGNALS:
            present = [row for row in resolved_known if row[signal] == "1"]
            present_failed = [row for row in present if row["resolved"] == "0"]
            rate = "" if not present else f"{len(present_failed) / len(present):.4f}"
            f.write(f"{signal},{len(present)},{len(present_failed)},{rate}\n")


def main() -> None:
    # Defaults match the repository layout used by the S3 download helper.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="helper_code/sweap_eval_full_v2.jsonl")
    parser.add_argument("--eval-root", default="traj_s3/eval_only")
    parser.add_argument("--results-root", default="traj")
    parser.add_argument("--out", default="analysis/failure_signals.csv")
    parser.add_argument("--summary-out", default="analysis/failure_signal_summary.csv")
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset))
    result_maps = load_result_maps(Path(args.results_root))
    rows = []
    # Skip attempts whose instance_id is not in the public benchmark JSONL.
    for run, instance_id, attempt_dir in iter_attempt_dirs(Path(args.eval_root)):
        if instance_id not in dataset:
            continue
        rows.append(analyze_attempt(run, instance_id, attempt_dir, dataset[instance_id], result_maps.get(run)))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    write_summary(rows, Path(args.summary_out))


if __name__ == "__main__":
    main()
