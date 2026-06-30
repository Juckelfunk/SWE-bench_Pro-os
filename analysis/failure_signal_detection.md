# Failure Signal Detection

This file lists failure categories that can be detected from SWE-Bench Pro artifacts when the issue text, requirements, gold patch, generated patch, eval output, and trajectory are available.

The important distinction is:

- **Mechanical failure signals** are measurable facts or close-to-facts. These are good targets for deterministic scripts.
- **Reviewed failure causes** are higher-level explanations. They can often be suggested from signals, but usually require semantic review to confirm.

Current implementation:

- Script: `analysis/failure_signal_analyzer.py`
- Patch checker: `analysis/patch_application_checker.py`
- Repository setup: `scripts/prepare_failure_analysis_repos.py`
- Detailed output: `analysis/output/failure_signals.csv`
- Summary output: `analysis/output/failure_signal_summary.csv`
- Markdown report: `analysis/output/failure_signal_report.md`, including overall, per-model/run, and per-repository signal breakdowns.
- Scope: low-to-medium-complexity mechanical signals, including explicit interface checks and structured trajectory signals.
- The analyzer is offline: it reads existing benchmark/eval artifacts and does not build projects, run tests, or generate new compiler diagnostics.
- Validation: signal failure rates are computed only where an official `traj/*/eval_results.json` result map is available.
- Path policy: `tests_only_patch` is strict and only uses benchmark `test_patch` files; `production_code_not_touched` is broader and also treats obvious test paths, docs, and generated/vendor files as non-production.
- Trajectory path extraction is language-agnostic but heuristic: it depends on path-like tokens in actions or `[File: ...]` metadata, filters obvious value ranges such as `min/max` and `-inf/+inf`, and may miss unusual agent formats or single-file names without directories.
- Required-interface extraction is conservative: it uses explicit `Name:` fields, HTTP routes, and code-like backticked symbols from the problem statement, while filtering obvious examples, URLs, placeholder paths, literals, and exception names. It should still be read as medium-confidence evidence rather than semantic proof.
- Trajectory path: use `--trajectory-root` for a root containing `<run>/traj/<instance_id>/*.traj`; it defaults to `--eval-root`.
- Missing or malformed trajectories set `trajectory_available=0` and do not emit behavioral trajectory signals.
- Patch application checks use full bare clones under `analysis/repos/` by default. Run `python3 scripts/prepare_failure_analysis_repos.py` once to clone the public repositories, fetch dataset commits that are no longer advertised by branch refs, and write `analysis/output/repo_availability.json`.
- Missing repositories or base commits set `patch_application_check_available=0`; they do not emit `patch_application_or_editing_failure`.
- CLI progress is printed every 100 attempts by default; configure the interval with `--progress-every N` or disable it with `--progress-every 0`.
- Use `--skip-trajectory-signals` to avoid loading trajectory files and `--skip-repo-checks` to avoid repository-backed patch application checks.
- Attempts are sequential by default; use `--workers N` to process attempts in parallel while the parent process retains progress reporting and CSV writes.

## Mechanical Failure Signals

