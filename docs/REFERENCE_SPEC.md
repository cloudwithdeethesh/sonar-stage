# Reference behaviour spec – `QC/sonar_evaluator.py`

This file describes, function by function, how the reference evaluator behaves.
The mirror implementation must follow it exactly: same names, signatures, order,
defaults, outputs and quirks (including the known gaps). Only the allowed
differences in CLAUDE.md Section 4 may change (LLM env names, bot identity env names).

## 1. Configuration (module level, read from env)
| Constant | Env var | Default |
|---|---|---|
| LLM_BASE_URL | `LLM_BASE_URL` | "" |
| LLM_TOKEN | `LLM_TOKEN` | "" |
| LLM_MODEL | `LLM_MODEL` | "" |
| SONAR_HOST | `SONAR_HOST_URL` | "" |
| SONAR_TOKEN | `SONAR_TOKEN` | "" |
| SONAR_READ_TOKEN | `SONAR_READ_TOKEN` | falls back to SONAR_TOKEN |
| SONAR_PROJECT_KEY | `SONAR_PROJECT_KEY` | "" |
| GITLAB_URL | `CI_SERVER_URL` | "https://gitlab.com" |
| GITLAB_TOKEN | `GITLAB_TOKEN` | "" |
| PROJECT_ID | `CI_PROJECT_ID` | "" |
| MR_IID | `CI_MERGE_REQUEST_IID` | "" |
| COMMIT_SHA | `CI_COMMIT_SHA` | "" |
| BRANCH_NAME | `CI_COMMIT_REF_NAME` | "" |
| SONAR_EVALUATOR_NAME | `SONAR_EVALUATOR_NAME` | "Sonar Recommender" |
| SONAR_EVALUATOR_EMAIL | `SONAR_EVALUATOR_EMAIL` | "sonar-recommender@noreply.local" |

Run modes:
- `DRY_RUN` = env `DRY_RUN` default "1"; true unless value (stripped) is in ("0","false","no","").
- `OFFLINE_FIXTURES_DIR` = env `OFFLINE_FIXTURES_DIR`, stripped, default "".
- `AUTO_FIX` = env `AUTO_FIX` stripped, true only if in ("1","true","yes").
- `REPORT_PATH` = env `REPORT_PATH`, default "sonar-recommendation-report.json".

## 2. `_build_ssl_context()` (no arguments) → `SSL_CTX` module constant
1. If env `INSECURE_TLS` (stripped) in ("1","true","yes"): print a warning that TLS
   verification is disabled (debug only), return a context with check_hostname False
   and CERT_NONE.
2. CA bundle = first set of env `CA_BUNDLE`, `SONAR_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`.
   If set and the file exists: print "TLS: verifying with CA bundle <path>" and
   return `ssl.create_default_context(cafile=...)`.
3. Otherwise print "TLS: verifying with system default trust store" and return the
   default context.
`SSL_CTX = _build_ssl_context()` is created once at import.

## 3. Severity
`SEVERITY_ORDER = {"BLOCKER":5,"CRITICAL":4,"MAJOR":3,"MINOR":2,"INFO":1}`,
`MIN_SEVERITY = "MINOR"`.

## 4. Offline fixtures – `_load_fixture(name)`
Return None if OFFLINE_FIXTURES_DIR is empty. Otherwise read
`<dir>/<name>` as JSON; on FileNotFoundError print a "fixture not found" warning and
return None; on any other error print a "fixture load error" warning and return None.

## 5. SonarQube API
### `sonar_api(endpoint, params=None)`
URL = `{SONAR_HOST}/api/{endpoint}`; if params, append `?k=v&k=v` (simple join, in
dict order). GET with headers `Authorization: Bearer {SONAR_READ_TOKEN}` and
`Accept: application/json`, `context=SSL_CTX`, timeout 60. Return parsed JSON.
On HTTPError: print "SonarQube API error: HTTP <code> on <endpoint>" and the first
300 chars of the response body; return None. On other exceptions: print the error;
return None.

### `fetch_sonar_issues()`
Print "Fetching SonarQube issues...". If fixture `issues.json` loads: take its
`issues` list, print "(offline) loaded N issues from fixture", return it.
Otherwise page through `issues/search` with params
`componentKeys`, `statuses="OPEN,CONFIRMED,REOPENED"`, `ps="500"`, `p=str(page)`,
`additionalFields="comments,rules"`. Stop when the response is None. Extend the list
with `issues`; print "Fetched page P: n issues (total: T)"; stop when
collected ≥ total or the page is empty; else next page. Return all issues.

