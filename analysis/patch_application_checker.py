"""Offline patch-application checks against bare benchmark repositories."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


def strip_binary_hunks(patch: str) -> str:
    """Remove binary sections exactly as the benchmark evaluator does."""
    sections = re.split(r"(?=^diff --git )", patch, flags=re.MULTILINE)
    kept = []
    for section in sections:
        if not section.strip():
            continue
        if re.search(r"^Binary files .* differ$", section, re.MULTILINE):
            continue
        if re.search(r"^GIT binary patch$", section, re.MULTILINE):
            continue
        kept.append(section)
    return "".join(kept)


def repo_storage_name(repo: str) -> str:
    """Map owner/name to a flat bare-repository directory name."""
    return repo.replace("/", "__") + ".git"


def normalize_apply_error(stderr: str) -> str:
    # Collapse Git's varied wording into stable failure categories for reports.
    lower = stderr.lower()
    if "corrupt patch" in lower or "no valid patches" in lower or "unrecognized input" in lower:
        return "malformed_patch"
    if "does not apply" in lower or "patch failed" in lower:
        return "context_mismatch"
    if "does not exist in index" in lower or "no such file" in lower:
        return "missing_path"
    if "already exists" in lower:
        return "path_conflict"
    return "apply_error"


class GitApplyChecker:
    """Check patches against benchmark base commits stored in bare repositories."""

    def __init__(self, repos_root: Path):
        self.repos_root = repos_root

    @staticmethod
    def _git(git_dir: Path, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", f"--git-dir={git_dir}", *args],
            capture_output=True,
            **kwargs,
        )

    def check(self, dataset_row: dict, patch_exists: bool, patch: str) -> dict:
        # Start with a conservative unavailable result until each prerequisite is proven.
        facts = {
            "patch_application_check_available": False,
            "patch_application_failed": False,
            "patch_application_error_type": "",
        }
        if not patch_exists:
            facts["patch_application_error_type"] = "patch_missing"
            return facts

        cleaned_patch = strip_binary_hunks(patch)
        repo = str(dataset_row.get("repo") or "")
        base_commit = str(dataset_row.get("base_commit") or "")
        git_dir = self.repos_root / repo_storage_name(repo)

        with tempfile.TemporaryDirectory(prefix="failure-apply-") as temp_dir:
            temp_root = Path(temp_dir)
            patch_path = temp_root / "patch.diff"
            patch_path.write_text(cleaned_patch, encoding="utf-8", errors="surrogateescape")

            # Parse first so malformed patches remain detectable without a repository clone.
            parsed = subprocess.run(
                ["git", "apply", "--numstat", "-z", str(patch_path)],
                cwd=temp_root,
                capture_output=True,
            )
            if not cleaned_patch.strip():
                facts.update(
                    patch_application_check_available=True,
                    patch_application_failed=True,
                    patch_application_error_type="empty_patch",
                )
                return facts
            if parsed.returncode != 0:
                facts.update(
                    patch_application_check_available=True,
                    patch_application_failed=True,
                    patch_application_error_type="malformed_patch",
                )
                return facts

            # Repository gaps are infrastructure evidence, not model-editing failures.
            if not git_dir.exists():
                facts["patch_application_error_type"] = "repository_unavailable"
                return facts

            # Commit availability is checked separately to avoid mislabeling rewritten history.
            commit = self._git(git_dir, ["cat-file", "-e", f"{base_commit}^{{commit}}"])
            if commit.returncode != 0:
                facts["patch_application_error_type"] = "base_commit_unavailable"
                return facts

            index_path = temp_root / "index"
            env = {"GIT_INDEX_FILE": str(index_path)}
            # A temporary index reproduces a clean base checkout without materializing a worktree.
            initialized = self._git(git_dir, ["read-tree", base_commit], env=env)
            if initialized.returncode != 0:
                facts["patch_application_error_type"] = "repository_error"
                return facts

            # Cached apply validates paths, modes, and hunk context against the exact base tree.
            applied = self._git(
                git_dir,
                ["apply", "--cached", "--check", str(patch_path)],
                env=env,
            )
            facts["patch_application_check_available"] = True
            facts["patch_application_failed"] = applied.returncode != 0
            if applied.returncode != 0:
                facts["patch_application_error_type"] = normalize_apply_error(
                    applied.stderr.decode("utf-8", errors="replace")
                )
            return facts
