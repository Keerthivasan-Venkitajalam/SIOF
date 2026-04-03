"""Tests for SARIF and JSON report generation."""

import json
from pathlib import Path

from siof.models import Finding
from siof.sarif_reporter import JSONReporter, SARIFReporter


class TestSARIFReporter:
    """Tests for SARIF report generation."""

    def test_generate_empty_findings(self):
        """Test SARIF generation with no findings."""
        report = SARIFReporter.generate([])

        assert report["version"] == "2.1.0"
        assert len(report["runs"]) == 1
        assert report["runs"][0]["results"] == []

    def test_generate_single_finding(self):
        """Test SARIF generation with single finding."""
        findings = [
            Finding(
                rule_id="NakedExceptionPass",
                severity="high",
                file_path="test.py",
                line=10,
                message="Bare exception detected",
                autofix_applied=False,
            )
        ]

        report = SARIFReporter.generate(findings)

        assert len(report["runs"][0]["results"]) == 1
        result = report["runs"][0]["results"][0]
        assert result["ruleId"] == "NakedExceptionPass"
        assert result["level"] == "error"
        assert result["message"]["text"] == "Bare exception detected"

    def test_generate_multiple_findings(self):
        """Test SARIF generation with multiple findings."""
        findings = [
            Finding(
                rule_id="NakedExceptionPass",
                severity="high",
                file_path="test.py",
                line=10,
                message="Bare exception detected",
                autofix_applied=False,
            ),
            Finding(
                rule_id="HedgeComment",
                severity="low",
                file_path="test.py",
                line=5,
                message="Hedge word detected",
                autofix_applied=False,
            ),
        ]

        report = SARIFReporter.generate(findings)

        assert len(report["runs"][0]["results"]) == 2

    def test_severity_mapping(self):
        """Test severity to SARIF level mapping."""
        test_cases = [
            ("critical", "error"),
            ("high", "error"),
            ("medium", "warning"),
            ("low", "note"),
        ]

        for severity, expected_level in test_cases:
            findings = [
                Finding(
                    rule_id="TestRule",
                    severity=severity,
                    file_path="test.py",
                    line=1,
                    message="Test",
                    autofix_applied=False,
                )
            ]

            report = SARIFReporter.generate(findings)
            result = report["runs"][0]["results"][0]
            assert result["level"] == expected_level

    def test_write_sarif(self, tmp_path: Path):
        """Test writing SARIF report to file."""
        findings = [
            Finding(
                rule_id="NakedExceptionPass",
                severity="high",
                file_path="test.py",
                line=10,
                message="Bare exception detected",
                autofix_applied=False,
            )
        ]

        output_path = tmp_path / "report.sarif"
        SARIFReporter.write_sarif(findings, output_path)

        assert output_path.exists()

        with open(output_path) as f:
            report = json.load(f)

        assert report["version"] == "2.1.0"
        assert len(report["runs"][0]["results"]) == 1

    def test_sarif_rules(self):
        """Test SARIF rules generation."""
        findings = [
            Finding(
                rule_id="NakedExceptionPass",
                severity="high",
                file_path="test.py",
                line=10,
                message="Bare exception detected",
                autofix_applied=False,
            ),
            Finding(
                rule_id="HedgeComment",
                severity="low",
                file_path="test.py",
                line=5,
                message="Hedge word detected",
                autofix_applied=False,
            ),
        ]

        report = SARIFReporter.generate(findings)
        rules = report["runs"][0]["tool"]["driver"]["rules"]

        assert len(rules) == 2
        rule_ids = {r["id"] for r in rules}
        assert "NakedExceptionPass" in rule_ids
        assert "HedgeComment" in rule_ids


class TestJSONReporter:
    """Tests for JSON report generation."""

    def test_generate_empty_findings(self):
        """Test JSON generation with no findings."""
        report = JSONReporter.generate([])

        assert report["summary"]["total"] == 0
        assert report["summary"]["by_severity"]["critical"] == 0
        assert report["summary"]["by_severity"]["high"] == 0

    def test_generate_single_finding(self):
        """Test JSON generation with single finding."""
        findings = [
            Finding(
                rule_id="NakedExceptionPass",
                severity="high",
                file_path="test.py",
                line=10,
                message="Bare exception detected",
                autofix_applied=False,
            )
        ]

        report = JSONReporter.generate(findings)

        assert report["summary"]["total"] == 1
        assert report["summary"]["by_severity"]["high"] == 1
        assert len(report["findings"]["high"]) == 1

    def test_generate_multiple_findings(self):
        """Test JSON generation with multiple findings."""
        findings = [
            Finding(
                rule_id="NakedExceptionPass",
                severity="high",
                file_path="test.py",
                line=10,
                message="Bare exception detected",
                autofix_applied=False,
            ),
            Finding(
                rule_id="HedgeComment",
                severity="low",
                file_path="test.py",
                line=5,
                message="Hedge word detected",
                autofix_applied=False,
            ),
            Finding(
                rule_id="UnusedImport",
                severity="low",
                file_path="test.py",
                line=1,
                message="Unused import",
                autofix_applied=False,
            ),
        ]

        report = JSONReporter.generate(findings)

        assert report["summary"]["total"] == 3
        assert report["summary"]["by_severity"]["high"] == 1
        assert report["summary"]["by_severity"]["low"] == 2
        assert report["summary"]["by_rule"]["NakedExceptionPass"] == 1
        assert report["summary"]["by_rule"]["HedgeComment"] == 1
        assert report["summary"]["by_rule"]["UnusedImport"] == 1

    def test_write_json(self, tmp_path: Path):
        """Test writing JSON report to file."""
        findings = [
            Finding(
                rule_id="NakedExceptionPass",
                severity="high",
                file_path="test.py",
                line=10,
                message="Bare exception detected",
                autofix_applied=False,
            )
        ]

        output_path = tmp_path / "report.json"
        JSONReporter.write_json(findings, output_path)

        assert output_path.exists()

        with open(output_path) as f:
            report = json.load(f)

        assert report["summary"]["total"] == 1
        assert len(report["findings"]["high"]) == 1

    def test_json_summary_statistics(self):
        """Test JSON summary statistics."""
        findings = [
            Finding(
                rule_id="NakedExceptionPass",
                severity="critical",
                file_path="test.py",
                line=10,
                message="Critical issue",
                autofix_applied=False,
            ),
            Finding(
                rule_id="NakedExceptionPass",
                severity="high",
                file_path="test.py",
                line=20,
                message="High issue",
                autofix_applied=False,
            ),
            Finding(
                rule_id="HedgeComment",
                severity="medium",
                file_path="test.py",
                line=5,
                message="Medium issue",
                autofix_applied=False,
            ),
            Finding(
                rule_id="UnusedImport",
                severity="low",
                file_path="test.py",
                line=1,
                message="Low issue",
                autofix_applied=False,
            ),
        ]

        report = JSONReporter.generate(findings)

        assert report["summary"]["total"] == 4
        assert report["summary"]["by_severity"]["critical"] == 1
        assert report["summary"]["by_severity"]["high"] == 1
        assert report["summary"]["by_severity"]["medium"] == 1
        assert report["summary"]["by_severity"]["low"] == 1
        assert report["summary"]["by_rule"]["NakedExceptionPass"] == 2
        assert report["summary"]["by_rule"]["HedgeComment"] == 1
        assert report["summary"]["by_rule"]["UnusedImport"] == 1