### `fetch_sonar_metrics()`
Print "Fetching SonarQube metrics...". Use fixture `measures.json` if it loads,
else `measures/component` with `component` and `metricKeys` =
`coverage,duplicated_lines_density,code_smells,bugs,vulnerabilities,security_hotspots,ncloc,sqale_debt_ratio,reliability_rating,security_rating`.
If no data return {}. Return `{measure["metric"]: measure.get("value","N/A")}` for
each item in `data["component"]["measures"]`.

### `fetch_sonar_hotspots()`
Print "Fetching security hotspots...". Fixture `hotspots.json` → its `hotspots`
list (print offline count). Else `hotspots/search` with only `projectKey` and
`status="TO_REVIEW"` (no paging – first page only). Return `data["hotspots"]` or [].

### `fetch_sonar_duplications()`
Print "Fetching duplications...". `duplications/show` with `key=SONAR_PROJECT_KEY`.
Return `data["duplications"]` or []. (Defined but never called by `main`.)

## 6. `call_llm(prompt, code_context="")`
If LLM_TOKEN is empty: print once (remember via a function attribute) a warning
that the token is not set and LLM recommendations are skipped (findings still
reported); return None.
Content = prompt, plus, if code_context, "\n\n```\n{code_context}\n```".
POST `{LLM_BASE_URL}/chat/completions` with JSON
`{"model": LLM_MODEL, "max_tokens": 4096, "temperature": 0.2,
"messages": [{"role":"user","content": content}]}` – **one user message only** –
headers Bearer token + `Content-Type: application/json`, `context=SSL_CTX`,
timeout 300. Return `result["choices"][0]["message"]["content"]`.
On HTTPError print "LLM API error: HTTP <code>"; if 401 also print
"→ token expired. Refresh in CI/CD variables."; return None. On other errors print and
return None.

## 7. Source helpers
### `read_source_file(file_path, start_line=1, end_line=None)`
Read all lines. If end_line is None: `end_line = min(start_line + 20, len(lines))`.
`start = max(0, start_line - 5)`, `end = min(len(lines), end_line + 5)`.
For each i in range(start, end): marker `">>>"` if
`start_line - 1 <= i <= (end_line or start_line) - 1` else three spaces; append
`f"{marker} {i+1:4d} | {line.rstrip()}"`. Return the lines joined by "\n".
FileNotFoundError → `"[File not found: {file_path}]"`; other errors →
`"[Error reading {file_path}: {e}]"`.

### `_normalize_ws(s)` → `" ".join(s.split())`

### `apply_fix_to_file(file_path, line_number, original_line, fixed_line)`
`dry_run` = env `FIX_DRY_RUN` (lower) in ("1","true","yes").
Helper result(applied, reason, before=None, after=None) →
`{"applied","reason","dry_run","line","before","after"}`.
1. fixed_line None → result(False,"no_fix").
2. Read lines; FileNotFoundError → print skipped (file_not_found) → result(False,"file_not_found");
   other error → print → result(False,"error").
3. `span = max(1, number of lines in original_line split on "\n")`, `idx = line_number - 1`.
   If idx < 0 or idx+span > len(lines) → print skipped (line_out_of_range) → result(False,"line_out_of_range").
4. target block = lines[idx:idx+span] joined. Match if stripped block == stripped
   original, or whitespace-normalised equal. No match → print (no_match) →
   result(False,"no_match", before=block).
5. replacement = fixed_line + "\n" unless it already ends with "\n".
6. If dry_run: print "DRY-RUN would fix file:line (exact|normalized match, span=N)" →
   result(False,"dry_run", before, after=replacement).
7. Write lines[:idx] + [replacement] + lines[idx+span:]; write error → result(False,"error", before).
8. result(True,"applied", before, after=replacement).

## 8. Prompts (wording may be paraphrased, structure must match)
- `EVALUATION_PROMPT`: senior engineer reviewing SonarQube findings. For each issue:
  1) brief explanation, 2) exact code fix (single line or minimal multi-line),
  3) severity assessment (agree/disagree with SonarQube). Respond as a JSON array of
  `{issue_key, file, line, rule, severity, explanation, original_line, fixed_line,
  recommendation}`. If no fix is possible, fixed_line = null. Ends with
  "SonarQube Issues:" followed by a newline (the issues JSON is appended).
