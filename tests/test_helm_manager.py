from __future__ import annotations

from siof.deploy import HelmChartManager


def test_helm_chart_manager_validates_chart_structure():
    manager = HelmChartManager(chart_dir="deploy/helm/siof")
    assert manager.validate_chart() is True


def test_helm_chart_manager_render_templates_returns_yaml_list():
    manager = HelmChartManager(chart_dir="deploy/helm/siof")
    docs = manager.render_templates("values.yaml")
    assert docs
    assert any("kind: Deployment" in d for d in docs)


def test_helm_chart_install_and_status():
    manager = HelmChartManager(chart_dir="deploy/helm/siof")
    status = manager.install(namespace="siof", values_file="values-dev.yaml")
    assert status.installed is True
    assert status.namespace == "siof"
