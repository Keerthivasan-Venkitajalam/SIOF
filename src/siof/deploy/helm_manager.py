"""Minimal Helm chart validation and rendering helper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DeploymentStatus:
    installed: bool
    namespace: str
    chart_version: str
    release_name: str


class HelmChartManager:
    """Utility for validating chart file structure and values."""

    def __init__(self, chart_dir: str | Path = "deploy/helm/siof"):
        self.chart_dir = Path(chart_dir)
        self._installed = False
        self._namespace = "default"
        self._release_name = "siof"
        self._chart_version = "unknown"

    def validate_chart(self) -> bool:
        required = [
            self.chart_dir / "Chart.yaml",
            self.chart_dir / "values.yaml",
            self.chart_dir / "values.schema.json",
            self.chart_dir / "README.md",
            self.chart_dir / "templates",
        ]
        if not all(path.exists() for path in required):
            return False
        chart_text = (self.chart_dir / "Chart.yaml").read_text(encoding="utf-8")
        for line in chart_text.splitlines():
            if line.startswith("version:"):
                self._chart_version = line.split(":", 1)[1].strip()
                break
        return True

    def render_templates(self, values_file: str | Path = "values.yaml") -> list[str]:
        values_path = self.chart_dir / values_file
        if not values_path.exists():
            raise FileNotFoundError(values_path)
        template_dir = self.chart_dir / "templates"
        rendered: list[str] = []
        for file_path in sorted(template_dir.rglob("*.yaml")):
            rendered.append(file_path.read_text(encoding="utf-8"))
        return rendered

    def install(self, namespace: str, values_file: str = "values.yaml", release_name: str = "siof") -> DeploymentStatus:
        if not self.validate_chart():
            raise RuntimeError("Chart validation failed")
        self.render_templates(values_file)
        self._installed = True
        self._namespace = namespace
        self._release_name = release_name
        return self.get_status()

    def upgrade(self, namespace: str, values_file: str = "values.yaml") -> DeploymentStatus:
        if not self._installed:
            return self.install(namespace=namespace, values_file=values_file)
        self.render_templates(values_file)
        self._namespace = namespace
        return self.get_status()

    def rollback(self) -> DeploymentStatus:
        # No-op in lightweight manager.
        return self.get_status()

    def get_status(self) -> DeploymentStatus:
        return DeploymentStatus(
            installed=self._installed,
            namespace=self._namespace,
            chart_version=self._chart_version,
            release_name=self._release_name,
        )
