# SIOF v2.0 Architecture

This document describes the complete architecture of SIOF v2.0, an enterprise-grade distributed system for semantic code analysis.

## Overview

SIOF v2.0 is built on a modular, pluggable architecture that enables:
- **Horizontal scaling** across multiple machines
- **Flexible deployment** (standalone, distributed, edge)
- **Multiple storage backends** (SQLite, Neo4j, FalkorDB)
- **Enterprise features** (JWT auth, Redis caching, audit logging)
- **Semantic search** with vector embeddings
- **Full observability** (metrics, tracing, logging)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      SIOF v2.0 System                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Parallel   │  │  Semantic    │  │  Enterprise  │    │
│  │   Indexer    │  │   Search     │  │  MCP Server  │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                  │                  │            │
│         └──────────────────┼──────────────────┘            │
│                            │                               │
│  ┌─────────────────────────┴────────────────────────────┐ │
│  │              Core Abstraction Layer                   │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │ │
│  │  │ Storage  │ │  Cache   │ │   Auth   │ │ Metrics │ │ │
│  │  │Interface │ │Interface │ │Interface │ │Interface│ │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │ │
│  └───────────────────────────────────────────────────────┘ │
│                            │                               │
│  ┌─────────────────────────┴────────────────────────────┐ │
│  │           Pluggable Implementations                   │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │ │
│  │  │  Neo4j   │ │  Redis   │ │   JWT    │ │Prometheus│ │
│  │  │ FalkorDB │ │  Memory  │ │ Session  │ │ Jaeger  │ │ │
│  │  │  SQLite  │ │          │ │ API Key  │ │         │ │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Interface Layer (`src/siof/v2/interfaces.py`)

Defines abstract base classes for all pluggable components:

- **StorageBackend**: Graph database abstraction
- **CacheBackend**: Caching layer abstraction
- **AuthProvider**: Authentication abstraction
- **VectorStore**: Vector database abstraction
- **CodeEmbedder**: Code embedding abstraction
- **ParallelExecutor**: Parallel processing abstraction
- **MetricsCollector**: Metrics collection abstraction
- **TracingProvider**: Distributed tracing abstraction

### 2. Mock Implementations (`src/siof/v2/mocks.py`)

In-memory implementations for testing and development:

- **MockStorageBackend**: In-memory graph storage
- **MockCacheBackend**: In-memory cache with TTL
- **MockAuthProvider**: Simple token-based auth
- **MockVectorStore**: In-memory vector search
- **MockCodeEmbedder**: Deterministic embeddings
- **MockParallelExecutor**: Synchronous execution
- **MockMetricsCollector**: In-memory metrics
- **MockTracingProvider**: In-memory traces

### 3. Configuration System (`src/siof/v2/config.py`)

Flexible configuration management:

```python
from siof.v2.config import SIOFv2Config

# Load from environment
config = SIOFv2Config.from_env()

# Load from YAML
config = SIOFv2Config.from_yaml("config.yaml")

# Validate
errors = config.validate()
if errors:
    print(f"Configuration errors: {errors}")
```

## Storage Backends

### SQLite (v1.0 Compatible)

```yaml
storage:
  backend: sqlite
  connection_string: siof.db
```

**Pros**: Simple, no dependencies, good for development
**Cons**: Single-node only, limited scalability

### Neo4j (Recommended for Production)

```yaml
storage:
  backend: neo4j
  connection_string: bolt://neo4j:7687
  options:
    username: ${NEO4J_USERNAME}
    password: ${NEO4J_PASSWORD}
```

**Pros**: ACID transactions, powerful graph queries, mature ecosystem
**Cons**: Higher resource usage, requires separate service

### FalkorDB (High Performance)

```yaml
storage:
  backend: falkordb
  connection_string: redis://redis:6379
```

**Pros**: Redis-based, extremely fast reads, low latency
**Cons**: Less mature than Neo4j, fewer features

## Cache Layer

### Memory Cache (Development)

```yaml
cache:
  enabled: true
  backend: memory
  max_size_mb: 100
```

**Pros**: No dependencies, fast
**Cons**: Not shared across instances

### Redis Cache (Production)

```yaml
cache:
  enabled: true
  backend: redis
  connection_string: redis://redis:6379
  ttl_seconds: 600
```

**Pros**: Distributed, persistent, battle-tested
**Cons**: Requires Redis service

## Authentication

### JWT (Stateless)

```yaml
auth:
  enabled: true
  provider: jwt
  jwt_secret: ${JWT_SECRET}
  jwt_algorithm: RS256
  token_expiry_seconds: 1800
```

**Pros**: Stateless, scalable, standard
**Cons**: Cannot revoke tokens easily

### Session (Stateful)

```yaml
auth:
  enabled: true
  provider: session
  options:
    redis_url: redis://redis:6379
```

**Pros**: Easy revocation, server-side control
**Cons**: Requires shared state (Redis)

### API Key (Service-to-Service)

```yaml
auth:
  enabled: true
  provider: apikey
  options:
    keys_file: /etc/siof/api-keys.yaml
```

**Pros**: Simple, no expiry management
**Cons**: Less secure, harder to rotate

## Semantic Search

### Transformer Embeddings

```yaml
semantic_search:
  enabled: true
  embedder: transformer
  model_name: sentence-transformers/all-MiniLM-L6-v2
  vector_store: milvus
  connection_string: http://milvus:19530
```

**Pros**: Open source, runs locally, good quality
**Cons**: Requires GPU for fast inference

