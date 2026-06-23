#!/usr/bin/env python3
"""Compute mechanical SWE-Bench Pro failure signals."""

from __future__ import annotations

import argparse
import csv
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

try:
    from analysis.failure_signal_detection import FIELDNAMES, SIGNALS, analyze_attempt
    from analysis.patch_application_checker import GitApplyChecker
except ModuleNotFoundError:  # Support `python analysis/failure_signal_analyzer.py`.
    from failure_signal_detection import FIELDNAMES, SIGNALS, analyze_attempt
    from patch_application_checker import GitApplyChecker


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
    # Return shape:
    #   {
    #     "<run-name>": {
    #       "<instance-id>": True,   # official result marks this attempt resolved
    #       "<instance-id>": False,  # official result marks this attempt unresolved
    #     }
    #   }
    maps = {}
    if not root.exists():
        return maps

    for result_path in root.glob("*/eval_results.json"):
        with result_path.open(encoding="utf-8") as f:
            maps[result_path.parent.name] = json.load(f)

    return maps


def find_trajectory_path(root: Path, run: str, instance_id: str) -> Path | None:
    # SWE-Agent stores one JSON .traj file below <root>/<run>/traj/<instance_id>/.
    trajectory_dir = root / run / "traj" / instance_id
    candidates = sorted(trajectory_dir.glob("*.traj"))
    return candidates[0] if candidates else None


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def print_progress(completed: int, total: int, started_at: float) -> None:
    elapsed = time.monotonic() - started_at
    percent = (completed / total) * 100 if total else 100
    print(
        f"[{completed}/{total}] {percent:5.1f}% | "
        f"elapsed {format_duration(elapsed)}",
        flush=True,
    )


_WORKER_DATASET = {}
_WORKER_RESULT_MAPS = {}
_WORKER_TRAJECTORY_ROOT = None
_WORKER_APPLY_CHECKER = None


def initialize_worker(
    dataset: dict,
    result_maps: dict,
    trajectory_root: str | None,
    repos_root: str | None,
) -> None:
    global _WORKER_DATASET, _WORKER_RESULT_MAPS, _WORKER_TRAJECTORY_ROOT, _WORKER_APPLY_CHECKER
    _WORKER_DATASET = dataset
    _WORKER_RESULT_MAPS = result_maps
    _WORKER_TRAJECTORY_ROOT = Path(trajectory_root) if trajectory_root else None
    _WORKER_APPLY_CHECKER = GitApplyChecker(Path(repos_root)) if repos_root else None


def analyze_attempt_worker(job: tuple[str, str, Path]) -> dict[str, str]:
    run, instance_id, attempt_dir = job
    trajectory_path = (
        find_trajectory_path(_WORKER_TRAJECTORY_ROOT, run, instance_id)
        if _WORKER_TRAJECTORY_ROOT
        else None
    )
    return analyze_attempt(
        run,
        instance_id,
        attempt_dir,
        _WORKER_DATASET[instance_id],
        _WORKER_RESULT_MAPS.get(run),
        trajectory_path,
        _WORKER_APPLY_CHECKER,
    )


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
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel attempt workers",
    )
    args = parser.parse_args()

    if args.progress_every < 0:
        parser.error("--progress-every must be zero or greater")
    if args.workers < 1:
        parser.error("--workers must be one or greater")

    dataset = load_dataset(Path(args.dataset))
    result_maps = load_result_maps(Path(args.results_root))
    trajectory_root = Path(args.trajectory_root) if args.trajectory_root else Path(args.eval_root)
    attempts = list(iter_attempt_dirs(Path(args.eval_root)))
    jobs = [attempt for attempt in attempts if attempt[1] in dataset]
    run_counts: dict[str, int] = {}
    for run, _instance_id, _attempt_dir in jobs:
        run_counts[run] = run_counts.get(run, 0) + 1

    rows = []
    started_at = time.monotonic()
    print(f"Analyzing {len(jobs)} attempts across {len(run_counts)} runs...", flush=True)
    print(f"Workers: {args.workers}", flush=True)
    if args.skip_trajectory_signals:
        print("Trajectory signals: skipped", flush=True)
    if args.skip_repo_checks:
        print("Repository-backed checks: skipped", flush=True)
    worker_trajectory_root = None if args.skip_trajectory_signals else str(trajectory_root)
    worker_repos_root = None if args.skip_repo_checks else args.repos_root
    initialize_worker(dataset, result_maps, worker_trajectory_root, worker_repos_root)

    if args.workers == 1:
        result_iterator = map(analyze_attempt_worker, jobs)
        executor = None
    else:
        executor = ProcessPoolExecutor(
            max_workers=args.workers,
            initializer=initialize_worker,
            initargs=(dataset, result_maps, worker_trajectory_root, worker_repos_root),
        )
        result_iterator = executor.map(analyze_attempt_worker, jobs)

    try:
        for attempt_number, row in enumerate(result_iterator, start=1):
            rows.append(row)
            if args.progress_every and (
                attempt_number % args.progress_every == 0 or attempt_number == len(jobs)
            ):
                print_progress(attempt_number, len(jobs), started_at)
    finally:
        if executor:
            executor.shutdown(cancel_futures=True)

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
