# Failure Signal Detection

This file lists failure categories that can be detected from SWE-Bench Pro artifacts when the issue text, requirements, gold patch, generated patch, eval output, and trajectory are available.

The important distinction is:

- **Mechanical failure signals** are measurable facts or close-to-facts. These are good targets for deterministic scripts.
- **Reviewed failure causes** are higher-level explanations. They can often be suggested from signals, but usually require semantic review to confirm.

Current implementation:

- Script: `analysis/failure_signal_analyzer.py`
- Patch checker: `analysis/patch_application_checker.py`
- Repository setup: `analysis/prepare_failure_analysis_repos.py`
- Detailed output: `analysis/output/failure_signals.csv`
- Summary output: `analysis/output/failure_signal_summary.csv`
- Markdown report: `analysis/output/failure_signal_report.md`, including overall, per-model/run, and per-repository signal breakdowns.
- Scope: low-to-medium-complexity mechanical signals, including explicit interface checks and structured trajectory signals.
- Validation: signal failure rates are computed only where an official `traj/*/eval_results.json` result map is available.
- Path policy: `tests_only_patch` is strict and only uses benchmark `test_patch` files; `production_code_not_touched` is broader and also treats obvious test paths, docs, and generated/vendor files as non-production.
- Trajectory path extraction is language-agnostic but heuristic: it depends on path-like tokens in actions or `[File: ...]` metadata, filters obvious value ranges such as `min/max` and `-inf/+inf`, and may miss unusual agent formats or single-file names without directories.
- Required-interface extraction is conservative: it uses explicit `Name:` fields, HTTP routes, and code-like backticked symbols from the problem statement, while filtering obvious examples, URLs, placeholder paths, literals, and exception names. It should still be read as medium-confidence evidence rather than semantic proof.
- Trajectory path: use `--trajectory-root` for a root containing `<run>/traj/<instance_id>/*.traj`; it defaults to `--eval-root`.
- Missing or malformed trajectories set `trajectory_available=0` and do not emit behavioral trajectory signals.
- Patch application checks use full bare clones under `analysis/repos/` by default. Run `python3 analysis/prepare_failure_analysis_repos.py` once to clone the public repositories, fetch dataset commits that are no longer advertised by branch refs, and write `analysis/output/repo_availability.json`.
- Missing repositories or base commits set `patch_application_check_available=0`; they do not emit `patch_application_or_editing_failure`.
- CLI progress is printed every 100 attempts by default; configure the interval with `--progress-every N` or disable it with `--progress-every 0`.
- Use `--skip-trajectory-signals` to avoid loading trajectory files and `--skip-repo-checks` to avoid repository-backed patch application checks.
- Attempts are sequential by default; use `--workers N` to process attempts in parallel while the parent process retains progress reporting and CSV writes.

## Mechanical Failure Signals