### OpenAI Embeddings

```yaml
semantic_search:
  enabled: true
  embedder: openai
  options:
    api_key: ${OPENAI_API_KEY}
    model: text-embedding-3-small
```

**Pros**: High quality, no infrastructure
**Cons**: Costs money, requires API access

## Parallel Processing

### Thread Pool (Python 3.14+)

```yaml
parallel:
  enabled: true
  executor: thread
  max_workers: 32
```

**Pros**: Low overhead, shared memory, free-threaded
**Cons**: Requires Python 3.14+

### Process Pool (Fallback)

```yaml
parallel:
  enabled: true
  executor: process
  max_workers: 8
```

**Pros**: Works on older Python, true parallelism
**Cons**: Higher overhead, no shared memory

## Observability

### Prometheus Metrics

```yaml
observability:
  metrics_enabled: true
  metrics_port: 9090
```

Exposes metrics at `http://localhost:9090/metrics`:
- `siof_requests_total` - Total requests
- `siof_request_duration_seconds` - Request latency
- `siof_parse_files_total` - Files parsed
- `siof_cache_hits_total` - Cache hit rate

### Distributed Tracing

```yaml
observability:
  tracing_enabled: true
  tracing_endpoint: http://jaeger:14268/api/traces
```

Traces operations across services:
- Parse file → Extract symbols → Build graph → Store nodes

### Logging

```yaml
observability:
  logging_level: INFO
```

Structured JSON logging with correlation IDs.

## Deployment Modes

### Standalone

```yaml
deployment:
  mode: standalone
  replicas: 1
```

Single instance, all components in one process.

### Distributed

```yaml
deployment:
  mode: distributed
  replicas: 3
  options:
    load_balancer: round_robin
    session_affinity: true
```

Multiple instances, shared storage and cache.

### Edge

```yaml
deployment:
  mode: edge
  region: us-east-1
  options:
    cdn_enabled: true
    cache_ttl: 3600
```

Deployed at edge locations for low latency.

## Performance Characteristics

| Operation | v1.0 | v2.0 (Standalone) | v2.0 (Distributed) |
|-----------|------|-------------------|---------------------|
| Parse 100 files | 1.0s | 0.1s | 0.05s |
| Query lineage | 50ms | 10ms | 5ms |
| Semantic search | N/A | 20ms | 10ms |
| Max nodes | 100K | 1M | 10M |
| Concurrent users | 10 | 100 | 1000 |

## Migration from v1.0

### Step 1: Export v1.0 Data

```bash
siof export --db siof.db --output export.json
```

### Step 2: Configure v2.0

```yaml
# config.yaml
storage:
  backend: neo4j
  connection_string: bolt://localhost:7687
```

### Step 3: Import to v2.0

```bash
siof v2 import --config config.yaml --input export.json
```

### Step 4: Verify

```bash
siof v2 verify --config config.yaml
```

## Testing Strategy

### Unit Tests

Test individual components with mocks:

```python
from siof.v2.mocks import MockStorageBackend

def test_storage():
    storage = MockStorageBackend()
    storage.connect()
    # Test operations
```

### Integration Tests

Test component interactions:

```python
def test_cache_and_storage():
    storage = MockStorageBackend()
    cache = MockCacheBackend()
    # Test caching behavior
```

### E2E Tests

Test complete workflows:

```python
def test_full_pipeline():
    config = SIOFv2Config()
    # Run complete indexing pipeline
```

## Security Considerations

### Authentication

- Use RS256 (asymmetric) JWT in production
- Rotate keys regularly
- Store secrets in Kubernetes Secrets or Vault

### Authorization

- Implement RBAC with roles: viewer, analyst, admin
- Audit all mutations
- Rate limit per organization

### Network

- Use TLS for all connections
- Enable mTLS for service-to-service
- Implement network policies in Kubernetes

### Data

- Encrypt sensitive data at rest
- Use encrypted connections (SSL/TLS)
- Implement data retention policies

## Monitoring and Alerting

### Key Metrics

- **Availability**: Uptime percentage
- **Latency**: P50, P95, P99 response times
- **Throughput**: Requests per second
- **Error Rate**: Percentage of failed requests
- **Resource Usage**: CPU, memory, disk

### Alert Rules

```yaml
alerts:
  - name: HighErrorRate
    condition: error_rate > 0.05
    duration: 5m
    severity: critical

  - name: HighLatency
    condition: p95_latency > 1s
    duration: 5m
    severity: warning

  - name: LowCacheHitRate
    condition: cache_hit_rate < 0.7
    duration: 10m
    severity: info
```

## Cost Optimization

### Development

- Use SQLite + memory cache
- Disable semantic search
- Single replica
- **Cost**: $0/month

### Small Production

- Neo4j Community + Redis
- 2 replicas
- Basic monitoring
- **Cost**: ~$200/month

### Enterprise

- Neo4j Enterprise + Redis Enterprise
- 10+ replicas
- Full observability
- Multi-region
- **Cost**: ~$2000/month

## Next Steps

1. Review the [V2 Roadmap](V2_ROADMAP.md)
2. Try the [development configuration](../deploy/config/siof-v2-development.yaml)
3. Run the [v2.0 tests](../tests/test_v2_interfaces.py)
4. Deploy using [Helm charts](../deploy/helm/)

---

**Status**: Architecture Complete
**Last Updated**: 2026-04-03
**Version**: 2.0.0-alpha