| Implemented | Signal | Pattern-based | Meaning | Required inputs | Detection robustness | Script complexity |
|---|---|---|---|---|---|---|
| [x] | `no_patch` | No | No generated patch artifact exists for the attempt. | Agent artifacts | Very high | Low |
| [x] | `empty_or_tiny_patch` | No | Generated patch is empty or below a small LOC threshold. | Generated patch | Very high | Low |
| [x] | `patch_application_or_editing_failure` | Partial | Patch is malformed, cannot be applied, or produces mechanically inconsistent edits. | Generated patch, base repo | High when repo cache is available | Medium |
| [x] | `syntax_or_parse_error` | Yes | Failed eval diagnostics or trajectory observations report syntax, parse, import, compile, or equivalent language-level failure. | Eval output/logs, trajectory observations | Medium; artifact- and pattern-dependent | Medium |
| [x] | `test_failure_available` | No | Public eval output contains at least one failed test. | Eval output | Very high | Low |
| [x] | `missing_output` | No | No eval output artifact is available for the attempt. | Eval artifacts | Very high | Low |
| [x] | `wrong_files_touched` | No | Generated patch touches files with no overlap with gold patch files. | Gold patch, generated patch | High as a mechanical overlap signal | Low |
| [x] | `partial_file_overlap` | No | Generated patch touches some, but not all, gold patch files. | Gold patch, generated patch | High as a mechanical overlap signal | Low |
| [x] | `all_gold_files_touched` | No | Generated patch touches every file changed by the gold patch. | Gold patch, generated patch | Very high | Low |
| [x] | `missing_gold_files` | No | One or more gold patch files are absent from the generated patch. | Gold patch, generated patch | Very high | Low |
| [x] | `extra_files_touched` | No | Generated patch changes files not present in the gold patch. | Gold patch, generated patch | Very high | Low |
| [x] | `generated_patch_too_small` | No | Generated patch LOC is far smaller than gold patch LOC. | Gold patch, generated patch | Medium as a heuristic size signal | Low |
| [x] | `generated_patch_too_large` | No | Generated patch LOC is far larger than gold patch LOC. | Gold patch, generated patch | Medium as a heuristic size signal | Low |
| [x] | `large_refactor` | No | Generated patch changes far more files or LOC than the gold patch. | Gold patch, generated patch | Medium as a heuristic breadth signal | Low |
| [x] | `multi_file_gold_patch` | No | Gold patch changes more than one file. | Gold patch | Very high | Low |
| [x] | `single_file_gold_patch` | No | Gold patch changes exactly one file. | Gold patch | Very high | Low |
| [x] | `generated_patch_multi_file` | No | Generated patch changes more than one file. | Generated patch | Very high | Low |
| [x] | `production_code_not_touched` | Yes | Generated patch avoids production-code paths and only touches non-production areas. | Generated patch, repo path rules | Medium; generic path-rule heuristic | Medium |
| [x] | `tests_only_patch` | No | Generated patch only changes files from the benchmark `test_patch`. | Generated patch, benchmark `test_patch` | Very high | Low |
| [x] | `docs_only_patch` | Yes | Generated patch only changes documentation files. | Generated patch, path rules | High | Low |
| [ ] | `config_only_patch` | N/A | Generated patch only changes config/build/metadata files. | Generated patch, path rules | N/A; not implemented | N/A |
| [x] | `generated_or_vendor_churn` | Yes | Generated patch changes generated, vendor, lockfile, or bundled files. | Generated patch, path rules | Medium; generic path-rule heuristic | Medium |
| [x] | `required_interface_missing` | Yes | Issue explicitly names an interface, method, class, endpoint, or function that is absent from the generated patch. | Problem statement, generated patch | Medium; conservative extraction and patch-string matching | Medium-high |
| [x] | `required_test_target_still_failing` | No | A `FAIL_TO_PASS` test is still failing after applying the generated patch. | `FAIL_TO_PASS`, eval output | Very high when structured eval output is available | Medium |
| [x] | `regression_test_failed` | No | A `PASS_TO_PASS` test fails after applying the generated patch. | `PASS_TO_PASS`, eval output | Very high when structured eval output is available | Medium |
| [x] | `new_tests_not_exercised_or_missing_output` | No | Expected target tests are absent from eval output or no useful output is available. | `FAIL_TO_PASS`, eval output | High for missing target-test evidence | Medium |
| [x] | `trajectory_no_submission` | No | Trajectory never reaches a submit/final-answer action. | Trajectory | High when trajectory metadata is structured | Medium |
| [x] | `trajectory_stuck_loop` | No | Trajectory repeats similar actions or observations beyond a fixed threshold. | Trajectory | Medium; heuristic repeated-action fingerprint | Medium |
| [x] | `trajectory_tool_error` | Yes | Trajectory records tool failures, command errors, or API/tool invocation errors. | Trajectory | Medium-high; pattern- and format-dependent | Medium |
| [x] | `trajectory_timeout_or_turn_limit` | Yes | Run ends due to timeout, turn limit, or equivalent budget exhaustion. | Trajectory/run metadata | High when termination metadata is logged | Low-medium |
| [x] | `trajectory_never_opened_gold_files` | Yes | Agent never inspected files changed by the gold patch. | Trajectory, gold patch | Medium; path-extraction heuristic | Medium-high |
| [x] | `trajectory_opened_but_did_not_edit_gold_files` | Yes | Agent inspected gold files but did not modify them. | Trajectory, gold patch, generated patch | Medium-high when paths are extractable | Medium-high |
| [x] | `trajectory_edited_wrong_subsystem` | Yes | Agent repeatedly inspected or edited paths outside the gold-patch subsystem. | Trajectory, gold patch, path rules | Medium; subsystem heuristic | Medium-high |
| [x] | `eval_passed_but_result_false_mismatch` | No | Non-empty structured eval output has no failed tests, but the result map marks the instance unresolved. | Eval result map, eval output | High for mismatch detection | Medium |

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

