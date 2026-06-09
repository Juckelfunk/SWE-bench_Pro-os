# LLMs and Local Results

Paper source: `2509.16941v2.pdf`, "SWE-Bench Pro: Can AI Agents Solve Long-Horizon Software Engineering Tasks?", arXiv v2 from 2025-11-14.

## LLMs Tested in the Paper

- Claude Sonnet 4.5
- Claude Sonnet 4
- Claude Haiku 4.5
- Claude Opus 4.1
- OpenAI GPT-5 (high)
- OpenAI GPT-5 (medium)
- OpenAI GPT-OSS 120B
- OpenAI GPT-OSS 20B
- OpenAI GPT-4o
- Gemini 2.5 Pro Preview
- Kimi K2 Instruct
- SWE-Smith-32B
- Qwen-3 32B

## Paper Results

| Model | Public Resolve, Table 1 | Commercial Resolve, Table 2 | Public Resolve with $2 cap, Table 5 |
|---|---:|---:|---:|
| Claude Sonnet 4.5 | 43.6% | - | - |
| Claude Sonnet 4 | 42.7% | 9.1% | 17.6% |
| Claude Haiku 4.5 | 39.5% | - | - |
| Claude Opus 4.1 | - | 17.8% | 22.7% |
| OpenAI GPT-5 (high) | 41.8% | 15.7% | 25.9% |
| OpenAI GPT-5 (medium) | - | 14.9% | 23.3% |
| OpenAI GPT-OSS 120B | 16.2% | - | - |
| OpenAI GPT-OSS 20B | - | - | 16.2% |
| OpenAI GPT-4o | - | 3.6% | 4.9% |
| Gemini 2.5 Pro Preview | - | 10.1% | 13.5% |
| Kimi K2 Instruct | 27.7% | - | - |
| SWE-Smith-32B | - | - | 6.8% |
| Qwen-3 32B | - | - | 3.4% |

## Repository Results

These values were calculated from `traj/*/eval_results.json`. The JSON files contain one `true`/`false` value per instance; the percentage is `true / total`.

| Repository run | Solved | Total | Resolve |
|---|---:|---:|---:|
| `traj/claude-45sonnet-10132025` | 319 | 730 | 43.70% |
| `traj/claude-4sonnet-10132025` | 240 | 562 | 42.70% |
| `traj/claude-opus-4-1-paper` | 206 | 891 | 23.12% |
| `traj/claude-sonnet-4-paper` | 166 | 663 | 25.04% |
| `traj/gemini-2-5-pro-preview-paper` | 105 | 955 | 10.99% |
| `traj/gpt-4o-paper` | 36 | 619 | 5.82% |
| `traj/gpt-5-250-turns-10132025` | 265 | 729 | 36.35% |
| `traj/gptoss-paper` | 118 | 728 | 16.21% |
| `traj/kimi-k2-instruct-10132025` | 202 | 729 | 27.71% |

Note: `traj/README.md` distinguishes between `paper` runs with a $2 cost limit and dated leaderboard runs without a cost limit.

## S3 Download Check

The public S3 bucket `s3://scaleapi-results/swe-bench-pro/` is anonymously readable through HTTPS, so no AWS account was needed for listing or downloading public objects.

The local eval-only S3 sync is stored under `traj_s3/eval_only`. Current local inventory:

- 15 run folders
- 19,283 files
- 748 MiB on disk

Downloaded run folders:

| S3 run folder | Local files |
|---|---:|
| `claude-45haiku-10222025` | 1,457 |
| `claude-45sonnet-10132025` | 1,456 |
| `claude-4sonnet-10132025` | 1,115 |
| `claude-opus-4-1-paper` | 1,306 |
| `claude-sonnet-4-paper` | 1,242 |
| `gemini-2-5-pro-preview-250-turns-debug-nov17` | 1 |
| `gemini-2-5-pro-preview-250-turns-debug-oct22` | 1,452 |
| `gemini-2-5-pro-preview-paper` | 1,415 |
| `glm-4p5-10222025` | 1,457 |
| `gpt-4o-paper` | 1,215 |
| `gpt-5-250-turns-10132025` | 1,450 |
| `gpt-5-codex-debug-oct22` | 1,415 |
| `gpt-5-high-paper` | 1,437 |
| `gptoss-paper` | 1,430 |
| `kimi-paper` | 1,435 |

One official aggregate result file is present in the S3 download:

| S3 run | Local file | Solved | Total | Resolve |
|---|---|---:|---:|---:|
| `gemini-2-5-pro-preview-250-turns-debug-nov17/output/eval_results.json` | `traj_s3/eval_only/gemini-2-5-pro-preview-250-turns-debug-nov17/output/eval_results.json` | 142 | 728 | 19.51% |

Most S3 run folders contain per-instance evaluation outputs (`eval/.../_output.json`, `_patch.diff`, logs, and related files) rather than an official aggregate `eval_results.json`. Those per-instance files are downloaded, but they are not summarized as official resolve scores here.

## Missing Repository Results from the Public Leaderboard

Source: <https://labs.scale.com/leaderboard/swe_bench_pro_public>, accessed on 2026-06-09. The page says non-grayed-out runs use 250 turns and no cost limit; `*` means the mini-swe-agent harness.

The local runs for `claude-4-5-Sonnet`, `claude-4-Sonnet`, `gpt-5-2025-08-07 (High)`, `kimi-k2-instruct`, and `gpt-oss-120b` were counted as present in the repository.

| Model on the website | Website resolve |
|---|---:|
| gpt-5.4 (xHigh)* | 59.10±3.56 |
| Muse Spark* | 55.00±3.60 |
| claude-opus-4-6 (thinking)* | 51.90±3.61 |
| gemini-3.1-pro (thinking)* | 46.10±3.60 |
| claude-opus-4-5-20251101 | 45.89±3.60 |
| gemini-3-pro-preview | 43.30±3.60 |
| gpt-5.2-codex | 41.04±3.57 |
| claude-4-5-haiku | 39.45±3.55 |
| qwen3-coder-480b-a35b | 38.70±3.55 |
| minimax-2.1 | 36.81±3.55 |
| gemini-3-flash | 34.63±3.55 |
| gpt-5.2 | 29.94±2.15 |
| qwen3-235b-a22b | 21.41±2.25 |
| deepseek-v3p2 | 15.56±2.63 |
| gemma-3-27b-it | 11.38±2.15 |
| llama3-1-405b-instruct | 11.18±2.15 |
| glm-4.6 | 9.67±2.15 |
| llama4-maverick-17b-instruct | 5.24±1.24 |
| codestral-2405 | 1.51±1.51 |

Not counted as missing: website models with a matching local run (`claude-4-5-Sonnet`, `claude-4-Sonnet`, `gpt-5-2025-08-07 (High)`, `kimi-k2-instruct`, `gpt-oss-120b`). Some local `paper` runs are not listed on the current website, for example `gpt-4o-paper`, `gemini-2-5-pro-preview-paper`, and `claude-opus-4-1-paper`.
