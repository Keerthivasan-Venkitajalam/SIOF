from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .models import Finding
from .storage import Storage

logger = logging.getLogger(__name__)

HEDGE_WORDS = [
    "robust",
    "comprehensive",
    "seamless",
    "cutting-edge",
    "world-class",
    "elegant",
    "sophisticated",
    "powerful",
    "revolutionary",
]


@dataclass(slots=True)
class SlopResult:
    findings: list[Finding]
    files_changed: int


class DeSlopper:
    """Detects and fixes AI-generated code anti-patterns."""

    def __init__(self, repo: Path, db_path: Path):
        self.repo = repo
        self.db = Storage(db_path)
        self.db.init_schema()
        logger.info(f"Initialized DeSlopper for {repo}")

    def close(self) -> None:
        self.db.close()

    def run(self, mode: str = "audit") -> SlopResult:
        """Run slop detection and optionally fix issues.
        
        Modes:
        - audit: detect only, no mutations
        - fix: apply safe fixes
        - strict: fail if high-severity findings exist
        """
        logger.info(f"Running DeSlopper in {mode} mode")
        findings: list[Finding] = []
        files_changed = 0
        self.db.clear_findings()

        for py_file in self._python_files():
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                logger.error(f"Failed to read {py_file}: {exc}")
                continue

            file_findings = self._scan_file(py_file, text)
            mutated = text
            if mode == "fix":
                mutated, autofixed = self._autofix(text)
                if autofixed:
                    try:
                        py_file.write_text(mutated, encoding="utf-8")
                        files_changed += 1
                        logger.info(f"Fixed {py_file}")
                    except Exception as exc:
                        logger.error(f"Failed to write {py_file}: {exc}")
                for f in file_findings:
                    if f.rule_id == "NakedExceptionPass" and autofixed:
                        f.autofix_applied = True
            findings.extend(file_findings)

        self.db.insert_findings(findings)

        high_severity = [f for f in findings if f.severity in {"high", "critical"}]
        if mode == "strict" and high_severity:
            logger.error(f"Strict mode failed: {len(high_severity)} high-severity findings")
            raise RuntimeError("strict mode failed due to high-severity findings")

        logger.info(f"DeSlopper complete: {len(findings)} findings, {files_changed} files changed")
        return SlopResult(findings=findings, files_changed=files_changed)

    def _python_files(self) -> list[Path]:
        return [
            p
            for p in self.repo.rglob("*.py")
            if ".venv" not in p.parts and "__pycache__" not in p.parts
        ]

    def _scan_file(self, py_file: Path, text: str) -> list[Finding]:
        """Scan a file for all slop patterns."""
        findings: list[Finding] = []
        rel = str(py_file.relative_to(self.repo))

        # Rule: except: pass (bare exception with pass)
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if node.type is None and self._handler_has_only_pass(node):
                        findings.append(
                            Finding(
                                rule_id="NakedExceptionPass",
                                severity="high",
                                file_path=rel,
                                line=node.lineno,
                                message="Bare exception with pass detected",
                            )
                        )
                    # Rule: broad exception catching (except Exception: pass)
                    elif (
                        isinstance(node.type, ast.Name)
                        and node.type.id == "Exception"
                        and self._handler_has_only_pass(node)
                    ):
                        findings.append(
                            Finding(
                                rule_id="BroadExceptionPass",
                                severity="high",
                                file_path=rel,
                                line=node.lineno,
                                message="Broad exception catch with pass detected",
                            )
                        )
        except SyntaxError as exc:
            findings.append(
                Finding(
                    rule_id="ParseError",
                    severity="medium",
                    file_path=rel,
                    line=1,
                    message="File parse failed; unable to apply AST rules",
                )
            )
            logger.warning(f"Parse error in {rel}: {exc}")

        # Rule: hedge words in comments/docstrings
        for idx, line in enumerate(text.splitlines(), start=1):
            s = line.strip().lower()
            if s.startswith("#") and any(w in s for w in HEDGE_WORDS):
                findings.append(
                    Finding(
                        rule_id="HedgeComment",
                        severity="low",
                        file_path=rel,
                        line=idx,
                        message="Hedge-word comment detected",
                    )
                )

        # Rule: likely echo comment (comments that just repeat code)
        echo_pattern = re.compile(r"^\s*#\s*(set|get|initialize|create|update|return|define|check|validate)\b", re.IGNORECASE)
        for idx, line in enumerate(text.splitlines(), start=1):
            if echo_pattern.match(line):
                findings.append(
                    Finding(
                        rule_id="EchoComment",
                        severity="low",
                        file_path=rel,
                        line=idx,
                        message="Potential echo comment",
                    )
                )

        # Rule: import that cannot be resolved (best-effort)
        findings.extend(self._hallucinated_import_findings(text, rel))

        # Rule: unused imports
        findings.extend(self._unused_import_findings(text, rel))

        return findings

    @staticmethod
    def _handler_has_only_pass(handler: ast.ExceptHandler) -> bool:
        if not handler.body:
            return False
        return len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)

    def _autofix(self, text: str) -> tuple[str, bool]:
        pattern = re.compile(r"except\s*:\s*\n(\s*)pass\b")
        changed = False

        def repl(m: re.Match[str]) -> str:
            nonlocal changed
            changed = True
            indent = m.group(1)
            return f"except Exception as exc:\n{indent}print(f'handled error: {{exc}}')"

        new_text = pattern.sub(repl, text)
        return new_text, changed

    def _hallucinated_import_findings(self, text: str, rel: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name.split(".")[0]
                    if self._is_suspicious_import(name):
                        findings.append(
                            Finding(
                                rule_id="SuspiciousImport",
                                severity="medium",
                                file_path=rel,
                                line=node.lineno,
                                message=f"Potential hallucinated import: {name}",
                            )
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                name = node.module.split(".")[0]
                if self._is_suspicious_import(name):
                    findings.append(
                        Finding(
                            rule_id="SuspiciousImport",
                            severity="medium",
                            file_path=rel,
                            line=node.lineno,
                            message=f"Potential hallucinated import: {name}",
                        )
                    )
        return findings

    @staticmethod
    def _is_suspicious_import(name: str) -> bool:
        """Check if an import name looks hallucinated."""
        # Standard library and common packages are not suspicious
        if name in {
            "os",
            "sys",
            "re",
            "json",
            "ast",
            "pathlib",
            "typing",
            "dataclasses",
            "sqlite3",
            "subprocess",
            "collections",
            "itertools",
            "math",
            "time",
            "datetime",
            "logging",
            "hashlib",
            "uuid",
            "argparse",
            "pathlib",
        }:
            return False
        # Suspicious if very long or has many x's (common in hallucinated names)
        return len(name) > 22 or name.count("x") > 3

    def _unused_import_findings(self, text: str, rel: str) -> list[Finding]:
        """Detect unused imports."""
        findings: list[Finding] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return findings

        # Collect all imports
        imports: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imports[name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imports[name] = node.lineno

        # Check usage (simple heuristic: search for name in code)
        code_lines = text.splitlines()
        for imp_name, imp_line in imports.items():
            # Skip if used in code after import
            used = False
            for idx, line in enumerate(code_lines, start=1):
                if idx > imp_line and imp_name in line and not line.strip().startswith("#"):
                    used = True
                    break
            if not used:
                findings.append(
                    Finding(
                        rule_id="UnusedImport",
                        severity="low",
                        file_path=rel,
                        line=imp_line,
                        message=f"Unused import: {imp_name}",
                    )
                )
        return findings
