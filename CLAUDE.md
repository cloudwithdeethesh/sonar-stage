# Sonar Recommendation – local mirror

## 1. What this project is
A local mirror of a 4-stage GitLab CI pipeline whose last two stages turn
SonarQube results into AI recommendations on merge requests.

Goal, in order:
1. **Mirror first:** reproduce the reference pipeline's behaviour as closely as
   possible, run it, and record what it produces (the baseline).
2. **Improve second:** fix the known gaps (§6), one milestone at a time, each
   compared against the baseline.

Sample code only. No employer code, names, hostnames, tokens or data in this repo.

## 2. Pipeline (mirror of the reference)
| # | Stage | Job | In the reference | Here |
|---|---|---|---|---|
| 1 | Unit_Test_Generation | – | AI generates tests | **Replaced:** tests are written by Claude Code and committed |
| 2 | Unit_Test_Execution | `run_tests` | runs tests, gates total coverage | same; produces `coverage.xml` (Cobertura) + `test-report.xml` (JUnit), artifacts `when: always` |
| 3 | Quality_Gate | `sonarqube_scan` | sonar-scanner, advisory | same; `allow_failure: true` |
| 4 | Sonar_Recommendation | `sonar_recommendation` | `QC/sonar_evaluator.py`, dry-run by default | same; writes `sonar-recommendation-report.json` |

Workflow rules (same as reference): run on MR events, pushes and manual web runs;
skip the push pipeline when an MR is open for the branch; skip `[skip ci]` commits.

## 3. Mirror rules – `QC/sonar_evaluator.py` (reference behaviour to reproduce)
Keep this structure, function names and order:
- **Config from env:** LLM URL/token/model; `SONAR_HOST_URL`; `SONAR_TOKEN` with a
  separate optional read token (`SONAR_READ_TOKEN`) for GET endpoints;
  `SONAR_PROJECT_KEY`; GitLab URL/token/project/MR IID/SHA/branch; bot name/email.
- **Run modes:** `DRY_RUN` (default ON: no MR posts, no commits), `OFFLINE_FIXTURES_DIR`
  (read captured JSON instead of calling SonarQube), `AUTO_FIX` (default OFF),
  `REPORT_PATH` (default `sonar-recommendation-report.json`).
- **TLS:** `_build_ssl_context()` verifies by default; CA bundle from env; an explicit
  insecure flag for local debugging only, logged loudly.
- **Severity:** `SEVERITY_ORDER = BLOCKER 5 … INFO 1`, `MIN_SEVERITY = MINOR`.
- **SonarQube API:** `sonar_api()`; `fetch_sonar_issues()` (paged, 500/page,
  statuses OPEN,CONFIRMED,REOPENED); `fetch_sonar_metrics()`; `fetch_sonar_hotspots()`
  (status TO_REVIEW); `fetch_sonar_duplications()`.
- **LLM:** `call_llm(prompt, code_context)` – OpenAI-compatible `/chat/completions`,
  Bearer token, `max_tokens` 4096, temperature 0.2; if no token: skip LLM, still report.
- **Source helpers:** `read_source_file()` (context window ±5 lines),
  `_normalize_ws()`, `apply_fix_to_file()` (exact then whitespace-normalised match,
  multi-line, dry-run aware, structured result).
- **Prompts:** `EVALUATION_PROMPT`, `HOTSPOT_PROMPT`, `DUPLICATION_PROMPT` with the
  same JSON fields (issue_key, file, line, rule, severity, explanation,
  original_line, fixed_line, recommendation; hotspots: assessment
  VULNERABLE|SAFE|NEEDS_REVIEW).
- **Parsing:** `_strip_code_fences()`, `_extract_first_json_array()`,
  `parse_llm_json_array()` (layered, salvages objects, never raises).
- **Flow:** `categorize_issues()` → `evaluate_issues_with_llm()` in batches of 15 with
  one JSON-only retry → hotspots evaluated → duplications skipped → inline comments
  (skipped in dry-run) → optional auto-fix → MR summary (`generate_mr_summary()`) →
  `_write_report()` → exit 0 in dry-run / advisory.
- **GitLab:** `gitlab_api()`, `post_mr_comment()`, `post_mr_inline_comment()` (position
  with base/start/head SHA), `commit_fixes()`.

## 4. Allowed differences (only these)
- Stage 1: hand-written tests instead of AI generation.
- No shared template include; jobs are defined inline in `.gitlab-ci.yml`.
- Public images, pinned versions (e.g. `python:3.12-slim`,
  `sonarsource/sonar-scanner-cli:<pinned>`), tag `local-mac`.
- LLM: OpenAI API during development (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_TOKEN`), final
  check with Ollama/Qwen. **No token-refresh stage.**
- Bot identity and URLs from CI variables, never hardcoded.

## 5. Local stack
- SonarQube Community Build **25.1.0.102122**, **Standard Experience**, Docker,
  `http://localhost:9000` (from jobs: `http://host.docker.internal:9000`).
  Project key `Sonar-Stage-Sample`; Python profile extended from Sonar way, all
  rules active.
- gitlab.com private repo + project runner in Docker on the Mac, tag `local-mac`.
- CI/CD variables: `SONAR_HOST_URL`, `SONAR_PROJECT_KEY`, `SONAR_TOKEN` (masked),
  `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TOKEN` (masked).
- `sonar-project.properties`: `sonar.python.coverage.reportPaths=coverage.xml`,
  `sonar.python.xunit.reportPath=test-report.xml`.

## 6. Known gaps (fix only after the baseline is recorded)
1. Gate counts blockers from LLM output, not SonarQube data.
2. Recommender reads the latest analysis, not the one this pipeline produced.
3. On MRs, issues are not filtered to the MR's changed lines.
4. Hotspots: first page only; not included in blocking.
5. Batches of 15 with `max_tokens` 4096 can truncate; a failed batch is dropped.
6. Inline comments on lines outside the diff fail silently; no de-duplication.
7. Project key and paths hardcoded.
8. Push URL embeds the token (only relevant if auto-fix is ever enabled).
Target delivery (agreed scope): **recommendations only, no fixing**; one inline thread
per finding on the developer's MR + one summary comment (counts by severity, findings
table, verdict); blocking via "open threads must be resolved"; no database.

## 7. Milestones
0b. [x] Runner + placeholder 4-stage pipeline green on gitlab.com.
1.  Sample app in `src/`, dirty samples in `samples/`, hand-written tests
    (~70–85% coverage); `coverage.xml` + `test-report.xml` produced.
2.  Mirror stages 2–4 (§3–§4); pipeline green in dry-run.
3.  Baseline run: save the report, scan results and a short BASELINE.md.
4+. One gap from §6 per milestone, compared against the baseline.

## 8. Working agreement
- One milestone per session; plan first (`/start-milestone N`, plan mode).
- One branch per milestone (`mN-short-name`); Conventional Commits; small commits.
- Tests pass before committing; merge via MR only.
- No secrets in commits, logs or URLs.
- Explain each change before making it; ask before installing anything.