| Implemented | Signal | Meaning | Required inputs | Detection robustness | Script complexity |
|---|---|---|---|---|---|
| [x] | `no_patch` | No generated patch artifact exists for the attempt. | Agent artifacts | Very high | Low |
| [x] | `empty_or_tiny_patch` | Generated patch is empty or below a small LOC threshold. | Generated patch | Very high | Low |
| [x] | `patch_application_or_editing_failure` | Patch is malformed, cannot be applied, or produces mechanically inconsistent edits. | Generated patch, base repo | High | Medium |
| [x] | `syntax_or_parse_error` | Failed eval diagnostics or trajectory observations report syntax, parse, import, compile, or equivalent language-level failure. | Eval output/logs, trajectory observations | Medium-high if diagnostics are structured | Medium |
| [x] | `test_failure_available` | Public eval output contains at least one failed test. | Eval output | Very high | Low |
| [x] | `missing_output` | No eval output artifact is available for the attempt. | Eval artifacts | Very high | Low |
| [x] | `wrong_files_touched` | Generated patch touches files with no overlap with gold patch files. | Gold patch, generated patch | High | Low |
| [x] | `partial_file_overlap` | Generated patch touches some, but not all, gold patch files. | Gold patch, generated patch | High | Low |
| [x] | `all_gold_files_touched` | Generated patch touches every file changed by the gold patch. | Gold patch, generated patch | Very high | Low |
| [x] | `missing_gold_files` | One or more gold patch files are absent from the generated patch. | Gold patch, generated patch | Very high | Low |
| [x] | `extra_files_touched` | Generated patch changes files not present in the gold patch. | Gold patch, generated patch | Very high | Low |
| [x] | `generated_patch_too_small` | Generated patch LOC is far smaller than gold patch LOC. | Gold patch, generated patch | High as a size signal | Low |
| [x] | `generated_patch_too_large` | Generated patch LOC is far larger than gold patch LOC. | Gold patch, generated patch | High as a size signal | Low |
| [x] | `large_refactor` | Generated patch changes far more files or LOC than the gold patch. | Gold patch, generated patch | Medium-high as a heuristic | Low |
| [x] | `multi_file_gold_patch` | Gold patch changes more than one file. | Gold patch | Very high | Low |
| [x] | `single_file_gold_patch` | Gold patch changes exactly one file. | Gold patch | Very high | Low |
| [x] | `generated_patch_multi_file` | Generated patch changes more than one file. | Generated patch | Very high | Low |
| [x] | `production_code_not_touched` | Generated patch avoids production-code paths and only touches non-production areas. | Generated patch, repo path rules | Medium-high | Medium |
| [x] | `tests_only_patch` | Generated patch only changes files from the benchmark `test_patch`. | Generated patch, benchmark `test_patch` | Very high | Low |
| [x] | `docs_only_patch` | Generated patch only changes documentation files. | Generated patch, path rules | High | Low |
| [ ] | `config_only_patch` | Generated patch only changes config/build/metadata files. | Generated patch, path rules | Medium-high | Medium |
| [x] | `generated_or_vendor_churn` | Generated patch changes generated, vendor, lockfile, or bundled files. | Generated patch, path rules | Medium-high | Medium |
| [x] | `required_interface_missing` | Issue explicitly names an interface, method, class, endpoint, or function that is absent from the generated patch. | Problem statement, generated patch | Medium-high when interfaces are explicit | Medium-high |
| [x] | `required_test_target_still_failing` | A `FAIL_TO_PASS` test is still failing after applying the generated patch. | `FAIL_TO_PASS`, eval output | Very high | Medium |
| [x] | `regression_test_failed` | A `PASS_TO_PASS` test fails after applying the generated patch. | `PASS_TO_PASS`, eval output | Very high | Medium |
| [x] | `new_tests_not_exercised_or_missing_output` | Expected target tests are absent from eval output or no useful output is available. | `FAIL_TO_PASS`, eval output | High | Medium |
| [x] | `trajectory_no_submission` | Trajectory never reaches a submit/final-answer action. | Trajectory | High if actions are structured | Medium |
| [x] | `trajectory_stuck_loop` | Trajectory repeats similar actions or observations beyond a fixed threshold. | Trajectory | Medium-high | Medium-high |
| [x] | `trajectory_tool_error` | Trajectory records tool failures, command errors, or API/tool invocation errors. | Trajectory | High if errors are structured | Medium |
| [x] | `trajectory_timeout_or_turn_limit` | Run ends due to timeout, turn limit, or equivalent budget exhaustion. | Trajectory/run metadata | High if logged | Low-medium |
| [x] | `trajectory_never_opened_gold_files` | Agent never inspected files changed by the gold patch. | Trajectory, gold patch | Medium-high | Medium-high |
| [x] | `trajectory_opened_but_did_not_edit_gold_files` | Agent inspected gold files but did not modify them. | Trajectory, gold patch, generated patch | Medium-high | Medium-high |
| [x] | `trajectory_edited_wrong_subsystem` | Agent repeatedly inspected or edited paths outside the gold-patch subsystem. | Trajectory, gold patch, path rules | Medium as a heuristic | Medium-high |
| [x] | `eval_passed_but_result_false_mismatch` | Non-empty structured eval output has no failed tests, but the result map marks the instance unresolved. | Eval result map, eval output | High for mismatch detection | Medium |

## Reviewed Failure Causes

These remain separate candidate-cause outputs. The implemented mechanical
`patch_application_or_editing_failure` signal does not by itself mark the
identically named reviewed-cause output as implemented.

