#!/usr/bin/env python3
"""Mechanical SWE-Bench Pro failure signal detection."""

from __future__ import annotations

import json
import re
import ast
import shlex
from pathlib import Path

from analysis.patch_application_checker import GitApplyChecker


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
    "required_interface_missing",
    "required_test_target_still_failing",
    "regression_test_failed",
    "new_tests_not_exercised_or_missing_output",
    "trajectory_no_submission",
    "trajectory_stuck_loop",
    "trajectory_tool_error",
    "trajectory_timeout_or_turn_limit",
    "trajectory_never_opened_gold_files",
    "trajectory_opened_but_did_not_edit_gold_files",
    "trajectory_edited_wrong_subsystem",
    "eval_passed_but_result_false_mismatch",
]

FIELDNAMES = [
    "run",
    "instance_id",
    "repo",
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

TINY_PATCH_CHANGED_LOC_THRESHOLD = 10

TOO_SMALL_GOLD_LOC_MINIMUM = 20
TOO_SMALL_GENERATED_LOC_MINIMUM = 10
TOO_SMALL_GENERATED_TO_GOLD_LOC_RATIO = 0.25

TOO_LARGE_GENERATED_LOC_MINIMUM = 50
TOO_LARGE_GENERATED_TO_GOLD_LOC_RATIO = 3

LARGE_REFACTOR_FILE_COUNT_RATIO = 2
LARGE_REFACTOR_EXTRA_FILE_COUNT_MINIMUM = 5
LARGE_REFACTOR_CHANGED_LOC_MINIMUM = 500
LARGE_REFACTOR_GENERATED_TO_GOLD_LOC_RATIO = 4

MULTI_FILE_PATCH_FILE_COUNT_THRESHOLD = 1
SINGLE_FILE_PATCH_FILE_COUNT = 1
TOOL_ERROR_COUNT_THRESHOLD = 0
TRAJECTORY_STUCK_LOOP_REPEAT_THRESHOLD = 5
TRAJECTORY_WRONG_SUBSYSTEM_MINIMUM_EDITED_FILES = 2

# TODO: Might need to add more patterns
SYNTAX_ERROR_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bSyntaxError:",
        r"\bParseError:",
        r"\bImportError:",
        r"\bModuleNotFoundError:",
        r"\bcompilation failed\b",
        r"\bcompile error\b",
        r"\bcannot compile\b",
        r"\bmodule not found\b",
        r"\berror TS\d{4}:",
        r"\berror: cannot find symbol\b",
        r"\bundefined reference\b",
    )
]

# TODO: Might need to add more patterns
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

# Match repo-like paths in shell/editor actions, including SWE-Agent's /app prefix.
PATH_TOKEN_RE = re.compile(r"(?:/app/|\.?/)?[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)+")

# Match explicit edited-file snapshot markers emitted by some trajectory metadata.
FILE_MARKER_RE = re.compile(r"\[File:\s*([^\]]+)\]")

# Match named interfaces from structured problem-statement sections.
INTERFACE_NAME_RE = re.compile(r"\bName:\s*([A-Za-z_][\w.$:-]*)")

# Match backticked code symbols or paths mentioned as required interfaces.
BACKTICK_SYMBOL_RE = re.compile(r"`([A-Za-z_][\w.$:-]*|\S+/\S+)`")

# Weak backticked examples often look code-like but are not required interfaces.
EXAMPLE_CONTEXT_RE = re.compile(
    r"\b(?:e\.g|example|examples|such as|like|format|formats|input|inputs|invalid|malformed)\b",
    re.IGNORECASE,
)

# Match HTTP method plus route pairs from API-oriented problem statements.
ENDPOINT_RE = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./{}:-]+)")

# TODO: Might need to add more patterns
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

def changed_line_count(text: str) -> int:
    # Count changed diff lines while ignoring file header lines.
    # This is a cheap patch-size proxy, not a semantic measure of effort.
    count = 0
    for line in text.splitlines():
        # Skip file headers
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
            try:
                parts = shlex.split(line)
            except ValueError:
                parts = line.split()
            if len(parts) >= 4:
                for raw in parts[2:4]:
                    path = clean_patch_path(raw)
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
    # Normalize diff paths like a/foo.py and b/foo.py while preserving spaces.
    path = path.split("\t", 1)[0]
    return path[2:] if path.startswith(("a/", "b/")) else path


