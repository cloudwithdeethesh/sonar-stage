# Sonar Analysis & Evaluation – local prototype

## 1. What this project is
A clean, production-grade rebuild of the last two stages of a GitLab CI pipeline:
- **Stage 5 – SonarQube Analysis:** check inputs, run sonar-scanner, wait for the
  quality gate, prove what was scanned, hand the exact analysis to stage 6.
- **Stage 6 – Sonar Evaluation:** fetch that analysis's findings, classify them with
  an LLM, propose fixes, verify fixes, report on the merge request, store results,
  and decide pass/fail from SonarQube's own data.

A reference prototype of this pipeline exists elsewhere; treat it as a reference
for **interfaces only** – not as code to patch.

Work happens on a developer Mac with **sample code only**: no proprietary code,
internal hostnames, tokens or data. The result must drop into the production
`.gitlab-ci.yml` with configuration changes only.

## 2. Upstream inputs (from the Test Execution stage)
- `coverage.xml` – Cobertura, from `pytest --cov=src` (Python only today)
- `test-report.xml` – JUnit, run with `--continue-on-collection-errors`
- Source in `src/`; tests in `tests/`, AI-generated tests in `tests/unit-tests/`
Known quality issues to defend against:
- pytest runs with `|| true` → coverage can come from failing tests
- files can be missing or empty; coverage may cover fewer folders than are scanned
- tests are regenerated every run; names can collide (`test_<module>.py`)
- non-Python languages produce no Sonar-readable coverage

## 3. Interfaces to keep (from the production pipeline)
- **LLM:** OpenAI-compatible `POST {LLM_BASE_URL}/chat/completions`, Bearer token.
  Production: an OpenAI-compatible gateway hosting Qwen models. Local: Ollama `qwen2.5-coder:7b`.
- **SonarQube Web API:** `api/ce/task`, `api/issues/search`, `api/hotspots/search`,
  `api/measures/component`, `api/qualitygates/project_status`,
  `api/qualityprofiles/search`.
- **GitLab API v4:** MR diffs `GET .../merge_requests/:iid/diffs` (or `/changes`),
  existing discussions `GET .../discussions`, comments `POST .../notes`,
  inline `POST .../discussions` with `position` (base/start/head SHA, new_path, new_line).
- **Config via env vars** (keep these names):
  `SONAR_HOST_URL, SONAR_TOKEN, SONAR_PROJECT_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TOKEN,
  GITLAB_URL, GITLAB_TOKEN, CI_PROJECT_ID, CI_MERGE_REQUEST_IID, CI_COMMIT_SHA,
  CI_COMMIT_REF_NAME, CI_MERGE_REQUEST_DIFF_BASE_SHA, MIN_SEVERITY, AUTO_COMMIT, MAX_FIXES`.
- **Dependencies:** Python standard library only (`urllib`, `json`, `ssl`, `sqlite3`,
  `subprocess`) to minimise runtime dependencies. Tests may use pytest.

## 4. Design requirements this project must satisfy
Each item addresses a failure mode commonly seen in early LLM-assisted code-review pipelines.

Correctness
1. The gate counts blockers from SonarQube's own data, never from an LLM's JSON — an LLM can downgrade or drop an issue.
2. On MR analyses, issues and hotspots are fetched scoped to the current PR/branch with analysis-id filters — never the whole project's main-branch issues.
3. The scan job must not be `allow_failure: true`; the evaluator must refuse to read a stale analysis.
4. On MR runs, a coverage failure upstream must not silently skip the Sonar analysis.
5. A JSON parse failure must not drop a whole batch of issues silently — each issue must get a classification or an explicit `llm_error` state.
6. Hotspots are fetched across all pages; recommendations are commented, considered for fixing, and counted in the gate.
7. Duplications and the `others` finding category are either evaluated or explicitly excluded with a reason.
8. SonarQube's MQR `impacts` are read alongside the deprecated `severity`; INFO-level issues must not be silently discarded.

Safety
9. Only fixes on an allow-list of rules are applied; multi-line diffs are allowed within a narrow window around the finding, but no whole-file rewrites.
10. Every fix is verified by re-running tests and re-scanning before it counts as applied; `[skip ci]` must not be used to hide results.
11. Auto-commit never targets `main` or any protected branch; verified fixes land on a new branch via an MR.
12. Push URLs must never embed a token; failed pushes must not print one. Use SSH or a credential helper (never put the token in the URL).
13. TLS certificate verification must stay enabled; a custom CA bundle must be supported when needed. Disabling verification lets the client trust any certificate — traffic is still TLS-encrypted, but to whoever intercepts the connection (man-in-the-middle risk), not the intended server.
14. Bot identity, coverage thresholds, and gate conditions live in config, not source; they must stay consistent with the configured quality gate.

