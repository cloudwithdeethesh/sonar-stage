"""Unit tests for QC.sonar_evaluator — spec-aligned helpers + offline smoke.

Imports the evaluator module. The module prints a TLS line at import
(from `SSL_CTX = _build_ssl_context()`); pytest captures it.
"""

import json
import re
import urllib.request
from pathlib import Path

import pytest

from QC import sonar_evaluator as se


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


# ─── §9 _strip_code_fences ───────────────────────────────────────────────────
class TestStripCodeFences:
    def test_strips_python_fence(self):
        assert se._strip_code_fences("```python\nhello\n```") == "hello"

    def test_strips_bare_fence(self):
        assert se._strip_code_fences("```\nhello\n```") == "hello"

    def test_passthrough_no_fence(self):
        assert se._strip_code_fences("hello world") == "hello world"

    def test_strips_edges(self):
        assert se._strip_code_fences("  hello  ") == "hello"

    def test_empty(self):
        assert se._strip_code_fences("") == ""


# ─── §9 _extract_first_json_array ────────────────────────────────────────────
class TestExtractFirstJsonArray:
    def test_simple_array(self):
        assert se._extract_first_json_array("before [1, 2, 3] after") == "[1, 2, 3]"

    def test_array_of_objects(self):
        s = 'pre [{"a": 1}, {"b": 2}] post'
        assert se._extract_first_json_array(s) == '[{"a": 1}, {"b": 2}]'

    def test_no_array_returns_none(self):
        assert se._extract_first_json_array("no brackets at all") is None

    def test_brackets_inside_string_dont_count(self):
        s = '[{"key": "val [with brackets]"}]'
        assert se._extract_first_json_array(s) == s

    def test_escaped_quote_in_string(self):
        s = '[{"key": "a \\"quoted\\" value"}]'
        assert se._extract_first_json_array(s) == s


# ─── §9 parse_llm_json_array ─────────────────────────────────────────────────
class TestParseLlmJsonArray:
    def test_empty_returns_empty_list(self):
        assert se.parse_llm_json_array("") == []

    def test_happy_path(self):
        s = '[{"issue_key": "A"}, {"issue_key": "B"}]'
        assert se.parse_llm_json_array(s) == [
            {"issue_key": "A"},
            {"issue_key": "B"},
        ]

    def test_with_code_fence(self):
        s = "```json\n[{\"a\": 1}]\n```"
        assert se.parse_llm_json_array(s) == [{"a": 1}]

    def test_single_dict_is_wrapped(self):
        assert se.parse_llm_json_array('{"a": 1}') == [{"a": 1}]

    def test_salvages_partial_array(self):
        s = '[{"a": 1}, {broken, not valid}]'
        assert {"a": 1} in se.parse_llm_json_array(s)

    def test_garbage_returns_empty(self):
        assert se.parse_llm_json_array("totally not json") == []

    def test_never_raises(self):
        for s in ["[", "]", "[}", "[{{]]", "{}", "[1,2,3]"]:
            assert isinstance(se.parse_llm_json_array(s), list)


# ─── §7 _normalize_ws ────────────────────────────────────────────────────────
class TestNormalizeWs:
    def test_collapses_runs_of_spaces(self):
        assert se._normalize_ws("a  b   c") == "a b c"

    def test_collapses_tabs_newlines(self):
        assert se._normalize_ws("a\tb\nc") == "a b c"

    def test_strips_edges(self):
        assert se._normalize_ws("  hello  ") == "hello"


# ─── §7 apply_fix_to_file ────────────────────────────────────────────────────
class TestApplyFixToFile:
    def test_dry_run_leaves_file_untouched(self, tmp_path, monkeypatch):
        p = tmp_path / "f.py"
        p.write_text("x = 1\n")
        monkeypatch.setenv("FIX_DRY_RUN", "1")
        r = se.apply_fix_to_file(str(p), 1, "x = 1", "x = 2")
        assert r["applied"] is False
        assert r["reason"] == "dry_run"
        assert r["dry_run"] is True
        assert p.read_text() == "x = 1\n"

    def test_exact_match_writes(self, tmp_path, monkeypatch):
        p = tmp_path / "f.py"
        p.write_text("x = 1\n")
        monkeypatch.delenv("FIX_DRY_RUN", raising=False)
        r = se.apply_fix_to_file(str(p), 1, "x = 1", "x = 2")
        assert r["applied"] is True
        assert r["reason"] == "applied"
        assert p.read_text() == "x = 2\n"

    def test_normalized_match_writes(self, tmp_path, monkeypatch):
        p = tmp_path / "f.py"
        p.write_text("x   =   1\n")
        monkeypatch.delenv("FIX_DRY_RUN", raising=False)
        r = se.apply_fix_to_file(str(p), 1, "x = 1", "x = 2")
        assert r["applied"] is True
        assert p.read_text() == "x = 2\n"

    def test_no_match(self, tmp_path, monkeypatch):
        p = tmp_path / "f.py"
        p.write_text("y = 42\n")
        monkeypatch.delenv("FIX_DRY_RUN", raising=False)
        r = se.apply_fix_to_file(str(p), 1, "x = 1", "x = 2")
        assert r["applied"] is False
        assert r["reason"] == "no_match"

    def test_fixed_line_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FIX_DRY_RUN", raising=False)
        p = tmp_path / "f.py"
        p.write_text("x = 1\n")
        r = se.apply_fix_to_file(str(p), 1, "x = 1", None)
        assert r["applied"] is False
        assert r["reason"] == "no_fix"

    def test_file_not_found(self, monkeypatch):
        monkeypatch.delenv("FIX_DRY_RUN", raising=False)
        r = se.apply_fix_to_file("/nonexistent/path.py", 1, "x", "y")
        assert r["applied"] is False
        assert r["reason"] == "file_not_found"

    def test_line_out_of_range(self, tmp_path, monkeypatch):
        p = tmp_path / "f.py"
        p.write_text("x = 1\n")
        monkeypatch.delenv("FIX_DRY_RUN", raising=False)
        r = se.apply_fix_to_file(str(p), 99, "x = 1", "x = 2")
        assert r["applied"] is False
        assert r["reason"] == "line_out_of_range"


