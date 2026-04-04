# Changelog

## 2.0.0 - 2026-04-04

### Added
- Enterprise modules for authentication, RBAC, API key management, sessions, rate limiting, and auditing.
- Distributed storage abstractions and backend implementations for Neo4j and FalkorDB.
- Free-threaded parsing and indexing support with compatibility fallback behavior.
- Observability stack components for telemetry, metrics, logs, tracing, alerts, and health checks.
- Vector semantic search modules including embedding, cache, vector store, intent query, and DTG integration helpers.
- Edge deployment modules for regional cache, replication, failover, endpoint routing, and deployment management.
- Helm/Kubernetes/K3s/observability/Milvus deployment artifacts and guides.

### Changed
- Unified package versioning to `2.0.0` across project metadata and runtime constants.
- Added optional dependency groups for storage backends and release tooling.

### Notes
- This release targets Python 3.11+.
- Free-threaded parallel mode is automatically enabled only on compatible Python builds.