Usability
15. Inline MR comments are posted only on lines that appear in the MR diff; otherwise a grouped summary note is used as a fallback.
16. Comments are de-duplicated across re-runs by the SonarQube issue key (embedded as a hidden marker).
17. Every run persists findings to the local store (see §7) for history, metrics, and future training data.

## 5. Target design

### Stage 5 – Analysis
1. **Input check:** fail clearly if `coverage.xml` / `test-report.xml` are missing,
   empty or unparsable; warn if covered files ⊄ `sonar.sources`.
2. **Scan:** sonar-scanner (pinned version + checksum, or Docker image by digest),
   `sonar.qualitygate.wait=true`, `sonar.python.version`, explicit sources/tests/exclusions.
   MR runs add `sonar.pullrequest.*` only if the edition supports it (detect via API).
3. **Hand-off:** read `.scannerwork/report-task.txt` → `ceTaskId` → poll `api/ce/task`
   → `analysisId`. Write `analysis.env` (dotenv artifact): `SONAR_ANALYSIS_ID,
   SONAR_CE_TASK_ID, SONAR_PR_KEY|SONAR_BRANCH`.
4. **Health check → `scan_health.json`:** profile + active-rule count per language,
   gate + conditions, files/ncloc indexed vs files in sources, coverage imported (y/n),
   CE warnings, edition/version, mode (MQR/Standard).

### Stage 6 – Evaluation
1. **Guard:** refuse to run without `SONAR_ANALYSIS_ID`, or if it is not the latest
   analysis for this branch/PR. Never evaluate stale data.
2. **Fetch (scoped):** issues + hotspots for this PR/branch, all pages, all statuses
   that are open. SonarQube is the **source of truth**.
3. **Triage before LLM:** severity/impact threshold, rule allow-list for auto-fix,
   "in MR diff?" flag (from GitLab diff), file size limit. Every issue gets a reason.
4. **Classify (LLM):** per issue → `true_positive | false_positive | needs_review`
   + one-line reason. Small batches; JSON-schema validated; 1 retry; then `llm_error`.
   Redact secrets from code context before sending.
5. **Propose fix (LLM):** only true positives on the allow-list → **unified diff**
   (multi-line). Reject diffs touching other files or lines outside a window.
6. **Verify (sandbox):** apply in a temp git worktree → run tests → re-scan →
   accept only if target issue gone AND no new issues AND no newly failing tests.
   Otherwise discard → `suggested`.
7. **Reconcile:** every SonarQube issue/hotspot ends in exactly one state:
   `fixed_verified | suggested | false_positive | needs_review | skipped(reason) |
   below_threshold | llm_error`. Counts must add up or the job fails.
8. **Gate:** fail MR if any BLOCKER/CRITICAL (or MQR HIGH+ impact on Security/
   Reliability), or any `TO_REVIEW` hotspot with HIGH probability, is not
   `fixed_verified`. Computed from SonarQube data, never from LLM output.
9. **Deliver:**
   - MR: inline discussion only on diff lines; otherwise one grouped summary note.
     De-duplicate using the **SonarQube issue key** embedded as a hidden marker.
   - Default **suggest-only**. With `AUTO_COMMIT=true`: verified fixes only, max
     `MAX_FIXES` (20), pushed to a **new branch + new MR**, never to main/protected branches.
   - Artifacts: `evaluation_report.json`, `scan_health.json`, MR summary markdown.
10. **Store:** SQLite `findings` table – one row per issue per run (see §7).

## 6. Security & DevOps requirements (non-negotiable)
- **Secrets:** tokens only from env/masked CI vars; never printed; never in URLs or
  command lines (use `GIT_ASKPASS`/credential helper or header auth). Scrub logs.
- **Least privilege:** Sonar token = project analysis/browse only; GitLab token = `api`
  scope on this project; bot account cannot push to protected branches.
- **TLS:** verify certificates; support a custom CA bundle (`REQUESTS_CA_BUNDLE`/
  `SSL_CERT_FILE`) instead of disabling verification.
- **Data leaving the runner:** only code snippets around findings, secrets redacted,
  size-capped; log what was sent (hashes, not content).
- **Prompt-injection safety:** code and comments are untrusted input. LLM output is
  only ever parsed as schema-validated JSON/diff; never executed; diffs path-checked.
- **Supply chain:** pin scanner/tool versions; verify checksums; no `pip install` at runtime.
- **Idempotent & re-runnable:** same analysis → same comments (dedupe), no duplicate commits.
- **Timeouts & limits:** per-call timeouts, max issues per run, max LLM calls,
  overall job budget; degrade to "suggest-only, partial" with a clear message.