# ─── §10 categorize_issues ───────────────────────────────────────────────────
class TestCategorizeIssues:
    def test_routes_by_type(self):
        issues = [
            {"key": "a", "severity": "MAJOR", "type": "BUG",
             "component": "p:f.py", "line": 1},
            {"key": "b", "severity": "MAJOR", "type": "VULNERABILITY",
             "component": "p:g.py", "line": 2},
            {"key": "c", "severity": "MAJOR", "type": "CODE_SMELL",
             "component": "p:h.py", "line": 3},
            {"key": "d", "severity": "MAJOR", "type": "WHATEVER",
             "component": "p:x.py", "line": 4},
        ]
        bugs, vulns, smells, others = se.categorize_issues(issues)
        assert [x["key"] for x in bugs] == ["a"]
        assert [x["key"] for x in vulns] == ["b"]
        assert [x["key"] for x in smells] == ["c"]
        assert [x["key"] for x in others] == ["d"]

    def test_drops_below_min_severity(self):
        issues = [
            {"key": "info", "severity": "INFO", "type": "CODE_SMELL",
             "component": "p:f.py", "line": 1},
            {"key": "minor", "severity": "MINOR", "type": "CODE_SMELL",
             "component": "p:f.py", "line": 1},
        ]
        _, _, smells, _ = se.categorize_issues(issues)
        assert len(smells) == 1 and smells[0]["key"] == "minor"

    def test_entry_shape(self):
        issues = [{
            "key": "k", "rule": "python:S1", "severity": "MAJOR",
            "type": "BUG", "component": "proj:src/foo.py",
            "line": 10, "message": "bad thing",
        }]
        bugs, _, _, _ = se.categorize_issues(issues)
        e = bugs[0]
        assert e["key"] == "k"
        assert e["rule"] == "python:S1"
        assert e["severity"] == "MAJOR"
        assert e["message"] == "bad thing"
        assert e["file"] == "src/foo.py"
        assert e["line"] == 10
        assert e["type"] == "BUG"

    def test_severity_order(self):
        o = se.SEVERITY_ORDER
        assert o["BLOCKER"] > o["CRITICAL"] > o["MAJOR"] > o["MINOR"] > o["INFO"]
        assert se.MIN_SEVERITY == "MINOR"


# ─── §7 read_source_file ─────────────────────────────────────────────────────
class TestReadSourceFile:
    def test_focus_line_marker(self, tmp_path):
        p = tmp_path / "f.py"
        p.write_text("\n".join(f"line{i}" for i in range(1, 21)) + "\n")
        out = se.read_source_file(str(p), start_line=10, end_line=10)
        marked = [l for l in out.splitlines() if l.startswith(">>>")]
        assert len(marked) == 1
        assert "line10" in marked[0]

    def test_marker_range(self, tmp_path):
        p = tmp_path / "f.py"
        p.write_text("\n".join(f"line{i}" for i in range(1, 21)) + "\n")
        out = se.read_source_file(str(p), start_line=5, end_line=7)
        marked = [l for l in out.splitlines() if l.startswith(">>>")]
        assert [l.split("|", 1)[1].strip() for l in marked] == [
            "line5", "line6", "line7",
        ]

    def test_start_bound_clamps_to_zero(self, tmp_path):
        p = tmp_path / "f.py"
        p.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n")
        out = se.read_source_file(str(p), start_line=1, end_line=1)
        lines = out.splitlines()
        # window start = max(0, 1-5) = 0; end = min(10, 1+5) = 6 → 6 lines
        assert len(lines) == 6
        assert lines[0].startswith(">>>") and "line1" in lines[0]

    def test_end_bound_clamps_to_len(self, tmp_path):
        p = tmp_path / "f.py"
        p.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n")
        out = se.read_source_file(str(p), start_line=10, end_line=10)
        lines = out.splitlines()
        # start = max(0, 10-5) = 5; end = min(10, 10+5) = 10 → 5 lines
        assert len(lines) == 5
        assert ">>>" in lines[-1]
        assert "line10" in lines[-1]

    def test_file_not_found(self):
        assert se.read_source_file("/nowhere.py", 1) == "[File not found: /nowhere.py]"