## Current Detection Details: Mechanical Failure Signals

Common preprocessing:

1. Load the benchmark row by `instance_id` from `helper_code/sweap_eval_full_v2.jsonl`.
2. Parse `patch` as the gold patch and the generated `_patch.diff` as the model patch.
3. Extract changed files and changed LOC from both patches.
4. Load `_output.json`; include sibling `*.log` files only as diagnostic text for syntax/import detection.
5. Load official result maps from `traj/*/eval_results.json` when available.
6. Optionally load trajectory messages/actions and normalize them into opened files, edited files, tool errors, submit state, repeated-action counts, diagnostics, and termination state.
7. Optionally check patch application against bare repository clones under `analysis/repos/`.

| Signal | Current detector |
|---|---|
| `no_patch` | Emits when `_patch.diff` is absent. If `_patch.diff` exists but is empty, this signal stays false; the empty file is reported by `empty_or_tiny_patch` and, when repo checks are enabled, by `patch_application_or_editing_failure` with `patch_application_error_type=empty_patch`. |
| `empty_or_tiny_patch` | Counts changed diff lines in the generated patch, ignoring `+++` and `---` headers. Emits for a present patch with changed LOC `< 10`. |
| `patch_application_or_editing_failure` | Uses `GitApplyChecker` when repo checks are enabled. Binary hunks are stripped, the patch is parsed with `git apply --numstat -z`, then checked against the benchmark `base_commit` in a temporary index with `git apply --cached --check`. Emits only when the check is available and fails. Error types are normalized to `empty_patch`, `malformed_patch`, `context_mismatch`, `missing_path`, `path_conflict`, or `apply_error`; missing repositories or base commits are recorded as unavailable, not failures. |
| `syntax_or_parse_error` | Searches only existing failed eval diagnostics, sibling `*.log` text, and trajectory observations for syntax/import/compile markers; it does not build the project or run a parser/compiler itself. If those artifacts are missing or contain no diagnostic text, this signal has no evidence to emit. Patterns checked: `SyntaxError:`, `ParseError:`, `ImportError:`, `ModuleNotFoundError:`, `compilation failed`, `compile error`, `cannot compile`, `module not found`, TypeScript `error TS<digits>:`, Java-like `error: cannot find symbol`, and linker-style `undefined reference`. If `_output.json` contains a non-empty structured test list and every test is `PASSED`, the signal is suppressed so fixed transient trajectory errors do not count. |
| `test_failure_available` | Parses `_output.json` only. Emits when `tests` is a list and at least one test object has `status != "PASSED"`. If structured eval output is missing or malformed, this signal has no evidence to emit and `missing_output` records the artifact gap instead. There is no log-only fallback for this signal. |
| `missing_output` | Emits when `_output.json` is absent, unreadable, invalid JSON, or does not contain a list-valued `tests` field. Empty `tests: []` is structured output, not missing output. |
| `wrong_files_touched` | File-overlap signal. Uses `overlap = gold_files & generated_files`. Emits when generated files are non-empty and `overlap` is empty. This is the "no gold-file overlap at all" case. |
| `partial_file_overlap` | File-overlap signal. Uses `missing = gold_files - generated_files`. Emits when `overlap` is non-empty and `missing` is also non-empty. This is the "some correct files, but not all gold files" case. |
| `all_gold_files_touched` | File-overlap signal. Emits when `gold_files` is non-empty and `missing` is empty. This is the "complete gold-file coverage" case and is a positive coverage signal, not a failure by itself. |
| `missing_gold_files` | File-overlap signal. Emits when `missing = gold_files - generated_files` is non-empty. This is a broad "gold coverage incomplete" flag; it overlaps with `wrong_files_touched` and `partial_file_overlap`. The CSV records only the missing count, not the file list. |
| `extra_files_touched` | File-overlap signal. Uses `extra = generated_files - gold_files`. Emits when `extra` is non-empty. This is independent of gold coverage: a patch can touch all gold files and still have extra files. The CSV records only the extra count, not the file list. |
| `generated_patch_too_small` | Emits when `gold_loc >= 20` and `generated_loc < max(10, int(0.25 * gold_loc))`. LOC means changed diff lines excluding file headers. |
| `generated_patch_too_large` | Emits when `generated_loc > max(50, 3 * gold_loc)`. |
| `large_refactor` | Emits when generated file count is greater than `max(2 * gold_file_count, gold_file_count + 5)` or generated LOC is greater than `max(500, 4 * gold_loc)`. |
| `multi_file_gold_patch` | Emits when the gold patch changes more than one file. |
| `single_file_gold_patch` | Emits when the gold patch changes exactly one file. |
| `generated_patch_multi_file` | Emits when the generated patch changes more than one file. |
| `production_code_not_touched` | Emits when generated files are non-empty and every generated file is classified as non-production. Non-production means the path is in benchmark `test_patch`, matches test path patterns, matches docs patterns, or matches generated/vendor patterns. Test path patterns checked: path parts `test`, `tests`, `spec`, `specs`, or `__tests__`; filenames starting with `test_` or `spec_`; filenames ending in `_test.py`, `.test.js`, `.spec.js`, `.test.ts`, `.spec.ts`, `.test.tsx`, or `.spec.tsx`. Config/build metadata is intentionally not treated as non-production. |
| `tests_only_patch` | Emits only when generated files are non-empty, benchmark `test_patch` contains files, and every generated file is a subset of the benchmark `test_patch` file set. It does not use generic `test/` path-name patterns. |
| `docs_only_patch` | Emits when generated files are non-empty and every generated path is documentation. Patterns checked: path parts `doc`, `docs`, or `documentation`; root filename starting with `README`; extensions `.md`, `.rst`, `.asciidoc`, or `.adoc`. |
| `config_only_patch` | Not implemented. No detector emits this signal today. |
| `generated_or_vendor_churn` | Emits when any generated path looks generated, vendored, bundled, or lockfile-like. Patterns checked: path parts `vendor`, `vendors`, `node_modules`, `dist`, `build`, `coverage`, `generated`, or `gen`; filenames ending in `.min.js`, `.min.css`, `.snap`, or `.lock`; filenames containing `generated`. |
| `required_interface_missing` | Extracts explicit required interfaces from the problem statement, then emits when at least one extracted interface is absent from the generated patch. Extraction patterns checked: `Name: <symbol>`, HTTP routes after `GET|POST|PUT|PATCH|DELETE`, and backticked code symbols or paths. Backticked symbols are ignored on lines containing example/input context terms: `e.g`, `example(s)`, `such as`, `like`, `format(s)`, `input(s)`, `invalid`, or `malformed`. Filters also reject URLs, `<placeholder>` values, booleans/null-like literals, exception/error class names, negative/range-like values, and weak example-looking symbols. Patch matching accepts either the full interface string or, for dotted/colon names, the final suffix as a word. |
| `required_test_target_still_failing` | Normalizes `FAIL_TO_PASS` from the dataset and failed test names from `_output.json` with whitespace collapsing. Emits when their exact normalized intersection is non-empty. If structured eval output is missing or malformed, this signal has no failed-test evidence to emit; `new_tests_not_exercised_or_missing_output` captures that gap for target tests. |
| `regression_test_failed` | Normalizes `PASS_TO_PASS` and failed test names with whitespace collapsing. Emits when their exact normalized intersection is non-empty. If structured eval output is missing or malformed, this signal has no failed-test evidence to emit. |
| `new_tests_not_exercised_or_missing_output` | Emits when the dataset has `FAIL_TO_PASS` targets and either output is missing/unstructured or none of those exact normalized target tests appear in `_output.json`. This signal is explicitly used to distinguish missing target-test evidence from observed target-test failures. |
| `trajectory_no_submission` | Requires a valid trajectory. If the trajectory is missing, malformed, or `--skip-trajectory-signals` is used, this behavioral signal stays false rather than treating the artifact gap as agent behavior. Emits when there is no `info.submission`, `info.exit_status` does not start with `submitted`, and no trajectory action starts with `submit`. |
| `trajectory_stuck_loop` | Requires a valid trajectory. If the trajectory is unavailable, this signal has no evidence to emit. Builds a consecutive action fingerprint from the first action word plus the first extracted path, or the first 80 lowercased action characters when no path is present. Emits when the same fingerprint repeats at least `5` times consecutively. |
| `trajectory_tool_error` | Requires a valid trajectory. If the trajectory is unavailable, this signal has no observation text or exit status to inspect. Counts action observations matching tool-error patterns, plus selected error exit statuses. Patterns checked: `command failed`, `command timed out`, `process/command exited/returned with code <nonzero>`, `non-zero exit/status`, `no such file or directory`, `file not found`, `permission denied`, `tool call/invocation error/failed`, and `invalid tool call/arguments`. Exit statuses containing `exit_error`, `exit_format`, or `exit_command_timeout` add one error. Emits when the count is greater than `0`. |
| `trajectory_timeout_or_turn_limit` | Requires a valid trajectory. If the trajectory is unavailable, this signal has no termination metadata to inspect. Emits when `info.exit_status` contains `exit_cost`, `exit_context`, or `exit_command_timeout`, or when the final trajectory text matches termination patterns. Patterns checked: cost/token/time/turn/step `limit` or `budget`, `max turns/steps/tokens`, `context window`, `command timeout(s)`, `timed out`, or `timeout`. |
| `trajectory_never_opened_gold_files` | Requires a valid trajectory, non-empty gold files, and at least one extracted opened path. If no trajectory or no opened paths are extractable, the signal stays false because missing parser coverage is not treated as proof that the agent never opened gold files. Opened files come from actions whose first word is `cat`, `sed`, `grep`, `rg`, `head`, `tail`, `nl`, or `less`, or actions containing `view`. Path patterns checked include repo-like slash paths with optional `/app/` or `./` prefixes; `[File: ...]` markers are also supported by the path extractor. Emits when no opened path overlaps a gold file. |
| `trajectory_opened_but_did_not_edit_gold_files` | Requires a valid trajectory. If no opened gold file can be extracted, this signal has no evidence to emit. Emits when at least one extracted opened path overlaps gold files but none of those opened gold files appear in the generated patch file set. |
| `trajectory_edited_wrong_subsystem` | Requires a valid trajectory. If edited/generated paths or gold subsystems cannot be extracted, this signal stays false. Edited files come from actions containing `str_replace_editor`, `apply_patch`, ` create `, ` edit `, or ` replace `, plus `[File: ...]` markers in `info` keys beginning with `edited_files`, plus generated patch files. Emits when at least `2` edited/generated files exist, none overlap gold files, and edited/generated top-level path components are disjoint from gold top-level path components. |
| `eval_passed_but_result_false_mismatch` | Requires both an official result map entry and structured `_output.json` evidence. Emits when the result map marks the attempt unresolved, `_output.json` has a non-empty structured test list, and none of those tests failed. If either artifact is missing, this signal has no mismatch evidence to emit. Empty `tests: []` is not treated as passed-looking evidence. |

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
