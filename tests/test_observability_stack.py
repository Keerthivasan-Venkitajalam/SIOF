from __future__ import annotations

import json

from siof.observability import (
    AlertManager,
    AlertRule,
    LogAggregator,
    MetricsExporter,
    TelemetryCollector,
)


def test_telemetry_collector_correlation_and_span():
    collector = TelemetryCollector()
    cid = collector.create_correlation_id()
    assert collector.get_correlation_id() == cid

    with collector.create_span("test.operation", attributes={"k": "v"}) as span:
        collector.add_event(span, "started")

    spans = collector.flush()
    assert len(spans) == 1
    assert spans[0].operation_name == "test.operation"
    assert spans[0].correlation_id == cid


def test_metrics_exporter_prometheus_render_and_cardinality():
    exporter = MetricsExporter()
    exporter.register_metric("custom_counter", "counter", "A custom counter", max_cardinality=1)
    exporter.increment_counter("custom_counter", labels={"tenant": "a"})
    exporter.increment_counter("custom_counter", labels={"tenant": "b"})

    text = exporter.render_prometheus()
    assert "custom_counter" in text
    assert "siof_metric_cardinality_drops_total" in text


def test_log_aggregator_json_and_query_filters():
    aggregator = LogAggregator()
    entry = aggregator.build_entry(
        level="info",
        logger="siof.test",
        message="hello",
        tenant_id="tenant-a",
        component="mcp",
    )
    line = aggregator.emit(entry)
    parsed = json.loads(line)
    assert parsed["message"] == "hello"

    found = aggregator.query(tenant_id="tenant-a", component="mcp")
    assert len(found) == 1


def test_alert_manager_trigger_and_resolve_cycle():
    alerts = []

    class Sink:
        def send(self, alert):
            alerts.append(alert)

    manager = AlertManager()
    manager.register_channel(Sink())
    manager.register_rule(
        AlertRule(
            name="high_latency",
            metric="latency_p95_seconds",
            threshold=1.0,
            comparator=">",
            duration_seconds=0,
            severity="critical",
        )
    )

    emitted = manager.evaluate({"latency_p95_seconds": 1.2}, now=100)
    assert any(a.status == "firing" for a in emitted)

    emitted = manager.evaluate({"latency_p95_seconds": 0.3}, now=101)
    assert any(a.status == "resolved" for a in emitted)
    assert len(alerts) >= 2