# ─── §15 offline smoke test ──────────────────────────────────────────────────
def _patch_offline(monkeypatch, tmp_path):
    """Patch module globals for an offline, dry-run execution."""
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(se, "OFFLINE_FIXTURES_DIR", str(FIXTURES_DIR))
    monkeypatch.setattr(se, "DRY_RUN", True)
    monkeypatch.setattr(se, "AUTO_FIX", False)
    monkeypatch.setattr(se, "REPORT_PATH", str(report_path))
    monkeypatch.setattr(se, "SONAR_PROJECT_KEY", "Sonar-Stage-Sample-TEST")
    # Dummy token so call_llm would proceed; the stub never actually posts.
    monkeypatch.setattr(se, "LLM_TOKEN", "test-not-real")
    monkeypatch.setattr(se, "LLM_BASE_URL", "http://invalid.test/v1")
    monkeypatch.setattr(se, "LLM_MODEL", "test-model")
    return report_path


def _canned_llm(prompt, code_context=""):
    """Return a canned JSON array: one rec per issue found in the prompt
    context. Shape depends on whether the prompt is for hotspots."""
    keys = re.findall(r'"key":\s*"([^"]+)"', prompt)
    is_hotspot = "Security Hotspots:" in prompt
    recs = []
    for key in keys:
        if is_hotspot:
            recs.append({
                "hotspot_key": key,
                "file": "samples/py/dirty_security.py",
                "line": 23,
                "category": "command-injection",
                "assessment": "VULNERABLE",
                "explanation": "subprocess with shell=True enables command injection",
                "original_line": "subprocess.run(cmd, shell=True)",
                "fixed_line": "subprocess.run(shlex.split(cmd))",
                "recommendation": "Avoid shell=True; split the command.",
            })
        else:
            recs.append({
                "issue_key": key,
                "file": "src/receipts.py",
                "line": 19,
                "rule": "python:S1192",
                "severity": "MAJOR",
                "explanation": "Repeated string literal.",
                "original_line": 'Decimal("0.01")',
                "fixed_line": 'Decimal(CENT)',
                "recommendation": "Extract the literal to a module-level constant.",
            })
    return json.dumps(recs)


def test_offline_smoke_main(tmp_path, monkeypatch):
    """Full main() flow from fixtures with a stubbed LLM; schema + counts."""
    report_path = _patch_offline(monkeypatch, tmp_path)
    monkeypatch.setattr(se, "call_llm", _canned_llm)

    rc = se.main()
    assert rc == 0
    assert report_path.exists()

    report = json.loads(report_path.read_text())
    required = {
        "project", "mode", "dry_run", "auto_fix",
        "counts", "metrics", "recommendations", "summary_markdown",
    }
    assert required.issubset(report.keys()), f"missing: {required - report.keys()}"
    assert report["mode"] == "offline"
    assert report["dry_run"] is True
    assert report["auto_fix"] is False
    assert report["project"] == "Sonar-Stage-Sample-TEST"

    # Fix (1): counts come from SonarQube findings, not LLM output.
    assert report["counts"]["bugs"] == 1
    assert report["counts"]["vulnerabilities"] == 1
    assert report["counts"]["code_smells"] == 1
    assert report["counts"]["hotspots"] == 1

    # LLM was stubbed → recommendations should be non-empty.
    assert report["counts"]["recommendations"] > 0
    assert isinstance(report["recommendations"], list)
    assert len(report["recommendations"]) > 0

    # Summary should include the recommendation-oriented sections.
    md = report["summary_markdown"]
    assert "Project Metrics" in md
    assert "Violations & Recommendations" in md
    assert ("Manual Review Required" in md
            or "Security Hotspots – Confirmed Vulnerabilities" in md)


def test_no_network_in_dry_run(tmp_path, monkeypatch):
    """Dry-run with offline fixtures + stubbed call_llm must not touch urlopen.

    Guard: the evaluator must call `urllib.request.urlopen` by full path so
    monkeypatching the module attribute catches every network path. If the
    evaluator ever switches to `from urllib.request import urlopen`, this
    test's patch won't bind and the no-network guarantee silently weakens.
    """
    src = Path(se.__file__).read_text()
    assert "urllib.request.urlopen" in src, "evaluator must call urllib.request.urlopen"
    assert "from urllib.request import urlopen" not in src, (
        "evaluator must NOT import urlopen directly — monkeypatch would miss it"
    )

    _patch_offline(monkeypatch, tmp_path)
    monkeypatch.setattr(se, "call_llm", _canned_llm)

    def boom(*args, **kwargs):
        raise AssertionError("network call attempted during dry-run")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    rc = se.main()
    assert rc == 0