def normalize_test_name(name: str) -> str:
    # Test names are compared after whitespace normalization only.
    return " ".join(str(name).split())


def normalize_dataset_tests(value: object) -> set[str]:
    # Dataset test fields may be real lists or serialized list strings.
    # Empty or malformed fields become an empty set so detectors stay conservative.
    if isinstance(value, list):
        return {normalize_test_name(item) for item in value if normalize_test_name(item)}
    if isinstance(value, str) and value.strip():
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            return {normalize_test_name(item) for item in parsed if normalize_test_name(item)}
        return {normalize_test_name(value)}
    return set()


def normalize_problem_statement(text: str) -> str:
    # Some rows keep an extra quote wrapper and escaped newlines inside the parsed string.
    stripped = str(text or "").strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
    return stripped.replace("\\n", "\n").replace('\\"', '"')


def extract_required_interfaces(problem_statement: str) -> set[str]:
    # Prefer explicit benchmark interface metadata over guessing from prose.
    text = normalize_problem_statement(problem_statement)
    interfaces = {
        item
        for item in INTERFACE_NAME_RE.findall(text)
        if is_plausible_required_interface(item, strong_source=True)
    }
    interfaces.update(
        item
        for item in ENDPOINT_RE.findall(text)
        if is_plausible_required_interface(item, strong_source=True)
    )

    for line in text.splitlines():
        if EXAMPLE_CONTEXT_RE.search(line):
            continue
        for symbol in BACKTICK_SYMBOL_RE.findall(line):
            # Keep backticked code-like names, but ignore ordinary quoted words.
            if is_plausible_required_interface(symbol, strong_source=False):
                interfaces.add(symbol)
    return {item.strip() for item in interfaces if item.strip()}


def is_plausible_required_interface(value: str, strong_source: bool) -> bool:
    # Filter obvious examples/literals without trying to semantically parse prose.
    # TODO: Might need to add more patterns
    symbol = str(value or "").strip().strip(".,;:")
    lower = symbol.lower()
    if not symbol:
        return False
    if lower.startswith(("http://", "https://")):
        return False
    if "<" in symbol or ">" in symbol:
        return False
    if symbol in {"True", "False", "None", "NotImplemented"}:
        return False
    if symbol.endswith(("Error", "Exception")):
        return False
    if symbol.startswith("-") or re.search(r"\d+[hms]", symbol):
        return False
    if strong_source:
        return True

    if "/" in symbol:
        return not lower.startswith(("example.", "www."))
    if "." in symbol:
        parts = symbol.split(".")
        return not any(part in {"example", "test"} for part in parts)
    if "_" in symbol:
        return True
    if symbol[:1].isupper():
        return len(symbol) > 3
    return False


def interface_present_in_patch(interface: str, patch: str) -> bool:
    # Full names are strongest; suffixes catch common implementations like db.mget -> mget.
    if interface in patch:
        return True
    suffix = interface.rsplit(".", 1)[-1].rsplit(":", 1)[-1]
    return suffix != interface and re.search(rf"\b{re.escape(suffix)}\b", patch) is not None


def normalize_repo_path(path: str) -> str:
    # Trajectory tools often use /app paths; generated patches use repo-relative paths.
    path = str(path or "").replace("\\", "/").strip().strip("'\"`,:;()[]{}")
    path = re.sub(r"/+", "/", path)
    path = path.split("#", 1)[0]
    if re.match(r"^[A-Za-z]:/", path):
        path = path[3:]
    path = re.sub(r":\d+$", "", path)
    if path.startswith("/app/"):
        path = path[5:]
    elif path == "/app":
        path = ""
    while path.startswith("./"):
        path = path[2:]
    return path.strip("/")


def extract_paths_from_text(text: str) -> set[str]:
    # This intentionally accepts broad path-looking tokens and normalizes later.
    paths = {normalize_repo_path(match) for match in PATH_TOKEN_RE.findall(str(text or ""))}
    paths.update(normalize_repo_path(match) for match in FILE_MARKER_RE.findall(str(text or "")))
    return {path for path in paths if is_plausible_extracted_path(path)}