- **Observability:** structured JSON logs, run id, counts per state, timings,
  LLM token usage; exit codes: 0 pass, 1 gate failed, 2 config/input error, 3 infra error.
- **Fail-safe:** if anything is uncertain (stale analysis, reconcile mismatch,
  infra error on MR) → fail closed on MRs, advise-only on pushes.

## 7. Findings store (data model)
`findings(run_id, created_at, project_key, branch, pr_key, analysis_id, issue_key,
kind[issue|hotspot], rule, file, line, sonar_severity, sonar_impacts, in_diff,
llm_classification, llm_reason, fix_status, verified, tests_passed, rescan_clean,
model, prompt_version, tokens_in, tokens_out, latency_ms)`
`runs(run_id, started_at, finished_at, pipeline_id, commit_sha, gate_result,
counts_json, health_json)`
Metrics in the report: issues found, % per state, verified-fix rate,
false-positive rate, LLM error rate, time per issue.

## 8. Local stack
- SonarQube Community Build **25.1.0.102122**, **Standard Experience** mode, on `http://localhost:9000`
  Project key: `Sonar-Stage-Sample`
- sonar-scanner via `sonarsource/sonar-scanner-cli` (container → `http://host.docker.internal:9000`)
- LLM during development: **OpenAI API** (OpenAI-compatible endpoint; no interface change)
- LLM for final validation: **Ollama `qwen2.5-coder:7b`** on `http://localhost:11434/v1`
- Python 3.12+, pytest, pytest-cov
- CI: **gitlab.com** with a **local `gitlab-runner`**

## 9. Layout
```
sonar_stage/
  common/      config.py (env), http.py (TLS, retries, timeouts), log.py, redact.py
  analysis/    input_check.py, scan.py, handoff.py, health.py      # stage 5
  evaluation/  fetch.py, triage.py, classify.py, propose.py,
               verify.py, reconcile.py, gate.py, deliver.py         # stage 6
  llm/         client.py, prompts/, schemas/
  gitlab/      client.py (diffs, discussions, notes, dedupe)
  store/       sqlite.py, schema.sql
  report/      summary_md.py, report_json.py
sample_project/  src/ with planted issues, tests/, expected_issues.json
tests/           unit tests (all network mocked) + e2e (local stack)
ci/              gitlab-ci.sonar.yml (drop-in jobs)
```

## 10. Milestones (do one at a time; explain changes; ask before installing anything)
1. Sample project with planted issues + tests; scan; write `expected_issues.json`.
2. Common layer: config, HTTP (TLS/timeouts/retries), structured logs, redaction.
3. Stage 5: input check, scan wrapper, analysis-id hand-off, health check.
4. Stage 6 core: guarded fetch (scoped), triage, reconcile, gate – **no LLM yet**.
5. LLM classify + propose (Ollama), schema validation, retries, redaction.
6. Verify loop in a temp worktree (re-test + re-scan); suggest-only default.
7. Delivery: MR comments with dedupe + fallback; safe auto-commit to a new branch.
8. Findings store + JSON report + metrics.
9. gitlab.com pipeline running stages 5–6 via a local gitlab-runner; failure-mode tests
   (stale analysis, LLM down, bad JSON, token missing, scan fails).

## 11. Coding rules
- Small modules, type hints, docstrings; no network in unit tests (mock).
- Every acceptance criterion in §5–§6 has at least one test.
- One clear error message per failure; never print secrets.

## 12. Working agreement
- **One milestone per session.** Finish it before starting another. _Why:_ keeps context small and each session reviewable.
- **Plan first.** Use `/start-milestone N` before writing any code. _Why:_ catches design mistakes while they're still cheap.
- **One branch per milestone.** Name: `mN-short-name` (e.g. `m1-sample-project`). _Why:_ each milestone is an independent, reviewable unit.
- **Small commits, Conventional Commits.** `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`. Scope optional (e.g. `feat(stage5):`). _Why:_ readable history; enables future changelog automation.
- **Tests pass before every commit.** `/finish-milestone` enforces this with `pytest`. Exit code 5 (no tests collected) is OK on scaffolding-only milestones. _Why:_ `main` is always a working baseline.
- **Merge via MR only; no direct pushes to `main`.** _Why:_ matches the production pipeline's review workflow.
- **No secrets ever.** Tokens, keys, `.env*` files stay out of commits, logs, and URLs. Enforced by `.gitignore`, Claude Code's deny list, and the secret scan in `/finish-milestone`. _Why:_ §6, non-negotiable.
- **Every change is explained.** A short "what and why" before each file write or significant command. _Why:_ matches §10 — "do one at a time; explain changes; ask before installing anything."
