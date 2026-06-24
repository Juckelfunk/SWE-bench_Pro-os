#!/usr/bin/env python3
"""Clone public benchmark repositories and audit their base commits."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

try:
    from analysis.patch_application_checker import repo_storage_name
except ModuleNotFoundError:  # Support direct script execution.
    from patch_application_checker import repo_storage_name


def load_repositories(dataset_path: Path) -> dict[str, set[str]]:
    # Group base commits by repository to avoid cloning the same origin repeatedly.
    repositories: dict[str, set[str]] = defaultdict(set)
    with dataset_path.open(encoding="utf-8") as dataset_file:
        for line in dataset_file:
            row = json.loads(line)
            repositories[row["repo"]].add(row["base_commit"])
    return dict(repositories)


def run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def prepare_repository(repo: str, commits: set[str], repos_root: Path) -> dict:
    # Store each upstream as a bare mirror-like cache keyed by its benchmark repo name.
    repo_path = repos_root / repo_storage_name(repo)
    clone_url = f"https://github.com/{repo}.git"
    if repo_path.exists():
        # Existing bare clones are refreshed so repeated setup runs remain idempotent.
        updated = run_git([f"--git-dir={repo_path}", "fetch", "--all", "--prune"])
        clone_status = "updated" if updated.returncode == 0 else "update_failed"
        clone_error = updated.stderr.strip() if updated.returncode != 0 else ""
    else:
        cloned = run_git(["clone", "--bare", clone_url, str(repo_path)])
        clone_status = "cloned" if cloned.returncode == 0 else "clone_failed"
        clone_error = cloned.stderr.strip() if cloned.returncode != 0 else ""

    missing_commits = []
    if repo_path.exists():
        for commit in sorted(commits):
            result = run_git([f"--git-dir={repo_path}", "cat-file", "-e", f"{commit}^{{commit}}"])
            if result.returncode != 0:
                # Exact SHA fetches recover benchmark commits dropped from advertised branch history.
                fetched = run_git(
                    [f"--git-dir={repo_path}", "fetch", "--no-tags", "origin", commit]
                )
                verified = run_git(
                    [f"--git-dir={repo_path}", "cat-file", "-e", f"{commit}^{{commit}}"]
                )
                if fetched.returncode != 0 or verified.returncode != 0:
                    missing_commits.append(commit)
    else:
        missing_commits = sorted(commits)

    return {
        "repo": repo,
        "path": str(repo_path),
        "clone_status": clone_status,
        "clone_error": clone_error,
        "base_commit_count": len(commits),
        "available_base_commit_count": len(commits) - len(missing_commits),
        "missing_base_commits": missing_commits,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="helper_code/sweap_eval_full_v2.jsonl")
    parser.add_argument("--repos-root", default="analysis/repos")
    parser.add_argument("--manifest", default="analysis/output/repo_availability.json")
    args = parser.parse_args()

    repos_root = Path(args.repos_root)
    repos_root.mkdir(parents=True, exist_ok=True)
    repositories = load_repositories(Path(args.dataset))
    results = []
    for repo, commits in sorted(repositories.items()):
        # Process repositories deterministically so manifest diffs stay easy to review.
        print(f"Preparing {repo} ({len(commits)} base commits)...", flush=True)
        result = prepare_repository(repo, commits, repos_root)
        results.append(result)
        print(
            f"  {result['clone_status']}: "
            f"{result['available_base_commit_count']}/{result['base_commit_count']} commits available",
            flush=True,
        )

    manifest = {
        "dataset": args.dataset,
        "repository_count": len(results),
        "base_commit_count": sum(result["base_commit_count"] for result in results),
        "available_base_commit_count": sum(result["available_base_commit_count"] for result in results),
        "repositories": results,
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # The manifest lets analysis distinguish incomplete setup from patch failures.
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if manifest["available_base_commit_count"] != manifest["base_commit_count"]:
        raise SystemExit("Some benchmark base commits are unavailable; see the manifest")


if __name__ == "__main__":
    main()