| Implemented | Cause | Meaning | Deterministic detection status | Best mechanical evidence | Detection robustness | Script complexity |
|---|---|---|---|---|---|---|
| [ ] | `overbroad_refactor` | Patch makes broad, unrelated, or unfocused changes instead of the narrow fix required. | Candidate only | `generated_patch_too_large`, `large_refactor`, `extra_files_touched`, `generated_or_vendor_churn` | Medium | Medium |
| [ ] | `incomplete_implementation` | Patch targets relevant code but implements only part of the required behavior. | Candidate only | `partial_file_overlap`, `missing_gold_files`, `generated_patch_too_small`, failed `FAIL_TO_PASS` tests | Medium | Medium |
| [ ] | `multi_file_coordination_failure` | Patch finds part of the right area but misses required files, wiring, generated artifacts, fixtures, schema/docs, or integration points. | Candidate only, often strong | `multi_file_gold_patch`, `partial_file_overlap`, `missing_gold_files`, required interface missing | Medium-high | Medium |
| [ ] | `wrong_subsystem_targeted` | Patch edits the wrong package, module, test/config area, generated artifact, or subsystem. | Candidate only | `wrong_files_touched`, low path overlap, `production_code_not_touched`, `tests_only_patch` | Medium-high | Medium |
| [ ] | `framework_api_misunderstanding` | Patch misunderstands framework conventions, project APIs, generated-code flow, or language-specific behavior. | Not reliably deterministic | Syntax/import errors, failed tests, trajectory notes, edits near framework integration points | Low-medium | High |
| [ ] | `patch_application_or_editing_failure` | Patch is malformed, misplaced, inconsistent, or fails mechanically during apply/build. | Often deterministic | Patch apply failure, syntax/parse error, malformed diff, broken generated files | High | Medium |
| [ ] | `insufficient_generated_patch` | Patch is too small, superficial, or does not materially address the requested behavior. | Candidate only, sometimes strong | `empty_or_tiny_patch`, `generated_patch_too_small`, required interfaces missing, failed target tests | Medium-high | Low-medium |
| [ ] | `test_expectation_misunderstood` | Patch misses exact behavior, edge case, signature, output shape, or assertion expected by tests. | Candidate only | Failed `FAIL_TO_PASS` tests, assertion messages, expected-vs-actual output, issue requirements | Medium | High |
| [ ] | `environment_or_artifact_gap` | Local artifacts are missing or incomplete, limiting what can be concluded. | Deterministic for artifact gaps, not for root cause | `missing_output`, `no_patch`, incomplete trajectory, missing logs | High for artifact gap | Low |

## Recommended Script Output

Scripts should avoid pretending that semantic root causes are fully deterministic. A robust analyzer should emit both exact signals and inferred causes:

```json
{
  "deterministic_signals": [
    "partial_file_overlap",
    "missing_gold_files",
    "required_test_target_still_failing"
  ],
  "candidate_failure_categories": [
    {
      "category": "multi_file_coordination_failure",
      "confidence": "high",
      "evidence": "Gold patch changed 5 files; generated patch touched 2 of them; two FAIL_TO_PASS tests still failed."
    }
  ]
}
```

## Implementation Plan: Mechanical Failure Signals

Common preprocessing:

1. Load the benchmark row by `instance_id` from `helper_code/sweap_eval_full_v2.jsonl`.
2. Parse `patch` as the gold patch and the generated `_patch.diff` as the model patch.
3. Extract changed files, added/deleted LOC, hunks, file extensions, and top-level path components from both patches.
4. Load eval artifacts such as `_output.json`, stdout/stderr logs, and result maps.
5. Load trajectory messages/actions and normalize them into opened files, edited files, tool errors, submit actions, repeated actions, and termination reason.

