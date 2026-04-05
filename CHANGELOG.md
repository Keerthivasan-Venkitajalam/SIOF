# Changelog

## 2.0.1 - 2026-04-05

### Changed
- Updated README architecture diagram to reflect the v2 system layout (core pipelines, enterprise control plane, distributed storage, and observability/deployment layers).
- Updated release documentation to show trusted publishing tag flow and PyPI filename immutability constraints for re-releases.
- Added GitHub Actions publish permission `attestations: write` for the PyPI publish job.

### Notes
- This patch release is used to republish v2 after a prior `2.0.0` release was removed.

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