def is_plausible_extracted_path(path: str) -> bool:
    # Keep this narrow: reject obvious value ranges without guessing repo language rules.
    if not path or path.startswith(".git/"):
        return False
    parts = path.split("/")
    return not any(part in {"min", "max", "-inf", "+inf"} for part in parts)


def extract_paths_from_action(action: str) -> set[str]:
    # Editor commands can embed full file contents; keep only the command portion.
    command = str(action or "").split("--file_text", 1)[0]
    return extract_paths_from_text(command)


def extract_file_markers(text: str) -> set[str]:
    # Edited-file snapshots use explicit [File: path] markers before file contents.
    return {
        path
        for path in (normalize_repo_path(match) for match in FILE_MARKER_RE.findall(str(text or "")))
        if path
    }


def path_subsystems(paths: set[str]) -> set[str]:
    # Top-level directories are a simple subsystem proxy across mixed repositories.
    return {path.split("/", 1)[0] for path in paths if "/" in path}


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
        "test_count": None,
        "output_text": "",
        "failed_output_text": "",
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
    failed_text_chunks = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        name = normalize_test_name(test.get("name", ""))
        if not name:
            continue
        facts["seen_test_names"].add(name)
        if test.get("status") != "PASSED":
            facts["failed_test_names"].add(name)
            # Keep failure diagnostics, but do not treat the test name itself as error text.
            failed_text_chunks.extend(
                str(value)
                for key, value in test.items()
                if key != "name" and isinstance(value, str)
            )

    facts["test_count"] = len(tests)
    facts["failed_tests"] = bool(facts["failed_test_names"])
    facts["failed_output_text"] = "\n".join(failed_text_chunks)
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


def syntax_error_evidence(text: str) -> bool:
    # Require diagnostic-looking text so test names like test_importerror do not match.
    return any(pattern.search(str(text or "")) for pattern in SYNTAX_ERROR_PATTERNS)