| Signal | Implementation plan |
|---|---|
| `no_patch` | Check whether the generated patch file exists and is non-empty. Emit if the file is missing. |
| `empty_or_tiny_patch` | Count changed LOC in the generated patch. Emit if changed LOC is `0` or below a fixed threshold such as `<10`. Keep the threshold configurable. |
| `patch_application_or_editing_failure` | Strip binary sections exactly as the evaluator does, parse the generated patch with `git apply --numstat`, load `base_commit` into a temporary index backed by the repository's bare clone, and run `git apply --cached --check`. Emit for empty, malformed, context-mismatched, missing-path, or conflicting patches. Record unavailable repositories/commits separately instead of treating infrastructure gaps as patch failures. |
| `syntax_or_parse_error` | Search failure diagnostics, sibling logs, and trajectory command observations for diagnostic-looking syntax/compile/import markers. Do not match test names alone; examples include `SyntaxError:`, `ParseError:`, `ImportError:`, `ModuleNotFoundError:`, `error TS2339:`, `Compilation failed`, and `error: cannot find symbol`. If structured eval output contains a non-empty all-passed test list, suppress earlier trajectory diagnostics so transient errors fixed before final eval do not count. |
| `test_failure_available` | Parse `_output.json`; emit if any test object has status other than `PASSED`. If only logs exist, detect known test framework failure markers. |
| `missing_output` | Emit if `_output.json` and relevant stdout/stderr logs are absent or unreadable for the attempt. |
| `wrong_files_touched` | Parse file sets from gold and generated patches. Emit if generated file set is non-empty and intersection with gold file set is empty. |
| `partial_file_overlap` | Emit if intersection with gold files is non-empty but does not cover all gold files. Include missing and touched gold file lists. |
| `all_gold_files_touched` | Emit if every gold file appears in the generated patch. This is a positive coverage signal, not a failure by itself. |
| `missing_gold_files` | Emit the exact list `gold_files - generated_files`. Optionally separate production, tests, docs, fixtures, generated files, schemas, and config paths. |
| `extra_files_touched` | Emit the exact list `generated_files - gold_files`. Summarize by path type and top-level package. |
| `generated_patch_too_small` | Compute generated LOC and gold LOC. Emit if `gold_loc >= 20` and `generated_loc < max(10, 0.25 * gold_loc)`. Thresholds should be configurable. |
| `generated_patch_too_large` | Emit if `generated_loc > max(50, 3 * gold_loc)`. Also record file count ratio. |
| `large_refactor` | Emit if generated file count is greater than `max(2 * gold_file_count, gold_file_count + 5)` or generated LOC is greater than `max(500, 4 * gold_loc)`. |
| `multi_file_gold_patch` | Emit if gold patch file count is `>1`. |
| `single_file_gold_patch` | Emit if gold patch file count is `1`. |
| `generated_patch_multi_file` | Emit if generated patch file count is `>1`. |
| `production_code_not_touched` | Classify paths with conservative generic rules. Emit if generated patch has no production paths and only touches benchmark test files, obvious test paths, docs, or generated/vendor files. Config/build metadata is intentionally excluded until repo-specific rules exist. |
| `tests_only_patch` | Parse files from the benchmark `test_patch`. Emit only if every generated path is contained in that `test_patch` file set. No generic path-name fallback is used. |
| `docs_only_patch` | Emit if every generated path matches docs-only rules, e.g. `docs/`, `doc/`, `README*`, `*.md`, `*.rst`, `*.asciidoc`. |
| `config_only_patch` | Currently not implemented. A robust version should avoid global filename allowlists and prefer repo-specific path rules plus gold-patch context. Emit only when changed files are explicitly known to be build/CI/tooling metadata for that repo and are not benchmark-relevant gold files. |
| `generated_or_vendor_churn` | Emit if generated patch touches likely generated/vendor files, e.g. `vendor/`, `dist/`, `build/`, generated API clients, snapshots, lockfiles, minified bundles. Flag as churn if these files are extra relative to gold or dominate changed LOC. |
| `required_interface_missing` | Extract explicit interfaces from the benchmark row. Prefer names after `Name:` and HTTP method routes. Include code-like backticked symbols only outside example-heavy contexts such as `e.g.`, `examples`, `like`, `format`, or `invalid inputs`. Filter obvious non-interfaces including URLs, `<placeholder>` paths, boolean/null literals, and exception class names. Emit if the generated patch does not contain the full required symbol/path or a method/function suffix such as `db.mget` -> `mget`. |
| `required_test_target_still_failing` | Normalize `FAIL_TO_PASS` names from the dataset and compare to failed tests in `_output.json`. Emit if any target test is still failing. |
| `regression_test_failed` | Normalize `PASS_TO_PASS` names and compare to failed tests. Emit if a regression test fails. |
| `new_tests_not_exercised_or_missing_output` | Emit if `FAIL_TO_PASS` exists but none of those tests appear in output, or if output is missing. This catches incomplete eval artifacts or test-selection problems. |
| `trajectory_no_submission` | Parse trajectory actions/messages for submit commands, final patch submission, or equivalent terminal action. Emit if no submit action appears before termination. |
| `trajectory_stuck_loop` | Build fingerprints of consecutive actions: command type, target file/path, search query, or observation hash. Emit if the same or highly similar action repeats beyond a threshold, e.g. `>=5`, without meaningful file changes. |
| `trajectory_tool_error` | Parse trajectory observations for structured errors and common tool failure patterns: command non-zero exit, file-not-found, patch apply failure, timeout, permission error, JSON/tool schema error. Emit counts and examples. |
| `trajectory_timeout_or_turn_limit` | Inspect run metadata and final trajectory messages for timeout, max-turn, budget, cost-limit, or termination reason. Emit if present. |
| `trajectory_never_opened_gold_files` | Extract opened/read file paths from trajectory actions and `[File: ...]` markers. Normalize paths for repo root and leading `./`, reject obvious non-file value ranges such as `min/max`, and emit if extracted opened paths exist but none overlap gold file paths. |
| `trajectory_opened_but_did_not_edit_gold_files` | Emit if the agent opened/read at least one gold file but generated patch does not modify that file. Useful for distinguishing search failure from edit/implementation failure. |
| `trajectory_edited_wrong_subsystem` | Compare edited paths in trajectory/generated patch to gold top-level directories/modules. Emit if edits concentrate in different subsystems and gold subsystem is untouched or lightly touched. Keep as heuristic. |
| `eval_passed_but_result_false_mismatch` | Compare result map boolean to parsed eval output. Emit only when the result map is `false`, `_output.json` contains a non-empty structured test list, and none of those tests failed. Empty `tests: []` is treated as missing evidence, not as passed-looking eval output. |

