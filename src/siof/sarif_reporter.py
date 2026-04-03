"""SARIF (Static Analysis Results Format) report generation for De-Slopper findings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Finding

logger_name = "siof.sarif_reporter"


@dataclass(slots=True)
class SARIFReport:
    """SARIF report container."""

    version: str
    runs: list[dict[str, Any]]


class SARIFReporter:
    """Generates SARIF reports from findings."""

    SARIF_VERSION = "2.1.0"

    @staticmethod
    def generate(findings: list[Finding], repo_path: Path | str = ".") -> dict[str, Any]:
        """Generate SARIF report from findings.

        Args:
            findings: List of findings to report
            repo_path: Repository root path

        Returns:
            SARIF report as dictionary
        """
        repo_path = Path(repo_path)

        # Group findings by file
        findings_by_file: dict[str, list[Finding]] = {}
        for finding in findings:
            if finding.file_path not in findings_by_file:
                findings_by_file[finding.file_path] = []
            findings_by_file[finding.file_path].append(finding)

        # Build results array
        results = []
        for file_path, file_findings in findings_by_file.items():
            for finding in file_findings:
                result = SARIFReporter._finding_to_result(finding, file_path)
                results.append(result)

        # Build rules array
        rules = SARIFReporter._build_rules(findings)

        # Build SARIF report
        report = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": SARIFReporter.SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "SIOF De-Slopper",
                            "version": "1.0.0",
                            "informationUri": "https://github.com/siof/siof",
                            "rules": rules,
                        }
                    },
                    "results": results,
                    "properties": {
                        "generatedAt": datetime.now(UTC).isoformat(),
                        "repositoryRoot": str(repo_path.absolute()),
                    },
                }
            ],
        }

        return report

    @staticmethod
    def _finding_to_result(finding: Finding, file_path: str) -> dict[str, Any]:
        """Convert a Finding to a SARIF result.

        Args:
            finding: Finding to convert
            file_path: File path for the finding

        Returns:
            SARIF result object
        """
        # Map severity to SARIF level
        level_map = {
            "critical": "error",
            "high": "error",
            "medium": "warning",
            "low": "note",
        }
        level = level_map.get(finding.severity, "warning")

        result = {
            "ruleId": finding.rule_id,
            "level": level,
            "message": {
                "text": finding.message,
            },
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": file_path,
                        },
                        "region": {
                            "startLine": finding.line,
                        },
                    }
                }
            ],
            "properties": {
                "autofix_applied": finding.autofix_applied,
            },
        }

        return result

    @staticmethod
    def _build_rules(findings: list[Finding]) -> list[dict[str, Any]]:
        """Build SARIF rules array from findings.

        Args:
            findings: List of findings

        Returns:
            List of SARIF rule objects
        """
        # Collect unique rules
        rules_by_id: dict[str, dict[str, Any]] = {}

        rule_descriptions = {
            "NakedExceptionPass": {
                "shortDescription": "Bare exception with pass detected",
                "fullDescription": "Bare except clause with pass statement swallows all exceptions, including hardware failures and network timeouts.",
                "help": "Replace with specific exception handling or log the error.",
            },
            "BroadExceptionPass": {
                "shortDescription": "Broad exception catch with pass detected",
                "fullDescription": "Catching Exception with pass statement swallows all exceptions, masking potential bugs.",
                "help": "Catch specific exceptions or log the error.",
            },
            "HedgeComment": {
                "shortDescription": "Hedge-word comment detected",
                "fullDescription": "Comment contains vague hedge words like 'robust', 'comprehensive', 'seamless' that don't add clarity.",
                "help": "Replace with specific, actionable comments.",
            },
            "EchoComment": {
                "shortDescription": "Potential echo comment",
                "fullDescription": "Comment merely restates what the code does without explaining why or the business logic.",
                "help": "Add comments that explain intent, not mechanics.",
            },
            "SuspiciousImport": {
                "shortDescription": "Potential hallucinated import",
                "fullDescription": "Import name looks suspicious and may be hallucinated by an AI model.",
                "help": "Verify the import exists and is necessary.",
            },
            "UnusedImport": {
                "shortDescription": "Unused import",
                "fullDescription": "Import is declared but never used in the code.",
                "help": "Remove unused imports.",
            },
            "ParseError": {
                "shortDescription": "File parse failed",
                "fullDescription": "File contains syntax errors and could not be parsed.",
                "help": "Fix syntax errors in the file.",
            },
        }

        for finding in findings:
            if finding.rule_id not in rules_by_id:
                desc = rule_descriptions.get(finding.rule_id, {})
                rules_by_id[finding.rule_id] = {
                    "id": finding.rule_id,
                    "shortDescription": {
                        "text": desc.get("shortDescription", finding.rule_id),
                    },
                    "fullDescription": {
                        "text": desc.get("fullDescription", ""),
                    },
                    "help": {
                        "text": desc.get("help", ""),
                    },
                    "defaultConfiguration": {
                        "level": "warning",
                    },
                }

        return list(rules_by_id.values())

    @staticmethod
    def write_sarif(
        findings: list[Finding], output_path: Path | str, repo_path: Path | str = "."
    ) -> None:
        """Write SARIF report to file.

        Args:
            findings: List of findings
            output_path: Path to write SARIF report
            repo_path: Repository root path
        """
        report = SARIFReporter.generate(findings, repo_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)


class JSONReporter:
    """Generates JSON reports from findings."""

    @staticmethod
    def generate(findings: list[Finding]) -> dict[str, Any]:
        """Generate JSON report from findings.

        Args:
            findings: List of findings

        Returns:
            JSON report as dictionary
        """
        # Group by severity
        by_severity: dict[str, list[dict[str, Any]]] = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
        }

        for finding in findings:
            finding_dict = asdict(finding)
            by_severity[finding.severity].append(finding_dict)

        # Summary statistics
        summary = {
            "total": len(findings),
            "by_severity": {
                "critical": len(by_severity["critical"]),
                "high": len(by_severity["high"]),
                "medium": len(by_severity["medium"]),
                "low": len(by_severity["low"]),
            },
            "by_rule": {},
        }

        # Count by rule
        for finding in findings:
            if finding.rule_id not in summary["by_rule"]:
                summary["by_rule"][finding.rule_id] = 0
            summary["by_rule"][finding.rule_id] += 1

        report = {
            "summary": summary,
            "findings": {
                "critical": by_severity["critical"],
                "high": by_severity["high"],
                "medium": by_severity["medium"],
                "low": by_severity["low"],
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }

        return report

    @staticmethod
    def write_json(findings: list[Finding], output_path: Path | str) -> None:
        """Write JSON report to file.

        Args:
            findings: List of findings
            output_path: Path to write JSON report
        """
        report = JSONReporter.generate(findings)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