def load_trajectory_facts(path: Path | None) -> dict:
    # Missing or malformed trajectories provide no evidence and must not become failures.
    facts = {
        "trajectory_available": False,
        "trajectory_submitted": False,
        "trajectory_tool_error_count": 0,
        "trajectory_timeout_or_turn_limit": False,
        "trajectory_opened_files": set(),
        "trajectory_edited_files": set(),
        "trajectory_max_repeated_action": 0,
        "trajectory_diagnostic_text": "",
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
    diagnostic_chunks = []
    repeated_count = 0
    previous_fingerprint = None
    for step in steps:
        action = str(step.get("action") or "").strip()
        action_lower = action.lower()
        action_paths = extract_paths_from_action(action)
        first_word = action_lower.split(maxsplit=1)[0] if action_lower else ""

        # Track file reads from common shell/editor actions; thoughts are deliberately ignored.
        if first_word in {"cat", "sed", "grep", "rg", "head", "tail", "nl", "less"} or " view " in f" {action_lower} ":
            facts["trajectory_opened_files"].update(action_paths)
        if any(word in action_lower for word in ("str_replace_editor", "apply_patch", " create ", " edit ", " replace ")):
            facts["trajectory_edited_files"].update(action_paths)

        # Consecutive identical command/path fingerprints are a simple stuck-loop signal.
        fingerprint_paths = sorted(action_paths)
        fingerprint = (first_word, fingerprint_paths[0] if fingerprint_paths else action_lower[:80])
        if action_lower and fingerprint == previous_fingerprint:
            repeated_count += 1
        else:
            repeated_count = 1 if action_lower else 0
            previous_fingerprint = fingerprint if action_lower else None
        facts["trajectory_max_repeated_action"] = max(facts["trajectory_max_repeated_action"], repeated_count)

        # Observations are command/tool results. Thoughts and responses often quote issue
        # text or source code and would create many false positives.
        if not action:
            continue
        observation = str(step.get("observation") or "")
        if syntax_error_evidence(observation):
            diagnostic_chunks.append(observation)
        if any(pattern.search(observation) for pattern in TOOL_ERROR_PATTERNS):
            error_steps += 1
            
    if any(marker in exit_status for marker in ("exit_error", "exit_format", "exit_command_timeout")):
        error_steps += 1
    facts["trajectory_tool_error_count"] = error_steps
    facts["trajectory_diagnostic_text"] = "\n".join(diagnostic_chunks)

    # SWE-Agent sometimes stores edited file snapshots in info instead of action names.
    for key, value in info.items():
        if str(key).startswith("edited_files"):
            facts["trajectory_edited_files"].update(extract_file_markers(str(value)))

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
    required_interfaces = extract_required_interfaces(dataset_row.get("problem_statement") or "")

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
    missing_required_interfaces = {
        interface
        for interface in required_interfaces
        if not interface_present_in_patch(interface, generated_patch)
    }

    facts = {
        "patch_path": patch_path,
        "output_path": output_path,
        "gold_files": gold_files,
        "test_files": test_files,
        "generated_files": generated_files,
        "gold_loc": gold_loc,
        "generated_loc": generated_loc,
        "required_interfaces": required_interfaces,
        "missing_required_interfaces": missing_required_interfaces,
        "overlap": overlap,
        "missing_gold": missing_gold,
        "extra_files": extra_files,
        "failed_tests": output_facts["failed_tests"],
        "test_count": output_facts["test_count"],
        "seen_test_names": output_facts["seen_test_names"],
        "failed_test_names": output_facts["failed_test_names"],
        "attempt_text": read_attempt_text(attempt_dir, output_facts["failed_output_text"]),
        "trajectory_diagnostic_text": trajectory_facts["trajectory_diagnostic_text"],
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
    """Detect patch artifact and mechanical applyability signals.

    Covered signals:
    - no_patch: the generated patch artifact is missing.
    - empty_or_tiny_patch: the generated patch exists but changes very little.
    - patch_application_or_editing_failure: git can parse/check the patch and the check fails.
    """
    # Patch-presence signals do not need gold-patch comparison.
    no_patch = not facts["patch_path"].exists()
    return {
        # no_patch means the artifact is absent in the eval directory.
        "no_patch": no_patch,

        # empty_or_tiny_patch fires for any present patch below the configured changed-line threshold.
        "empty_or_tiny_patch": (not no_patch) and facts["generated_loc"] < TINY_PATCH_CHANGED_LOC_THRESHOLD,

        # Only definitive parser/index failures emit this signal; infrastructure gaps remain unavailable.
        "patch_application_or_editing_failure": (
            facts["patch_application_check_available"] and facts["patch_application_failed"]
        ),
    }


def detect_eval_output_signals(facts: dict) -> dict[str, bool]:
    """Detect signals from structured eval output and diagnostic text.

    Covered signals:
    - test_failure_available: `_output.json` contains at least one non-PASSED test.
    - missing_output: `_output.json` is absent, invalid, or not shaped like test output.
    - syntax_or_parse_error: output/log/trajectory diagnostics contain syntax/import/compile markers.
    """
    # Eval output is used only for observable test-failure signals.
    diagnostic_text = "\n".join([facts["attempt_text"], facts.get("trajectory_diagnostic_text", "")])
    has_passing_test_results = facts["failed_tests"] is False and facts["test_count"] is not None and facts["test_count"] > 0
    return {
        # test_failure_available fires when structured output has at least one non-PASSED test.
        "test_failure_available": facts["failed_tests"] is True,

        # missing_output covers absent or unstructured output, not just missing files.
        "missing_output": facts["failed_tests"] is None,

        # syntax_or_parse_error uses conservative text markers from output/log files.
        "syntax_or_parse_error": (not has_passing_test_results) and syntax_error_evidence(diagnostic_text),
    }


def detect_file_overlap_signals(facts: dict) -> dict[str, bool]:
    """Compare generated patch files with gold patch files.

    Covered signals:
    - wrong_files_touched: generated files have no overlap with gold files.
    - partial_file_overlap: generated files hit some gold files but miss others.
    - all_gold_files_touched: generated files cover the whole gold file set.
    - missing_gold_files: at least one gold file is absent from the generated patch.
    - extra_files_touched: generated patch changes files outside the gold file set.
    """
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
    """Compare generated patch size against gold patch size.

    Covered signals:
    - generated_patch_too_small: generated changed LOC is much smaller than gold LOC.
    - generated_patch_too_large: generated changed LOC is much larger than gold LOC.
    - large_refactor: generated patch has broad file or LOC churn relative to gold.
    """
    # Size thresholds mirror the report heuristics and remain configurable later.
    gold_loc = facts["gold_loc"]
    generated_loc = facts["generated_loc"]
    gold_files = facts["gold_files"]
    generated_files = facts["generated_files"]
    return {
        # Too-small patches are only flagged when the gold patch is large enough to compare.
        "generated_patch_too_small": (
            gold_loc >= TOO_SMALL_GOLD_LOC_MINIMUM
            and generated_loc < max(
                TOO_SMALL_GENERATED_LOC_MINIMUM,
                int(TOO_SMALL_GENERATED_TO_GOLD_LOC_RATIO * gold_loc),
            )
        ),
        
        # Too-large patches use both a ratio threshold and an absolute minimum.
        "generated_patch_too_large": generated_loc > max(
            TOO_LARGE_GENERATED_LOC_MINIMUM,
            TOO_LARGE_GENERATED_TO_GOLD_LOC_RATIO * gold_loc,
        ),
        
        # large_refactor catches broad file churn or very large LOC churn.
        "large_refactor": (
            len(generated_files) > max(
                LARGE_REFACTOR_FILE_COUNT_RATIO * len(gold_files),
                len(gold_files) + LARGE_REFACTOR_EXTRA_FILE_COUNT_MINIMUM,
            )
            or generated_loc > max(
                LARGE_REFACTOR_CHANGED_LOC_MINIMUM,
                LARGE_REFACTOR_GENERATED_TO_GOLD_LOC_RATIO * gold_loc,
            )
        ),
    }


def detect_file_type_signals(facts: dict) -> dict[str, bool]:
    """Classify task and generated-patch file types.

    Covered signals:
    - multi_file_gold_patch / single_file_gold_patch: shape of the reference patch.
    - generated_patch_multi_file: generated patch touches multiple files.
    - tests_only_patch: generated files are only benchmark test-patch files.
    - docs_only_patch: generated files are all documentation paths.
    - production_code_not_touched: generated files are only tests/docs/generated/vendor paths.
    - generated_or_vendor_churn: generated patch touches likely generated/vendor/lockfile paths.
    """
    # test_patch gives benchmark-specific test files; docs remain path-based.
    generated_files = facts["generated_files"]
    test_files = facts["test_files"]
    return {
        # multi_file_gold_patch describes task shape, not generated patch behavior.
        "multi_file_gold_patch": len(facts["gold_files"]) > MULTI_FILE_PATCH_FILE_COUNT_THRESHOLD,

        # single_file_gold_patch is useful for separating simple-looking gold patches.
        "single_file_gold_patch": len(facts["gold_files"]) == SINGLE_FILE_PATCH_FILE_COUNT,

        # generated_patch_multi_file describes how broad the generated edit is.
        "generated_patch_multi_file": len(generated_files) > MULTI_FILE_PATCH_FILE_COUNT_THRESHOLD,

        # tests_only_patch is strict: generated files must be a subset of benchmark test_patch files.
        "tests_only_patch": bool(generated_files) and bool(test_files) and generated_files <= test_files,
        
        # docs_only_patch fires only when every generated file is classified as documentation.
        "docs_only_patch": bool(generated_files) and all(is_docs_path(path) for path in generated_files),
        
        # production_code_not_touched is broader and allows obvious test/docs/generated/vendor paths.
        "production_code_not_touched": bool(generated_files) and all(is_non_production_path(path, test_files) for path in generated_files),
        
        # generated_or_vendor_churn fires on any likely generated/vendor/lockfile path.
        "generated_or_vendor_churn": bool(generated_files) and any(is_generated_or_vendor_path(path) for path in generated_files),
    }


def detect_required_interface_signals(facts: dict) -> dict[str, bool]:
    """Detect missing explicit interfaces from the problem statement.

    Covered signal:
    - required_interface_missing: the issue names an interface/endpoint/symbol and the
      generated patch contains neither the full name nor an accepted suffix form.
    """
    # Emit only when the problem names explicit interfaces and the patch misses at least one.
    return {
        "required_interface_missing": bool(facts["required_interfaces"])
        and bool(facts["missing_required_interfaces"]),
    }


def detect_test_target_signals(facts: dict) -> dict[str, bool]:
    """Compare benchmark target/regression tests with structured eval results.

    Covered signals:
    - required_test_target_still_failing: a FAIL_TO_PASS test is still failing.
    - regression_test_failed: a PASS_TO_PASS test failed.
    - new_tests_not_exercised_or_missing_output: FAIL_TO_PASS tests are absent from output
      or output is missing/unstructured.
    """
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
    """Detect behavioral signals from parsed agent trajectory data.

    Covered signals:
    - trajectory_no_submission: no explicit or metadata-recorded submission.
    - trajectory_stuck_loop: repeated consecutive action fingerprints.
    - trajectory_tool_error: command/tool error patterns occurred in observations or exit status.
    - trajectory_timeout_or_turn_limit: exit status or final text indicates budget/timeout limits.
    - trajectory_never_opened_gold_files: read actions never touched gold files.
    - trajectory_opened_but_did_not_edit_gold_files: gold files were read but not changed.
    - trajectory_edited_wrong_subsystem: edits concentrate in top-level paths disjoint from gold.
    """
    # Trajectory absence is an artifact gap, not proof of agent behavior.
    available = facts["trajectory_available"]
    opened_files = facts.get("trajectory_opened_files", set())
    edited_files = facts.get("trajectory_edited_files", set())
    gold_files = facts.get("gold_files", set())
    generated_files = facts.get("generated_files", set())
    opened_gold = opened_files & gold_files
    edited_or_generated = edited_files | generated_files
    gold_subsystems = path_subsystems(gold_files)
    edited_subsystems = path_subsystems(edited_or_generated)
    return {
        "trajectory_no_submission": available and not facts["trajectory_submitted"],
        "trajectory_stuck_loop": available and facts["trajectory_max_repeated_action"] >= TRAJECTORY_STUCK_LOOP_REPEAT_THRESHOLD,
        "trajectory_tool_error": available and facts["trajectory_tool_error_count"] > TOOL_ERROR_COUNT_THRESHOLD,
        "trajectory_timeout_or_turn_limit": available and facts["trajectory_timeout_or_turn_limit"],
        # Require at least one extracted read path so missing parser coverage stays neutral.
        "trajectory_never_opened_gold_files": available and bool(gold_files) and bool(opened_files) and not opened_gold,
        "trajectory_opened_but_did_not_edit_gold_files": available and bool(opened_gold) and not (opened_gold & generated_files),
        # This is intentionally a subsystem heuristic, not a semantic wrong-solution verdict.
        "trajectory_edited_wrong_subsystem": (
            available
            and bool(gold_subsystems)
            and len(edited_or_generated) >= TRAJECTORY_WRONG_SUBSYSTEM_MINIMUM_EDITED_FILES
            and bool(edited_subsystems)
            and not (edited_or_generated & gold_files)
            and edited_subsystems.isdisjoint(gold_subsystems)
        ),
    }


def detect_result_mismatch_signals(facts: dict) -> dict[str, bool]:
    """Detect mismatches between structured eval output and official result maps.

    Covered signal:
    - eval_passed_but_result_false_mismatch: tests look passed in `_output.json`, but the
      official result map marks the attempt unresolved.
    """
    # This narrow mismatch catches passed-looking output marked unresolved officially.
    resolved = facts.get("resolved")
    failed_tests = facts["failed_tests"]
    has_test_results = facts["test_count"] is not None and facts["test_count"] > 0
    return {
        # This does not flag resolved=True with failed output; it only tracks false negatives.
        "eval_passed_but_result_false_mismatch": (
            resolved is not None
            and failed_tests is not None
            and has_test_results
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
    signals.update(detect_required_interface_signals(facts))
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
    # Return shape: one CSV row keyed by FIELDNAMES. All values are strings so
    # csv.DictWriter can write the row directly; booleans are encoded as "1"/"0".
    facts = build_attempt_facts(attempt_dir, dataset_row, trajectory_path, apply_checker)

    # Eval output is a signal source, but only official maps label success/failure.
    resolved = result_map.get(instance_id) if result_map and instance_id in result_map else None
    
    # resolved=None means this attempt is included in detail output but excluded from failure rates.
    facts["resolved"] = resolved
    signals = detect_signals(facts)

    row = {
        "run": run,
        "instance_id": instance_id,
        "repo": str(dataset_row.get("repo") or ""),
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
