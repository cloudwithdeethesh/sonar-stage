"""Sonar Recommendation evaluator — mirror of docs/REFERENCE_SPEC.md.

Reads SonarQube issues / hotspots / metrics, asks an OpenAI-compatible LLM to
evaluate them, and in non-dry-run posts inline comments + a summary to the
GitLab MR. In DRY_RUN (default) it still reads, still writes a JSON report,
but posts nothing to GitLab and commits nothing.

Run: `python -m QC.sonar_evaluator`
"""

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request


# ─── §1 configuration ─────────────────────────────────────────────────────────
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_TOKEN = os.getenv("LLM_TOKEN", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")

SONAR_HOST = os.getenv("SONAR_HOST_URL", "")
SONAR_TOKEN = os.getenv("SONAR_TOKEN", "")
SONAR_READ_TOKEN = os.getenv("SONAR_READ_TOKEN", "") or SONAR_TOKEN
SONAR_PROJECT_KEY = os.getenv("SONAR_PROJECT_KEY", "")

GITLAB_URL = os.getenv("CI_SERVER_URL", "https://gitlab.com")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
PROJECT_ID = os.getenv("CI_PROJECT_ID", "")
MR_IID = os.getenv("CI_MERGE_REQUEST_IID", "")
COMMIT_SHA = os.getenv("CI_COMMIT_SHA", "")
BRANCH_NAME = os.getenv("CI_COMMIT_REF_NAME", "")

SONAR_EVALUATOR_NAME = os.getenv("SONAR_EVALUATOR_NAME", "Sonar Recommender")
SONAR_EVALUATOR_EMAIL = os.getenv("SONAR_EVALUATOR_EMAIL", "sonar-recommender@noreply.local")

# Run modes
DRY_RUN = os.getenv("DRY_RUN", "1").strip().lower() not in ("0", "false", "no", "")
OFFLINE_FIXTURES_DIR = os.getenv("OFFLINE_FIXTURES_DIR", "").strip()
AUTO_FIX = os.getenv("AUTO_FIX", "").strip().lower() in ("1", "true", "yes")
REPORT_PATH = os.getenv("REPORT_PATH", "sonar-recommendation-report.json")


# ─── §2 SSL context ───────────────────────────────────────────────────────────
def _build_ssl_context():
    if os.getenv("INSECURE_TLS", "").strip().lower() in ("1", "true", "yes"):
        print("WARNING: INSECURE_TLS set — TLS verification DISABLED (debug only).")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    ca_bundle = (
        os.getenv("CA_BUNDLE")
        or os.getenv("SONAR_CA_BUNDLE")
        or os.getenv("REQUESTS_CA_BUNDLE")
    )
    if ca_bundle and os.path.exists(ca_bundle):
        print(f"TLS: verifying with CA bundle {ca_bundle}")
        return ssl.create_default_context(cafile=ca_bundle)
    print("TLS: verifying with system default trust store")
    return ssl.create_default_context()


SSL_CTX = _build_ssl_context()


# ─── §3 severity ──────────────────────────────────────────────────────────────
SEVERITY_ORDER = {"BLOCKER": 5, "CRITICAL": 4, "MAJOR": 3, "MINOR": 2, "INFO": 1}
MIN_SEVERITY = "MINOR"


# ─── §4 offline fixtures ──────────────────────────────────────────────────────
def _load_fixture(name):
    if not OFFLINE_FIXTURES_DIR:
        return None
    path = os.path.join(OFFLINE_FIXTURES_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"WARNING: fixture not found: {path}")
        return None
    except Exception as e:
        print(f"WARNING: fixture load error ({path}): {e}")
        return None


# ─── §5 SonarQube API ─────────────────────────────────────────────────────────
def sonar_api(endpoint, params=None):
    url = f"{SONAR_HOST}/api/{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {SONAR_READ_TOKEN}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        print(f"SonarQube API error: HTTP {e.code} on {endpoint}")
        if body:
            print(body)
        return None
    except Exception as e:
        print(f"SonarQube API error on {endpoint}: {e}")
        return None


def fetch_sonar_issues():
    print("Fetching SonarQube issues...")
    fixture = _load_fixture("issues.json")
    if fixture is not None:
        issues = fixture.get("issues", [])
        print(f"(offline) loaded {len(issues)} issues from fixture")
        return issues
    all_issues = []
    page = 1
    while True:
        data = sonar_api(
            "issues/search",
            {
                "componentKeys": SONAR_PROJECT_KEY,
                "statuses": "OPEN,CONFIRMED,REOPENED",
                "ps": "500",
                "p": str(page),
                "additionalFields": "comments,rules",
            },
        )
        if data is None:
            break
        batch = data.get("issues", [])
        total = data.get("total", 0)
        all_issues.extend(batch)
        print(f"Fetched page {page}: {len(batch)} issues (total: {total})")
        if not batch or len(all_issues) >= total:
            break
        page += 1
    return all_issues


def fetch_sonar_metrics():
    print("Fetching SonarQube metrics...")
    fixture = _load_fixture("measures.json")
    if fixture is not None:
        data = fixture
    else:
        data = sonar_api(
            "measures/component",
            {
                "component": SONAR_PROJECT_KEY,
                "metricKeys": (
                    "coverage,duplicated_lines_density,code_smells,bugs,"
                    "vulnerabilities,security_hotspots,ncloc,sqale_debt_ratio,"
                    "reliability_rating,security_rating"
                ),
            },
        )
    if not data:
        return {}
    measures = data.get("component", {}).get("measures", []) or []
    return {m["metric"]: m.get("value", "N/A") for m in measures if "metric" in m}


def fetch_sonar_hotspots():
    print("Fetching security hotspots...")
    fixture = _load_fixture("hotspots.json")
    if fixture is not None:
        hotspots = fixture.get("hotspots", [])
        print(f"(offline) loaded {len(hotspots)} hotspots from fixture")
        return hotspots
    data = sonar_api(
        "hotspots/search",
        {"projectKey": SONAR_PROJECT_KEY, "status": "TO_REVIEW"},
    )
    if not data:
        return []
    return data.get("hotspots", []) or []


def fetch_sonar_duplications():
    print("Fetching duplications...")
    data = sonar_api("duplications/show", {"key": SONAR_PROJECT_KEY})
    if not data:
        return []
    return data.get("duplications", []) or []


# ─── §6 LLM ───────────────────────────────────────────────────────────────────
def call_llm(prompt, code_context=""):
    if not LLM_TOKEN:
        if not getattr(call_llm, "_warned", False):
            print(
                "WARNING: LLM_TOKEN is not set; LLM recommendations are skipped. "
                "Findings are still reported."
            )
            call_llm._warned = True
        return None
    content = prompt
    if code_context:
        content += f"\n\n```\n{code_context}\n```"
    body = json.dumps(
        {
            "model": LLM_MODEL,
            "max_tokens": 4096,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": content}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {LLM_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=300) as r:
            result = json.loads(r.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        print(f"LLM API error: HTTP {e.code}")
        if e.code == 401:
            print("→ token expired. Refresh in CI/CD variables.")
        return None
    except Exception as e:
        print(f"LLM API error: {e}")
        return None


# ─── §7 source helpers ────────────────────────────────────────────────────────
def read_source_file(file_path, start_line=1, end_line=None):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return f"[File not found: {file_path}]"
    except Exception as e:
        return f"[Error reading {file_path}: {e}]"
    if end_line is None:
        end_line = min(start_line + 20, len(lines))
    start = max(0, start_line - 5)
    end = min(len(lines), end_line + 5)
    out = []
    for i in range(start, end):
        focus_end = (end_line or start_line) - 1
        marker = ">>>" if (start_line - 1) <= i <= focus_end else "   "
        out.append(f"{marker} {i + 1:4d} | {lines[i].rstrip()}")
    return "\n".join(out)


def _normalize_ws(s):
    return " ".join(s.split())


def apply_fix_to_file(file_path, line_number, original_line, fixed_line):
    dry_run = os.getenv("FIX_DRY_RUN", "").strip().lower() in ("1", "true", "yes")

    def result(applied, reason, before=None, after=None):
        return {
            "applied": applied,
            "reason": reason,
            "dry_run": dry_run,
            "line": line_number,
            "before": before,
            "after": after,
        }

    if fixed_line is None:
        return result(False, "no_fix")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"apply_fix_to_file: skipped {file_path}:{line_number} (file_not_found)")
        return result(False, "file_not_found")
    except Exception as e:
        print(f"apply_fix_to_file: error reading {file_path}: {e}")
        return result(False, "error")
    span = max(1, len(original_line.split("\n")))
    idx = line_number - 1
    if idx < 0 or idx + span > len(lines):
        print(f"apply_fix_to_file: skipped {file_path}:{line_number} (line_out_of_range)")
        return result(False, "line_out_of_range")
    block = "".join(lines[idx : idx + span])
    match = None
    if block.strip() == original_line.strip():
        match = "exact"
    elif _normalize_ws(block) == _normalize_ws(original_line):
        match = "normalized"
    if match is None:
        print(f"apply_fix_to_file: skipped {file_path}:{line_number} (no_match)")
        return result(False, "no_match", before=block)
    replacement = fixed_line if fixed_line.endswith("\n") else fixed_line + "\n"
    if dry_run:
        print(
            f"DRY-RUN would fix {file_path}:{line_number} "
            f"({match} match, span={span})"
        )
        return result(False, "dry_run", before=block, after=replacement)
    try:
        new_lines = lines[:idx] + [replacement] + lines[idx + span :]
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"apply_fix_to_file: write error for {file_path}: {e}")
        return result(False, "error", before=block)
    return result(True, "applied", before=block, after=replacement)


# ─── §8 prompts ───────────────────────────────────────────────────────────────
EVALUATION_PROMPT = """You are a senior engineer reviewing SonarQube findings.
For each issue, provide:
  1) a brief explanation,
  2) an exact code fix (single line or minimal multi-line),
  3) a severity assessment (agree or disagree with SonarQube's label).

Respond as a JSON array of objects with these exact fields:
  issue_key, file, line, rule, severity, explanation,
  original_line, fixed_line, recommendation

If no fix is possible, set fixed_line to null.

SonarQube Issues:
"""

HOTSPOT_PROMPT = """You are a security engineer reviewing SonarQube security
hotspots. For each hotspot, decide whether it is a true vulnerability or a
false positive; if real, provide a fix.

Respond as a JSON array of objects with these exact fields:
  hotspot_key, file, line, category,
  assessment (VULNERABLE|SAFE|NEEDS_REVIEW),
  explanation, original_line, fixed_line (or null), recommendation

Security Hotspots:
"""

DUPLICATION_PROMPT = """You are reviewing SonarQube duplication groups.
For each duplicated block, suggest a refactoring.

Respond as a JSON array of objects with these exact fields:
  files (list of file paths),
  lines (number of duplicated lines),
  recommendation,
  estimated_effort (low|medium|high)

Duplications:
"""


# ─── §9 parsing ───────────────────────────────────────────────────────────────
def _strip_code_fences(text):
    s = text.strip()
    if s.startswith("```"):
        if "\n" in s:
            s = s.split("\n", 1)[1]
        else:
            s = ""
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


def _extract_first_json_array(text):
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    return text[start : i + 1]
    return None


def parse_llm_json_array(response):
    if not response:
        return []
    cleaned = _strip_code_fences(response)
    for candidate in (cleaned, _extract_first_json_array(cleaned)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            return [data]
    # Salvage: every balanced top-level {...} that parses as a dict
    results = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(cleaned):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    chunk = cleaned[start : i + 1]
                    try:
                        obj = json.loads(chunk)
                        if isinstance(obj, dict):
                            results.append(obj)
                    except Exception:
                        pass
                    start = -1
    return results


# ─── §10 categorize ───────────────────────────────────────────────────────────
def categorize_issues(issues):
    bugs, vulnerabilities, code_smells, others = [], [], [], []
    min_level = SEVERITY_ORDER[MIN_SEVERITY]
    for issue in issues:
        itype = issue.get("type", "CODE_SMELL")
        severity = issue.get("severity", "MINOR")
        if SEVERITY_ORDER.get(severity, 0) < min_level:
            continue
        component = issue.get("component", "") or ""
        file = component.rsplit(":", 1)[1] if ":" in component else component
        entry = {
            "key": issue.get("key"),
            "rule": issue.get("rule"),
            "severity": severity,
            "message": issue.get("message", ""),
            "file": file,
            "line": issue.get("line", 0),
            "type": itype,
        }
        if itype == "BUG":
            bugs.append(entry)
        elif itype == "VULNERABILITY":
            vulnerabilities.append(entry)
        elif itype == "CODE_SMELL":
            code_smells.append(entry)
        else:
            others.append(entry)
    return bugs, vulnerabilities, code_smells, others


# ─── §11 batched LLM evaluation ───────────────────────────────────────────────
def evaluate_issues_with_llm(issues, prompt_template):
    if not issues:
        return []
    results = []
    batch_size = 15
    for start in range(0, len(issues), batch_size):
        batch = issues[start : start + batch_size]
        batch_num = (start // batch_size) + 1
        print(f"Evaluating batch {batch_num} ({len(batch)} issues)...")
        issues_with_context = []
        for issue in batch:
            ctx = read_source_file(issue["file"], issue.get("line") or 1)
            item = dict(issue)
            item["source_context"] = ctx
            issues_with_context.append(item)
        issues_json = json.dumps(issues_with_context, indent=2)
        response = call_llm(prompt_template + issues_json)
        recs = parse_llm_json_array(response) if response else []
        if not recs and response:
            print("WARNING: empty parse — retrying with JSON-only instruction")
            response2 = call_llm(
                prompt_template
                + issues_json
                + "\n\nIMPORTANT: Respond with ONLY a valid JSON array. No prose, no markdown."
            )
            recs = parse_llm_json_array(response2) if response2 else []
            if not recs:
                preview = (response2 or response or "")[:200]
                print(f"Still unparseable; skipping batch. Preview: {preview}")
        results.extend(recs)
        time.sleep(1)
    return results


# ─── §12 GitLab ───────────────────────────────────────────────────────────────
def gitlab_api(method, endpoint, data=None):
    url = f"{GITLAB_URL}/api/v4/{endpoint}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "PRIVATE-TOKEN": GITLAB_TOKEN,
            "Content-Type": "application/json",
            "User-Agent": "sonar-evaluator",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
            if r.status == 204:
                return {}
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"GitLab API error: HTTP {e.code} on {method} {endpoint}")
        return None
    except Exception as e:
        print(f"GitLab API error on {method} {endpoint}: {e}")
        return None


def post_mr_comment(body):
    if not MR_IID or not GITLAB_TOKEN:
        print(body)
        return
    gitlab_api(
        "POST",
        f"projects/{PROJECT_ID}/merge_requests/{MR_IID}/notes",
        {"body": body},
    )


def post_mr_inline_comment(file_path, line, body):
    if not MR_IID or not GITLAB_TOKEN:
        print(f"[{file_path}:{line}] {body}")
        return
    base_sha = os.getenv("CI_MERGE_REQUEST_DIFF_BASE_SHA", "")
    gitlab_api(
        "POST",
        f"projects/{PROJECT_ID}/merge_requests/{MR_IID}/discussions",
        {
            "body": body,
            "position": {
                "base_sha": base_sha,
                "start_sha": base_sha,
                "head_sha": COMMIT_SHA,
                "position_type": "text",
                "new_path": file_path,
                "new_line": line,
            },
        },
    )


def commit_fixes(recommendations):
    applied = []
    skipped = []
    for rec in recommendations:
        if rec.get("fixed_line") is None:
            continue
        file = rec.get("file")
        line = rec.get("line", 0)
        if not file or not line:
            continue
        r = apply_fix_to_file(file, line, rec.get("original_line", ""), rec["fixed_line"])
        if r["applied"]:
            applied.append(rec)
        else:
            skipped.append((rec, r["reason"]))

    if not applied:
        print("No fixes applied.")
        return []

    sev_order = ["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"]
    msg_lines = [f"fix: SonarQube violations – {len(applied)} auto-fixed [skip ci]", ""]
    grouped = {s: [] for s in sev_order}
    for rec in applied:
        sev = str(rec.get("severity", "MINOR")).upper()
        if sev in grouped:
            grouped[sev].append(rec)
    for sev in sev_order:
        if not grouped[sev]:
            continue
        msg_lines.append(f"[{sev}]")
        for rec in grouped[sev]:
            rule = rec.get("rule", "")
            recm = (rec.get("recommendation") or "")[:120]
            msg_lines.append(f"- `{rec['file']}:{rec['line']}` [{rule}] – {recm}")
        msg_lines.append("")
    commit_msg = "\n".join(msg_lines).strip()

    files = sorted({rec["file"] for rec in applied})
    try:
        subprocess.run(["git", "config", "user.email", SONAR_EVALUATOR_EMAIL], check=True)
        subprocess.run(["git", "config", "user.name", SONAR_EVALUATOR_NAME], check=True)
        subprocess.run(["git", "add", *files], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
            subprocess.run(
                [
                    "git",
                    "commit",
                    "--author",
                    f"{SONAR_EVALUATOR_NAME} <{SONAR_EVALUATOR_EMAIL}>",
                    "-m",
                    commit_msg,
                ],
                check=True,
            )
            push_url = (
                f"https://oauth2:{GITLAB_TOKEN}@"
                f"{os.getenv('CI_SERVER_HOST', '')}/"
                f"{os.getenv('CI_PROJECT_PATH', '')}.git"
            )
            subprocess.run(
                ["git", "push", push_url, f"HEAD:{BRANCH_NAME}"],
                check=True,
            )
    except subprocess.CalledProcessError as e:
        print(f"Fixes applied locally but not committed: {e}")
    return applied


# ─── §13 MR summary ───────────────────────────────────────────────────────────
def _metric_row(metrics, label, key, status_fn):
    val = metrics.get(key, "N/A")
    if val in (None, "N/A"):
        return f"| {label} | N/A |  |"
    try:
        num = float(val)
    except (TypeError, ValueError):
        return f"| {label} | {val} |  |"
    return f"| {label} | {val} | {status_fn(num)} |"


def generate_mr_summary(
    metrics, bugs_recs, vuln_recs, smell_recs, hotspot_recs, dup_recs, applied_fixes
):
    lines = ["# SonarQube Analysis – AI Evaluation Report", ""]

    lines.append("## Project Metrics")
    lines.append("")
    lines.append("| Metric | Value | Status |")
    lines.append("|---|---|---|")
    lines.append(_metric_row(metrics, "Code Coverage", "coverage",
                             lambda v: "✅" if v >= 80 else "❌"))
    lines.append(_metric_row(metrics, "Duplicated Lines", "duplicated_lines_density",
                             lambda v: "✅" if v <= 3 else "⚠️"))
    lines.append(_metric_row(metrics, "Code Smells", "code_smells",
                             lambda v: "✅" if v == 0 else "⚠️"))
    lines.append(_metric_row(metrics, "Bugs", "bugs",
                             lambda v: "✅" if v == 0 else "❌"))
    lines.append(_metric_row(metrics, "Vulnerabilities", "vulnerabilities",
                             lambda v: "✅" if v == 0 else "❌"))
    lines.append(_metric_row(metrics, "Security Hotspots", "security_hotspots",
                             lambda v: "✅" if v == 0 else "⚠️"))
    lines.append(_metric_row(metrics, "Technical Debt Ratio", "sqale_debt_ratio",
                             lambda v: "✅" if v <= 5 else "⚠️"))
    lines.append("")

    lines.append("## Violations & Recommendations")
    lines.append("")
    lines.append("| Category | Found | Auto-Fixed | Remaining |")
    lines.append("|---|---|---|---|")

    applied_by_type = {}
    for rec in applied_fixes:
        t = rec.get("type", "")
        applied_by_type[t] = applied_by_type.get(t, 0) + 1

    def _row(cat, recs, type_key):
        found = len(recs)
        fixed = applied_by_type.get(type_key, 0) if type_key else 0
        lines.append(f"| {cat} | {found} | {fixed} | {found - fixed} |")

    _row("Bugs", bugs_recs, "BUG")
    _row("Vulnerabilities", vuln_recs, "VULNERABILITY")
    _row("Code Smells", smell_recs, "CODE_SMELL")
    lines.append(f"| Security Hotspots | {len(hotspot_recs)} | 0 | {len(hotspot_recs)} |")
    lines.append(f"| Duplications | {len(dup_recs)} | 0 | {len(dup_recs)} |")
    lines.append("")

    applied_keys = {rec.get("key") or rec.get("issue_key") for rec in applied_fixes}

    if applied_fixes:
        lines.append("## Auto-Fixed Violations")
        lines.append("")
        for rec in applied_fixes:
            file = rec.get("file", "")
            line = rec.get("line", 0)
            sev = rec.get("severity", "")
            rule = rec.get("rule", "")
            recm = (rec.get("recommendation") or "")[:150]
            lines.append(f"- `{file}:{line}` **[{sev}]** [{rule}] – {recm}")
        lines.append("")

    remaining = [
        rec
        for rec in (bugs_recs + vuln_recs + smell_recs)
        if not rec.get("fixed_line")
        or (rec.get("key") or rec.get("issue_key")) not in applied_keys
    ]
    if remaining:
        lines.append("## Manual Review Required")
        lines.append("")
        for rec in remaining[:20]:
            file = rec.get("file", "")
            line = rec.get("line", 0)
            sev = rec.get("severity", "")
            rule = rec.get("rule", "")
            recm = (rec.get("recommendation") or "")[:150]
            lines.append(f"- `{file}:{line}` **[{sev}]** [{rule}] – {recm}")
        if len(remaining) > 20:
            lines.append(f"...and {len(remaining) - 20} more (see inline comments)")
        lines.append("")

    confirmed = [h for h in hotspot_recs if str(h.get("assessment", "")).upper() == "VULNERABLE"]
    if confirmed:
        lines.append("## Security Hotspots – Confirmed Vulnerabilities")
        lines.append("")
        for h in confirmed:
            file = h.get("file", "")
            line = h.get("line", 0)
            cat = h.get("category", "")
            recm = (h.get("recommendation") or "")[:150]
            lines.append(f"- `{file}:{line}` [{cat}] – {recm}")
        lines.append("")

    if dup_recs:
        lines.append("## Duplication – Refactoring Suggestions")
        lines.append("")
        for rec in dup_recs[:10]:
            files_list = ", ".join(rec.get("files", []))
            n_lines = rec.get("lines", 0)
            effort = rec.get("estimated_effort", "")
            recm = (rec.get("recommendation") or "")[:150]
            lines.append(f"- {files_list} ({n_lines} lines, effort: {effort}) – {recm}")
        lines.append("")

    lines.append(f"Analysis by {SONAR_EVALUATOR_NAME} using {LLM_MODEL}")
    return "\n".join(lines)


# ─── §14 report writer ────────────────────────────────────────────────────────
def _write_report(payload):
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"Wrote recommendation report → {REPORT_PATH}")
    except Exception as e:
        print(f"WARNING: failed to write report: {e}")


# ─── §15 main ─────────────────────────────────────────────────────────────────
def main():
    bar = "=" * 60
    print(bar)
    print("SonarQube Analysis – AI Evaluation")
    mode_source = "OFFLINE-FIXTURES" if OFFLINE_FIXTURES_DIR else "LIVE-API"
    mode_dry = "DRY-RUN (no posting/commits)" if DRY_RUN else "ACTIVE"
    mode_fix = f"auto-fix: {'ON' if AUTO_FIX else 'OFF'}"
    print(f"{mode_source} | {mode_dry} | {mode_fix}")
    print(bar)

    if not OFFLINE_FIXTURES_DIR:
        missing = []
        if not SONAR_HOST:
            missing.append("SONAR_HOST_URL")
        if not SONAR_TOKEN:
            missing.append("SONAR_TOKEN")
        if not SONAR_PROJECT_KEY:
            missing.append("SONAR_PROJECT_KEY")
        if missing:
            print(f"ERROR: missing required env vars: {', '.join(missing)}")
            sys.exit(1)

    issues = fetch_sonar_issues()
    metrics = fetch_sonar_metrics()
    hotspots = fetch_sonar_hotspots()
    print(
        f"Fetched {len(issues)} issues, {len(hotspots)} hotspots, "
        f"metrics: {json.dumps(metrics)}"
    )

    if not issues and not hotspots:
        if not DRY_RUN:
            post_mr_comment("Clean – no issues, hotspots, or violations found.")
        _write_report({"project": SONAR_PROJECT_KEY, "clean": True, "metrics": metrics})
        return 0

    bugs, vulnerabilities, code_smells, others = categorize_issues(issues)
    print(
        f"Categorized: bugs={len(bugs)}, vulnerabilities={len(vulnerabilities)}, "
        f"code_smells={len(code_smells)}, others={len(others)}"
    )

    print(f"Evaluating {len(bugs)} bugs...")
    bugs_recs = evaluate_issues_with_llm(bugs, EVALUATION_PROMPT)
    print(f"Evaluating {len(vulnerabilities)} vulnerabilities...")
    vuln_recs = evaluate_issues_with_llm(vulnerabilities, EVALUATION_PROMPT)
    print(f"Evaluating {len(code_smells)} code smells...")
    smell_recs = evaluate_issues_with_llm(code_smells, EVALUATION_PROMPT)

    hotspot_items = []
    for h in hotspots:
        component = h.get("component", "") or ""
        file = component.rsplit(":", 1)[1] if ":" in component else component
        hotspot_items.append({
            "key": h.get("key"),
            "file": file,
            "line": h.get("line", 0),
            "category": h.get("securityCategory", ""),
            "message": h.get("message", ""),
            "vulnerability_probability": h.get("vulnerabilityProbability", ""),
        })
    if hotspot_items:
        print(f"Evaluating {len(hotspot_items)} hotspots...")
        hotspot_recs = evaluate_issues_with_llm(hotspot_items, HOTSPOT_PROMPT)
    else:
        hotspot_recs = []

    dup_recs = []
    all_recommendations = bugs_recs + vuln_recs + smell_recs + hotspot_recs
    print(f"Total recommendations: {len(all_recommendations)}")

    if DRY_RUN:
        print("DRY-RUN: skipping inline comments")
    else:
        for rec in all_recommendations:
            parts = [
                f"**{SONAR_EVALUATOR_NAME}** [{rec.get('severity', '')}] `{rec.get('rule', '')}`",
                f"**Issue:** {rec.get('explanation', '')}",
                f"**Recommendation:** {rec.get('recommendation', '')}",
            ]
            if rec.get("fixed_line"):
                parts.append(
                    "**Suggested fix:**\n```suggestion\n"
                    f"{rec['fixed_line']}\n```"
                )
            body = "\n\n".join(parts)
            file = rec.get("file", "")
            line = rec.get("line", 0)
            if line and line > 0:
                post_mr_inline_comment(file, line, body)
            else:
                post_mr_comment(f"[{file}] {body}")

    if AUTO_FIX and not DRY_RUN:
        applied_fixes = commit_fixes(all_recommendations)
    else:
        print("Auto-fix disabled (observe-first). Recommendations are advisory only.")
        applied_fixes = []

    summary = generate_mr_summary(
        metrics, bugs_recs, vuln_recs, smell_recs, hotspot_recs, dup_recs, applied_fixes
    )
    if not DRY_RUN:
        post_mr_comment(summary)

    # Gap #1: blockers counted from LLM output
    blockers = [
        rec
        for rec in all_recommendations
        if str(rec.get("severity", "")).upper() in ("BLOCKER", "CRITICAL")
    ]
    applied_blocker_keys = {
        rec.get("key") or rec.get("issue_key")
        for rec in applied_fixes
        if str(rec.get("severity", "")).upper() in ("BLOCKER", "CRITICAL")
    }
    unfixed_blockers = [
        rec
        for rec in blockers
        if (rec.get("key") or rec.get("issue_key")) not in applied_blocker_keys
    ]

    _write_report({
        "project": SONAR_PROJECT_KEY,
        "mode": "offline" if OFFLINE_FIXTURES_DIR else "live",
        "dry_run": DRY_RUN,
        "auto_fix": AUTO_FIX,
        "counts": {
            "bugs": len(bugs),
            "vulnerabilities": len(vulnerabilities),
            "code_smells": len(code_smells),
            "hotspots": len(hotspots),
            "recommendations": len(all_recommendations),
            "auto_fixed": len(applied_fixes),
            "blocking_unfixed": len(unfixed_blockers),
        },
        "metrics": metrics,
        "recommendations": all_recommendations,
        "summary_markdown": summary,
    })

    print(
        f"Total: {len(all_recommendations)} recommendations, "
        f"{len(applied_fixes)} auto-fixed, "
        f"{len(unfixed_blockers)} unfixed blocker(s)"
    )
    if DRY_RUN or not AUTO_FIX:
        print("Advisory run – not blocking the pipeline.")
        return 0
    return 1 if unfixed_blockers else 0


if __name__ == "__main__":
    sys.exit(main())