- `HOTSPOT_PROMPT`: security engineer reviewing hotspots; decide true vulnerability
  or false positive; if real, give the fix. JSON array of `{hotspot_key, file, line,
  category, assessment: VULNERABLE|SAFE|NEEDS_REVIEW, explanation, original_line,
  fixed_line (or null), recommendation}`. Ends with "Security Hotspots:".
- `DUPLICATION_PROMPT`: suggest refactoring per duplicated block. JSON array of
  `{files: [..], lines, recommendation, estimated_effort: low|medium|high}`.
  Ends with "Duplications:".

## 9. Parsing
- `_strip_code_fences(text)`: strip; if it starts with ``` drop the first line; if it
  then ends with ``` drop the last 3 chars; return stripped.
- `_extract_first_json_array(text)`: first balanced top-level `[...]`, string/escape
  aware; return substring or None.
- `parse_llm_json_array(response)`: empty → []. Clean with `_strip_code_fences`.
  For candidate in (cleaned, first array of cleaned): json.loads; list → keep dict
  items; dict → [dict]. If both fail, salvage every balanced top-level `{...}` that
  parses as a dict. Never raises.

## 10. `categorize_issues(issues)` → `(bugs, vulnerabilities, code_smells, others)`
For each issue: type = `issue.get("type","CODE_SMELL")`, severity =
`issue.get("severity","MINOR")`; skip if SEVERITY_ORDER[severity] < SEVERITY_ORDER[MIN_SEVERITY].
file = part after the last ":" of `component` (if any). Entry =
`{key, rule, severity, message, file, line (default 0), type}`.
Route by type: BUG → bugs, VULNERABILITY → vulnerabilities, CODE_SMELL → code_smells,
else others.

## 11. `evaluate_issues_with_llm(issues, prompt_template)`
Empty → []. batch_size 15. For each batch: print "Evaluating batch N (n issues)...";
for each issue add `source_context = read_source_file(issue["file"], issue["line"] or 1)`;
`issues_json = json.dumps(issues_with_context, indent=2)`;
`response = call_llm(prompt_template + issues_json)`;
`recs = parse_llm_json_array(response) if response else []`.
If not recs and response: print a warning and retry once with
`prompt_template + issues_json + "\n\nIMPORTANT: Respond with ONLY a valid JSON array. No prose, no markdown."`;
if still empty print "Still unparseable; skipping batch. Preview: <first 200 chars>".
Extend results; `time.sleep(1)`. Return all.

## 12. GitLab
- `gitlab_api(method, endpoint, data=None)`: URL `{GITLAB_URL}/api/v4/{endpoint}`; JSON
  body if data; headers `PRIVATE-TOKEN`, `Content-Type: application/json`,
  `User-Agent: sonar-evaluator`; timeout 30; return parsed JSON unless status 204 → {}.
  Errors print and return None.
- `post_mr_comment(body)`: if no MR_IID or no GITLAB_TOKEN → print(body) and return;
  else POST `projects/{PROJECT_ID}/merge_requests/{MR_IID}/notes` `{"body": body}`.
- `post_mr_inline_comment(file_path, line, body)`: if no MR_IID or token → print
  `[file:line] body`; else POST `.../discussions` with position
  `{base_sha: CI_MERGE_REQUEST_DIFF_BASE_SHA, start_sha: same, head_sha: COMMIT_SHA,
  position_type: "text", new_path: file_path, new_line: line}`.
