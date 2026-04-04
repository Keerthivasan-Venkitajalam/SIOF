from __future__ import annotations

from siof.edge import (
    EdgeDeploymentManager,
    FailoverController,
    RegionalCacheManager,
    RegionalEndpointRegistry,
    ReplicationManager,
)


def test_regional_cache_manager_set_get_and_stats():
    cache = RegionalCacheManager(ttl_seconds=10, max_entries=2)
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.get_stats()["hits"] >= 1


def test_replication_manager_event_and_status():
    mgr = ReplicationManager()
    event = mgr.create_event(
        operation="create",
        resource_type="node",
        resource_id="n1",
        payload={"x": 1},
    )
    status = mgr.replicate_event(event, ["us-east", "eu-west"])
    assert status["us-east"] == "in_sync"


def test_failover_controller_promotes_replica():
    fc = FailoverController(primary_region="us-east")
    fc.report_health("us-east", healthy=False)
    fc.report_health("us-east", healthy=False)
    fc.report_health("us-east", healthy=False)
    check = fc.check_primary_health()
    assert check["ready_for_failover"] is True
    ev = fc.trigger_failover("eu-west")
    assert ev.new_primary == "eu-west"


def test_endpoint_registry_returns_preferred_healthy_endpoint():
    reg = RegionalEndpointRegistry()
    reg.register_endpoint("us-east", "https://use.example.com")
    reg.register_endpoint("eu-west", "https://euw.example.com")
    assert reg.get_nearest_endpoint(["eu-west"]) == "https://euw.example.com"


def test_edge_deployment_manager_reports_region_health():
    manager = EdgeDeploymentManager()
    status = manager.deploy_region("us-east", {"mode": "single-node"})
    assert status.status in {"ready", "failed"}
    health = manager.get_region_health("us-east")
    assert health["region_id"] == "us-east"