## Implementation Plan: Reviewed Failure Causes

Reviewed causes should be emitted as candidate causes with confidence and evidence. Deterministic rules should generate candidates first; an LLM-as-judge can then review the issue text, gold patch summary, generated patch summary, eval failures, and trajectory excerpts.

Recommended judge input should be compact and structured:

- issue title and requirements
- explicit interfaces from the problem statement
- gold patch file list and per-file summary
- generated patch file list and per-file summary
- deterministic signals
- failing tests and key error snippets
- trajectory summary: files opened, files edited, repeated tool errors, submit/termination

| Cause | Implementation plan |
|---|---|
| `overbroad_refactor` | Rule candidate: emit when `generated_patch_too_large`, `large_refactor`, many `extra_files_touched`, or generated/vendor churn is present. Increase confidence if extra files are unrelated by top-level subsystem or if formatting-only churn dominates. Use LLM-as-judge to decide whether the added breadth is semantically unrelated to the issue, because file count alone is not enough. |
| `incomplete_implementation` | Rule candidate: emit when generated patch has partial overlap with gold files, missing required interfaces, generated patch too small, or target tests still fail. Increase confidence if the patch touches the correct subsystem but omits gold files named in requirements. Use LLM-as-judge to compare issue requirements against the generated behavior and identify which requirement was only partially implemented. |
| `multi_file_coordination_failure` | Rule candidate: emit when gold patch is multi-file and generated patch misses gold files, misses integration/schema/fixture/generated paths, or only updates one side of a source/generated pair. Increase confidence if trajectory opened some gold files but did not edit all required integration points. LLM-as-judge is useful to explain the missed coordination path. |
| `wrong_subsystem_targeted` | Rule candidate: emit when `wrong_files_touched`, no gold overlap, production code not touched, tests-only patch, or edits are concentrated in a different top-level module. Increase confidence if trajectory never opened gold files. Use path heuristics first; use LLM-as-judge for cases where alternative valid solutions may legitimately touch different files. |
| `framework_api_misunderstanding` | Rule candidate only when eval/logs show framework-specific errors, imports, API misuse, type errors, or failed tests around framework conventions. Use LLM-as-judge by giving the relevant issue requirement, generated diff snippet, failing error, and gold patch snippet. This category is not reliably script-only because the failure is semantic. |
| `patch_application_or_editing_failure` | Deterministic when patch application, parsing, build, or syntax checks fail. Emit directly if `patch_application_or_editing_failure` or `syntax_or_parse_error` is present. LLM-as-judge is usually unnecessary except to distinguish malformed editing from a deeper code misunderstanding. |
| `insufficient_generated_patch` | Rule candidate: emit when patch is empty/tiny, too small relative to gold, missing required interfaces/files, or fails all target tests despite touching very little code. Increase confidence if issue requirements are broad but generated patch only changes one superficial line. LLM-as-judge can confirm whether the small patch could plausibly satisfy the requirements. |
| `test_expectation_misunderstood` | Rule candidate: emit when failing `FAIL_TO_PASS` tests have clear assertion mismatches, expected-vs-actual output, signature mismatches, or edge-case names that map to issue requirements. Use LLM-as-judge to connect the failing assertion to the requirement and decide whether the model implemented the wrong behavior rather than merely incomplete behavior. |
| `environment_or_artifact_gap` | Deterministic for missing artifacts: emit when output, patch, trajectory, logs, or result maps are missing or inconsistent. Do not use LLM-as-judge as the primary detector; a script can reliably report the gap. LLM can optionally explain how the gap limits confidence in other categories. |

## LLM-as-Judge Output Contract

When used, the judge should not replace deterministic signals. It should consume them and return a bounded schema:

```json
{
  "primary_cause": "multi_file_coordination_failure",
  "secondary_causes": ["incomplete_implementation"],
  "confidence": "high",
  "evidence": [
    "Gold patch updated API route, schema, and fixture files.",
    "Generated patch changed only the route handler.",
    "FAIL_TO_PASS tests for schema validation still failed."
  ],
  "not_enough_information": false
}
```

Recommended confidence rules:

- `high`: deterministic signals and semantic review agree.
- `medium`: deterministic signals are strong but semantic review has plausible alternatives.
- `low`: only weak signals are present or artifacts are incomplete.
