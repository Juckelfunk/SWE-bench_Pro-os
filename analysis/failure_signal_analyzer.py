#!/usr/bin/env python3
"""Compute mechanical SWE-Bench Pro failure signals."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path

try:
    from analysis.patch_application_checker import GitApplyChecker
except ModuleNotFoundError:  # Support `python analysis/failure_signal_analyzer.py`.
    from patch_application_checker import GitApplyChecker


SIGNALS = [
    "no_patch",
    "empty_or_tiny_patch",
    "patch_application_or_editing_failure",
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
    "syntax_or_parse_error",
    "production_code_not_touched",
    "generated_or_vendor_churn",
    "required_test_target_still_failing",
    "regression_test_failed",
    "new_tests_not_exercised_or_missing_output",
    "trajectory_no_submission",
    "trajectory_tool_error",
    "trajectory_timeout_or_turn_limit",
    "eval_passed_but_result_false_mismatch",
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
    "failed_fail_to_pass_count",
    "failed_pass_to_pass_count",
    "patch_application_check_available",
    "patch_application_error_type",
    "trajectory_available",
    "trajectory_tool_error_count",
    *SIGNALS,
]

SYNTAX_ERROR_PATTERNS = [
    "syntaxerror",
    "parseerror",
    "compilation failed",
    "compile error",
    "cannot compile",
    "importerror",
    "module not found",
    "ts2304",
    "ts2322",
    "ts2339",
    "error: cannot find symbol",
    "undefined reference",
]

TOOL_ERROR_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bcommand failed\b",
        r"\bcommand timed out\b",
        r"\b(?:process|command) (?:exited|returned) with (?:exit )?code [1-9]\d*\b",
        r"\bnon[- ]zero exit(?: code| status)?\b",
        r"\bno such file or directory\b",
        r"\bfile not found\b",
        r"\bpermission denied\b",
        r"\btool (?:call |invocation )?(?:error|failed)\b",
        r"\binvalid tool (?:call|arguments?)\b",
    )
]

TERMINATION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:cost|token|time|turn|step) limit\b",
        r"\b(?:cost|token|time|turn|step) budget\b",
        r"\bmax(?:imum)?[ _-]?(?:turns?|steps?|tokens?)\b",
        r"\bcontext window\b",
        r"\bcommand timeouts?\b",
        r"\btimed out\b",
        r"\btimeout\b",
    )
]

##########################################
# Helper functions
##########################################

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
    # This is a cheap patch-size proxy, not a semantic measure of effort.
    count = 0
    for line in text.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def patch_files(text: str) -> set[str]:
    # Extract changed paths from both git diff headers and ---/+++ file headers.
    # Supporting both forms keeps parsing robust for slightly different diff emitters.
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


def normalize_test_name(name: str) -> str:
    # Test names are compared after whitespace normalization only.
    return " ".join(str(name).split())


def normalize_dataset_tests(value: object) -> set[str]:
    # Dataset test fields are expected to be lists, but tolerate strings.
    # Empty or malformed fields become an empty set so detectors stay conservative.
    if isinstance(value, list):
        return {normalize_test_name(item) for item in value if normalize_test_name(item)}
    if isinstance(value, str) and value.strip():
        return {normalize_test_name(value)}
    return set()


def is_docs_path(path: str) -> bool:
    # Treat common documentation directories and markup files as docs-only.
    # This rule is intentionally simple because docs-only is a low-risk path type.
    lower = path.lower()
    parts = lower.split("/")
    return (
        any(part in {"doc", "docs", "documentation"} for part in parts)
        or lower.startswith("readme")
        or lower.endswith((".md", ".rst", ".asciidoc", ".adoc"))
    )


def is_obvious_test_path(path: str) -> bool:
    # Generic test path rules are used only for broad non-production checks.
    # tests_only_patch does not use this helper; it relies only on benchmark test_patch.
    lower = path.lower()
    parts = lower.split("/")
    name = parts[-1]
    return (
        any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts)
        or name.startswith(("test_", "spec_"))
        or name.endswith(("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"))
    )


def is_generated_or_vendor_path(path: str) -> bool:
    # Generated/vendor rules flag files that are usually not hand-authored fixes.
    # A hit here is evidence of churn, not proof that the generated patch is wrong.
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    parts = lower.split("/")
    return (
        any(part in {"vendor", "vendors", "node_modules", "dist", "build", "coverage", "generated", "gen"} for part in parts)
        or name.endswith((".min.js", ".min.css", ".snap", ".lock"))
        or "generated" in name
    )


def is_non_production_path(path: str, test_files: set[str]) -> bool:
    # Non-production is intentionally limited to tests, docs, and generated/vendor files.
    # Config/build files are excluded until repo-specific rules exist.
    return (
        path in test_files
        or is_obvious_test_path(path)
        or is_docs_path(path)
        or is_generated_or_vendor_path(path)
    )


def load_output_facts(path: Path) -> dict:
    # Return structured test facts and raw text for conservative log-pattern signals.
    # failed_tests=None means "missing or unparseable", not "all tests passed".
    facts = {
        "failed_tests": None,
        "failed_test_names": set(),
        "seen_test_names": set(),
        "output_text": "",
    }
    if not path.exists():
        return facts
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError):
        return facts
    facts["output_text"] = text
    tests = data.get("tests")
    if not isinstance(tests, list):
        return facts

    # Status comparison is strict: anything other than PASSED is a failing test.
    for test in tests:
        name = normalize_test_name(test.get("name", ""))
        if not name:
            continue
        facts["seen_test_names"].add(name)
        if test.get("status") != "PASSED":
            facts["failed_test_names"].add(name)
    facts["failed_tests"] = bool(facts["failed_test_names"])
    return facts


def read_attempt_text(attempt_dir: Path, output_text: str) -> str:
    # Logs are optional; include them when present for syntax/import detection.
    # The analyzer only reads sibling .log files and does not require trajectory data.
    chunks = [output_text]
    for path in sorted(attempt_dir.glob("*.log")):
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def find_trajectory_path(root: Path, run: str, instance_id: str) -> Path | None:
    # SWE-Agent stores one JSON .traj file below <root>/<run>/traj/<instance_id>/.
    trajectory_dir = root / run / "traj" / instance_id
    candidates = sorted(trajectory_dir.glob("*.traj"))
    return candidates[0] if candidates else None


def load_trajectory_facts(path: Path | None) -> dict:
    # Missing or malformed trajectories provide no evidence and must not become failures.
    facts = {
        "trajectory_available": False,
        "trajectory_submitted": False,
        "trajectory_tool_error_count": 0,
        "trajectory_timeout_or_turn_limit": False,
    }
    if path is None:
        return facts
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return facts
    if not isinstance(data, dict) or not isinstance(data.get("trajectory"), list):
        return facts

    facts["trajectory_available"] = True
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    exit_status = str(info.get("exit_status") or "").strip().lower()
    steps = [step for step in data["trajectory"] if isinstance(step, dict)]

    # A recorded submission is stronger evidence than requiring an explicit final action:
    # SWE-Agent may autosubmit after a budget or environment termination.
    facts["trajectory_submitted"] = bool(info.get("submission")) or exit_status.startswith("submitted")
    if not facts["trajectory_submitted"]:
        facts["trajectory_submitted"] = any(
            str(step.get("action") or "").strip().lower().split(maxsplit=1)[0:1] == ["submit"]
            for step in steps
        )

    error_steps = 0
    for step in steps:
        # Observations are command/tool results. Thoughts and responses often quote issue
        # text or source code and would create many false positives.
        if not str(step.get("action") or "").strip():
            continue
        observation = str(step.get("observation") or "")
        if any(pattern.search(observation) for pattern in TOOL_ERROR_PATTERNS):
            error_steps += 1
    if any(marker in exit_status for marker in ("exit_error", "exit_format", "exit_command_timeout")):
        error_steps += 1
    facts["trajectory_tool_error_count"] = error_steps

    termination_text = " ".join(
        [exit_status]
        + [
            str(step.get(field) or "")
            for step in steps[-1:]
            for field in ("response", "thought", "observation")
        ]
    )
    facts["trajectory_timeout_or_turn_limit"] = (
        any(marker in exit_status for marker in ("exit_cost", "exit_context", "exit_command_timeout"))
        or any(pattern.search(termination_text) for pattern in TERMINATION_PATTERNS)
    )
    return facts


def bool_cell(value: bool) -> str:
    return "1" if value else "0"


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def print_progress(completed: int, total: int, started_at: float) -> None:
    elapsed = time.monotonic() - started_at
    remaining = (elapsed / completed) * (total - completed) if completed else 0
    percent = (completed / total) * 100 if total else 100
    print(
        f"[{completed}/{total}] {percent:5.1f}% | "
        f"elapsed {format_duration(elapsed)} | ETA {format_duration(remaining)}",
        flush=True,
    )


def build_attempt_facts(
    attempt_dir: Path,
    dataset_row: dict,
    trajectory_path: Path | None = None,
    apply_checker: GitApplyChecker | None = None,
) -> dict:
    # Build all reusable facts before running individual signal checks.
    # Facts are deliberately mechanical so detector functions remain small and auditable.
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
    output_facts = load_output_facts(output_path)
    trajectory_facts = load_trajectory_facts(trajectory_path)
    application_facts = (
        apply_checker.check(dataset_row, patch_path.exists(), generated_patch)
        if apply_checker
        else {
            "patch_application_check_available": False,
            "patch_application_failed": False,
            "patch_application_error_type": "check_not_configured",
        }
    )
    # File overlap is computed against the gold patch, not against issue text guesses.
    overlap = gold_files & generated_files
    missing_gold = gold_files - generated_files
    extra_files = generated_files - gold_files
    # FAIL_TO_PASS are target tests; PASS_TO_PASS are regression guards.
    fail_to_pass = normalize_dataset_tests(dataset_row.get("FAIL_TO_PASS"))
    pass_to_pass = normalize_dataset_tests(dataset_row.get("PASS_TO_PASS"))
    # Exact normalized intersections avoid fuzzy matching false positives.
    failed_fail_to_pass = fail_to_pass & output_facts["failed_test_names"]
    failed_pass_to_pass = pass_to_pass & output_facts["failed_test_names"]

    facts = {
        "patch_path": patch_path,
        "output_path": output_path,
        "gold_files": gold_files,
        "test_files": test_files,
        "generated_files": generated_files,
        "gold_loc": gold_loc,
        "generated_loc": generated_loc,
        "overlap": overlap,
        "missing_gold": missing_gold,
        "extra_files": extra_files,
        "failed_tests": output_facts["failed_tests"],
        "seen_test_names": output_facts["seen_test_names"],
        "failed_test_names": output_facts["failed_test_names"],
        "attempt_text": read_attempt_text(attempt_dir, output_facts["output_text"]),
        "fail_to_pass": fail_to_pass,
        "pass_to_pass": pass_to_pass,
        "failed_fail_to_pass": failed_fail_to_pass,
        "failed_pass_to_pass": failed_pass_to_pass,
    }
    facts.update(trajectory_facts)
    facts.update(application_facts)
    return facts


##########################################
# Signal detection functions
##########################################

def detect_patch_presence_signals(facts: dict) -> dict[str, bool]:
    # Patch-presence signals do not need gold-patch comparison.
    no_patch = not facts["patch_path"].exists()
    return {
        # no_patch means the artifact is absent in the eval directory.
        "no_patch": no_patch,
        # empty_or_tiny_patch fires for any present patch below 10 changed lines.
        "empty_or_tiny_patch": (not no_patch) and facts["generated_loc"] < 10,
        # Only definitive parser/index failures emit this signal; infrastructure gaps remain unavailable.
        "patch_application_or_editing_failure": (
            facts["patch_application_check_available"] and facts["patch_application_failed"]
        ),
    }


def detect_eval_output_signals(facts: dict) -> dict[str, bool]:
    # Eval output is used only for observable test-failure signals.
    lower_text = facts["attempt_text"].lower()
    return {
        # test_failure_available fires when structured output has at least one non-PASSED test.
        "test_failure_available": facts["failed_tests"] is True,
        # missing_output covers absent or unstructured output, not just missing files.
        "missing_output": facts["failed_tests"] is None,
        # syntax_or_parse_error uses conservative text markers from output/log files.
        "syntax_or_parse_error": any(pattern in lower_text for pattern in SYNTAX_ERROR_PATTERNS),
    }


def detect_file_overlap_signals(facts: dict) -> dict[str, bool]:
    # These signals compare generated paths against reference patch paths.
    gold_files = facts["gold_files"]
    generated_files = facts["generated_files"]
    overlap = facts["overlap"]
    return {
        # wrong_files_touched means generated files exist but none are in the gold patch.
        "wrong_files_touched": bool(generated_files) and not overlap,
        # partial_file_overlap means the patch found some gold files but missed others.
        "partial_file_overlap": bool(overlap) and overlap != gold_files,
        # all_gold_files_touched is a coverage signal and can appear on passing or failing attempts.
        "all_gold_files_touched": bool(gold_files) and gold_files <= generated_files,
        # missing_gold_files is the broad deterministic "gold file absent" signal.
        "missing_gold_files": bool(facts["missing_gold"]),
        # extra_files_touched captures generated changes outside the gold file set.
        "extra_files_touched": bool(facts["extra_files"]),
    }


def detect_patch_size_signals(facts: dict) -> dict[str, bool]:
    # Size thresholds mirror the report heuristics and remain configurable later.
    gold_loc = facts["gold_loc"]
    generated_loc = facts["generated_loc"]
    gold_files = facts["gold_files"]
    generated_files = facts["generated_files"]
    return {
        # Too-small patches are only flagged when the gold patch is large enough to compare.
        "generated_patch_too_small": gold_loc >= 20 and generated_loc < max(10, int(0.25 * gold_loc)),
        # Too-large patches use both a ratio threshold and an absolute minimum.
        "generated_patch_too_large": generated_loc > max(50, 3 * gold_loc),
        # large_refactor catches broad file churn or very large LOC churn.
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
        # multi_file_gold_patch describes task shape, not generated patch behavior.
        "multi_file_gold_patch": len(facts["gold_files"]) > 1,
        # single_file_gold_patch is useful for separating simple-looking gold patches.
        "single_file_gold_patch": len(facts["gold_files"]) == 1,
        # generated_patch_multi_file describes how broad the generated edit is.
        "generated_patch_multi_file": len(generated_files) > 1,
        # tests_only_patch is strict: generated files must be a subset of benchmark test_patch files.
        "tests_only_patch": bool(generated_files) and bool(test_files) and generated_files <= test_files,
        # docs_only_patch fires only when every generated file is classified as documentation.
        "docs_only_patch": bool(generated_files) and all(is_docs_path(path) for path in generated_files),
        # production_code_not_touched is broader and allows obvious test/docs/generated/vendor paths.
        "production_code_not_touched": bool(generated_files) and all(is_non_production_path(path, test_files) for path in generated_files),
        # generated_or_vendor_churn fires on any likely generated/vendor/lockfile path.
        "generated_or_vendor_churn": bool(generated_files) and any(is_generated_or_vendor_path(path) for path in generated_files),
    }


def detect_test_target_signals(facts: dict) -> dict[str, bool]:
    # FAIL_TO_PASS/PASS_TO_PASS names come from the benchmark row and are matched exactly after normalization.
    output_missing = facts["failed_tests"] is None
    target_tests = facts["fail_to_pass"]
    seen_target_tests = target_tests & facts["seen_test_names"]
    return {
        # required_test_target_still_failing means a benchmark target test remains red.
        "required_test_target_still_failing": bool(facts["failed_fail_to_pass"]),
        # regression_test_failed means a benchmark guard test regressed.
        "regression_test_failed": bool(facts["failed_pass_to_pass"]),
        # new_tests_not_exercised_or_missing_output means target-test evidence is absent.
        "new_tests_not_exercised_or_missing_output": bool(target_tests) and (output_missing or not seen_target_tests),
    }


def detect_trajectory_signals(facts: dict) -> dict[str, bool]:
    # Trajectory absence is an artifact gap, not proof of agent behavior.
    available = facts["trajectory_available"]
    return {
        "trajectory_no_submission": available and not facts["trajectory_submitted"],
        "trajectory_tool_error": available and facts["trajectory_tool_error_count"] > 0,
        "trajectory_timeout_or_turn_limit": available and facts["trajectory_timeout_or_turn_limit"],
    }


def detect_result_mismatch_signals(facts: dict) -> dict[str, bool]:
    # This narrow mismatch catches passed-looking output marked unresolved officially.
    resolved = facts.get("resolved")
    failed_tests = facts["failed_tests"]
    return {
        # This does not flag resolved=True with failed output; it only tracks false negatives.
        "eval_passed_but_result_false_mismatch": (
            resolved is not None
            and failed_tests is not None
            and not bool(resolved)
            and not failed_tests
        ),
    }


def detect_signals(facts: dict) -> dict[str, bool]:
    # Keep signal groups small so new detectors can be added safely.
    signals = {}
    signals.update(detect_patch_presence_signals(facts))
    signals.update(detect_eval_output_signals(facts))
    signals.update(detect_file_overlap_signals(facts))
    signals.update(detect_patch_size_signals(facts))
    signals.update(detect_file_type_signals(facts))
    signals.update(detect_test_target_signals(facts))
    signals.update(detect_trajectory_signals(facts))
    signals.update(detect_result_mismatch_signals(facts))
    return signals


# General functions

def analyze_attempt(
    run: str,
    instance_id: str,
    attempt_dir: Path,
    dataset_row: dict,
    result_map: dict[str, bool] | None,
    trajectory_path: Path | None = None,
    apply_checker: GitApplyChecker | None = None,
) -> dict[str, str]:
    # Compare the reference patch and generated patch using simple path/LOC facts.
    facts = build_attempt_facts(attempt_dir, dataset_row, trajectory_path, apply_checker)

    # Eval output is a signal source, but only official maps label success/failure.
    resolved = result_map.get(instance_id) if result_map and instance_id in result_map else None
    # resolved=None means this attempt is included in detail output but excluded from failure rates.
    facts["resolved"] = resolved
    signals = detect_signals(facts)

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
        "failed_fail_to_pass_count": str(len(facts["failed_fail_to_pass"])),
        "failed_pass_to_pass_count": str(len(facts["failed_pass_to_pass"])),
        "patch_application_check_available": bool_cell(facts["patch_application_check_available"]),
        "patch_application_error_type": facts["patch_application_error_type"],
        "trajectory_available": bool_cell(facts["trajectory_available"]),
        "trajectory_tool_error_count": str(facts["trajectory_tool_error_count"]),
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
    parser.add_argument(
        "--trajectory-root",
        default=None,
        help="Root containing <run>/traj/<instance_id> (defaults to --eval-root)",
    )
    parser.add_argument(
        "--repos-root",
        default="analysis/repos",
        help="Root containing bare owner__repo.git clones for patch application checks",
    )
    parser.add_argument(
        "--skip-trajectory-signals",
        action="store_true",
        help="Skip loading trajectories and emit no trajectory-based signals",
    )
    parser.add_argument(
        "--skip-repo-checks",
        action="store_true",
        help="Skip repository-backed patch application checks",
    )
    parser.add_argument("--out", default="analysis/failure_signals.csv")
    parser.add_argument("--summary-out", default="analysis/failure_signal_summary.csv")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Print progress every N attempts; use 0 to disable",
    )
    args = parser.parse_args()

    if args.progress_every < 0:
        parser.error("--progress-every must be zero or greater")

    dataset = load_dataset(Path(args.dataset))
    result_maps = load_result_maps(Path(args.results_root))
    trajectory_root = Path(args.trajectory_root) if args.trajectory_root else Path(args.eval_root)
    apply_checker = None if args.skip_repo_checks else GitApplyChecker(Path(args.repos_root))
    attempts = list(iter_attempt_dirs(Path(args.eval_root)))
    run_counts: dict[str, int] = {}
    for run, _instance_id, _attempt_dir in attempts:
        run_counts[run] = run_counts.get(run, 0) + 1

    rows = []
    started_at = time.monotonic()
    print(f"Analyzing {len(attempts)} attempts across {len(run_counts)} runs...", flush=True)
    if args.skip_trajectory_signals:
        print("Trajectory signals: skipped", flush=True)
    if args.skip_repo_checks:
        print("Repository-backed checks: skipped", flush=True)
    current_run = None
    run_number = 0
    # Skip attempts whose instance_id is not in the public benchmark JSONL.
    for attempt_number, (run, instance_id, attempt_dir) in enumerate(attempts, start=1):
        if run != current_run:
            current_run = run
            run_number += 1
            print(
                f"Run {run_number}/{len(run_counts)}: {run} ({run_counts[run]} attempts)",
                flush=True,
            )
        if instance_id not in dataset:
            if args.progress_every and (
                attempt_number % args.progress_every == 0 or attempt_number == len(attempts)
            ):
                print_progress(attempt_number, len(attempts), started_at)
            continue
        trajectory_path = (
            None
            if args.skip_trajectory_signals
            else find_trajectory_path(trajectory_root, run, instance_id)
        )
        rows.append(
            analyze_attempt(
                run,
                instance_id,
                attempt_dir,
                dataset[instance_id],
                result_maps.get(run),
                trajectory_path,
                apply_checker,
            )
        )
        if args.progress_every and (
            attempt_number % args.progress_every == 0 or attempt_number == len(attempts)
        ):
            print_progress(attempt_number, len(attempts), started_at)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    write_summary(rows, Path(args.summary_out))
    print(
        f"Completed {len(rows)} analyzed attempts in "
        f"{format_duration(time.monotonic() - started_at)}.",
        flush=True,
    )
    print(f"Detailed output: {out_path}", flush=True)
    print(f"Summary output: {args.summary_out}", flush=True)


if __name__ == "__main__":
    main()