- `commit_fixes(recommendations)`: apply each rec that has fixed_line, file and line via
  apply_fix_to_file; collect applied/skipped (with skip_reason); if none applied print
  "No fixes applied." and return []. Build a commit message: first line
  "fix: SonarQube violations – N auto-fixed [skip ci]", then fixes grouped by severity
  BLOCKER→INFO with `- \`file:line\` [rule] – recommendation[:120]`. git config email/name
  from SONAR_EVALUATOR_*; git add changed files; if `git diff --cached --quiet` shows
  changes, commit with `--author`, then push to
  `https://oauth2:{GITLAB_TOKEN}@{CI_SERVER_HOST}/{CI_PROJECT_PATH}.git HEAD:{BRANCH_NAME}`
  (known gap #8, keep). On CalledProcessError print that fixes were applied locally
  but not committed. Return applied fixes.

## 13. `generate_mr_summary(metrics, bugs_recs, vuln_recs, smell_recs, hotspot_recs, dup_recs, applied_fixes)`
Markdown:
1. Title "SonarQube Analysis – AI Evaluation Report".
2. "Project Metrics" table (Metric | Value | Status): Code Coverage (✅ if ≥ 80 else ❌),
   Duplicated Lines (✅ if ≤ 3 else ⚠️), Code Smells (✅ if 0 else ⚠️), Bugs (✅ if 0
   else ❌), Vulnerabilities (✅ if 0 else ❌), Security Hotspots (✅ if 0 else ⚠️),
   Technical Debt Ratio (✅ if ≤ 5 else ⚠️). "N/A" values are shown without a status.
3. "Violations & Recommendations" table (Category | Found | Auto-Fixed | Remaining)
   for Bugs, Vulnerabilities, Code Smells (auto-fixed counted by `type` of applied
   fixes), Security Hotspots (auto-fixed 0), Duplications (auto-fixed 0).
4. If applied fixes: "Auto-Fixed Violations" list `file:line **[severity]** [rule] – recommendation[:150]`.
5. Remaining = bug+vuln+smell recs whose key/issue_key is not in applied fixes; if any:
   "Manual Review Required" list (max 20, then "...and N more (see inline comments)").
6. Hotspots with assessment VULNERABLE: "Security Hotspots – Confirmed Vulnerabilities" list.
7. If dup_recs: "Duplication – Refactoring Suggestions" (max 10).
8. Footer: "Analysis by {SONAR_EVALUATOR_NAME} using {LLM_MODEL}".

## 14. `_write_report(payload)`
Write JSON (indent 2, utf-8) to REPORT_PATH; print "Wrote recommendation report → path";
on error print a warning.

## 15. `main()` → int
1. Print a banner: "=" * 60, title, a mode line
   ("OFFLINE-FIXTURES" or "LIVE-API" | "DRY-RUN (no posting/commits)" or "ACTIVE" |
   "auto-fix: ON/OFF"), "=" * 60.
2. If not offline and (no SONAR_HOST or no SONAR_TOKEN or no SONAR_PROJECT_KEY):
   print an error and `sys.exit(1)`.
3. Fetch issues, metrics, hotspots. Print a summary (issue count, hotspot count, metrics JSON).
4. If no issues and no hotspots: unless DRY_RUN post "Clean – no issues, hotspots, or
   violations found."; write `{"project", "clean": True, "metrics"}`; return 0.
5. `bugs, vulnerabilities, code_smells, others = categorize_issues(issues)`; print counts.
6. Evaluate with LLM, in this order, each printed: bugs, vulnerabilities, code smells
   (all with EVALUATION_PROMPT); then hotspots converted to
   `{key, file (component after ":"), line (default 0), category (securityCategory),
   message, vulnerability_probability}` and evaluated with HOTSPOT_PROMPT (only if any).
   Duplications: `dup_recs = []` (not evaluated).
7. `all_recommendations = bugs_recs + vuln_recs + smell_recs + hotspot_recs`; print total.
8. Inline comments: if DRY_RUN print "skipping inline comments"; else for each rec build
   body "**{SONAR_EVALUATOR_NAME}** [severity] `rule`", "**Issue:** explanation",
   "**Recommendation:** recommendation", plus "**Suggested fix:**" + ```suggestion block
   if fixed_line; post inline if line > 0 else as a general comment prefixed with the file.
9. Auto-fix: if AUTO_FIX and not DRY_RUN → `applied_fixes = commit_fixes(all_recommendations)`;
   else print "Auto-fix disabled (observe-first). Recommendations are advisory only."
10. `summary = generate_mr_summary(metrics, bugs_recs, vuln_recs, smell_recs, hotspot_recs, dup_recs, applied_fixes)`;
    post it unless DRY_RUN.
11. Known gap #1: `blockers` = recs in all_recommendations whose `severity` is
    BLOCKER/CRITICAL; `unfixed_blockers = blockers − applied fixes with those severities`.
12. Write the report:
    `{project, mode: "offline"|"live", dry_run, auto_fix,
      counts: {bugs, vulnerabilities, code_smells, hotspots, recommendations, auto_fixed, blocking_unfixed},
      metrics, recommendations: all_recommendations, summary_markdown: summary}`.
13. Print totals. If DRY_RUN or not AUTO_FIX: print "Advisory run – not blocking the
    pipeline." and return 0. Else return 1 if unfixed_blockers > 0, otherwise 0.

`if __name__ == "__main__": sys.exit(main())`

## 16. Imports
Standard library only: os, sys, json, ssl, time, subprocess, urllib.request, urllib.error.
