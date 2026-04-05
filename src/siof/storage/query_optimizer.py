"""Query optimizer for distributed graph queries."""

import hashlib
import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ExecutionStrategy(Enum):
    """Query execution strategy for distributed queries.

    Attributes:
        SINGLE_SHARD: Execute on a single shard (best for filtered queries)
        MULTI_SHARD: Execute across multiple shards with coordination
        BROADCAST: Broadcast query to all shards (for full graph scans)
    """

    SINGLE_SHARD = "single_shard"
    MULTI_SHARD = "multi_shard"
    BROADCAST = "broadcast"


class QueryOptimizer:
    """Optimize queries for distributed execution.

    This class analyzes query patterns and chooses optimal execution strategies
    to minimize latency and resource usage in distributed graph scenarios.

    Attributes:
        plan_cache: Cache of optimized query plans
        plan_cache_size: Maximum number of cached plans
    """

    def __init__(self, plan_cache_size: int = 100) -> None:
        """Initialize QueryOptimizer.

        Args:
            plan_cache_size: Maximum number of cached plans (default: 100)

        Raises:
            ValueError: If plan_cache_size is invalid
        """
        if plan_cache_size < 0:
            raise ValueError(f"plan_cache_size must be non-negative, got {plan_cache_size}")

        self.plan_cache: dict[str, dict[str, Any]] = {}
        self.plan_cache_size = plan_cache_size

    def optimize(self, query: str, params: dict[str, Any]) -> dict[str, Any]:
        """Analyze query and choose optimal execution strategy.

        This method analyzes the query structure and parameters to determine
        the best execution strategy for distributed execution.

        Args:
            query: Query string (Cypher or similar)
            params: Query parameters

        Returns:
            Dictionary containing:
            - strategy: ExecutionStrategy enum value
            - push_down_filters: List of filters that can be pushed to backend
            - estimated_cost: Estimated query cost (lower is better)
            - plan_id: Unique identifier for this plan
        """
        logger.debug(f"Optimizing query: {query[:100]}...")

        # Create cache key
        cache_key = self._make_cache_key(query)

        # Check cache
        if cache_key in self.plan_cache:
            logger.debug("Using cached plan for query")
            return self.plan_cache[cache_key]

        # Analyze query
        strategy = self._analyze_query(query)
        filters = self._extract_filters(query)
        cost = self._estimate_cost(query, strategy)

        plan = {
            "strategy": strategy,
            "push_down_filters": filters,
            "estimated_cost": cost,
            "plan_id": cache_key,
        }

        # Cache plan if cache not full
        if len(self.plan_cache) < self.plan_cache_size:
            self.plan_cache[cache_key] = plan
            logger.debug(f"Cached query plan: {cache_key}")
        else:
            logger.debug("Plan cache full, not caching new plan")

        return plan

    def _analyze_query(self, query: str) -> ExecutionStrategy:
        """Determine optimal execution strategy for query.

        Uses heuristics to classify queries:
        - Queries with specific node IDs in MATCH clause -> SINGLE_SHARD
        - Queries with WHERE clauses -> MULTI_SHARD
        - Full graph scans -> BROADCAST

        Args:
            query: Query string

        Returns:
            ExecutionStrategy enum value
        """
        query_upper = query.upper()

        # Check for specific node ID filters in MATCH clause (best case for single shard)
        # Look for patterns like {id: $id} or {id: "value"}
        if "{id:" in query.lower() or "id: $" in query.lower():
            logger.debug("Query has specific node ID filter, using SINGLE_SHARD")
            return ExecutionStrategy.SINGLE_SHARD

        # Check for WHERE clause (can be optimized for multi-shard)
        if "WHERE" in query_upper:
            logger.debug("Query has WHERE clause, using MULTI_SHARD")
            return ExecutionStrategy.MULTI_SHARD

        # Default to broadcast for full graph scans
        logger.debug("Query is full graph scan, using BROADCAST")
        return ExecutionStrategy.BROADCAST

    def _extract_filters(self, query: str) -> list[str]:
        """Extract filter conditions that can be pushed to backend.

        Identifies WHERE clause conditions that can be executed at the
        backend level rather than in the application.

        Args:
            query: Query string

        Returns:
            List of filter strings
        """
        filters: list[str] = []

        try:
            # Simple extraction: find WHERE clause
            query_upper = query.upper()
            where_idx = query_upper.find("WHERE")

            if where_idx == -1:
                return filters

            # Extract WHERE clause content
            where_clause = query[where_idx + 5 :].strip()

            # Split by AND/OR
            conditions = []
            for part in where_clause.split("AND"):
                part = part.strip()
                if part:
                    conditions.append(part)

            filters = conditions
            logger.debug(f"Extracted {len(filters)} pushdown filters")

        except Exception as e:
            logger.debug(f"Failed to extract filters: {e}")

        return filters

    def _estimate_cost(self, query: str, strategy: ExecutionStrategy) -> float:
        """Estimate query cost for different strategies.

        Cost estimation is based on:
        - Strategy type (single shard is cheapest)
        - Query complexity (number of joins, aggregations)
        - Result set size (estimated)

        Args:
            query: Query string
            strategy: ExecutionStrategy to estimate cost for

        Returns:
            Estimated cost (lower is better)
        """
        base_cost = 1.0

        # Strategy multiplier
        if strategy == ExecutionStrategy.SINGLE_SHARD:
            strategy_multiplier = 1.0
        elif strategy == ExecutionStrategy.MULTI_SHARD:
            strategy_multiplier = 5.0
        else:  # BROADCAST
            strategy_multiplier = 10.0

        # Complexity multiplier based on query features
        complexity_multiplier = 1.0

        query_upper = query.upper()

        # Count joins (MATCH clauses) - only add cost if more than 1
        match_count = query_upper.count("MATCH")
        if match_count > 1:
            complexity_multiplier *= 1.0 + (match_count - 1) * 0.5

        # Check for aggregations
        if "AGGREGATE" in query_upper or "COUNT" in query_upper:
            complexity_multiplier *= 2.0

        # Check for sorting
        if "ORDER BY" in query_upper:
            complexity_multiplier *= 1.5

        # Check for DISTINCT
        if "DISTINCT" in query_upper:
            complexity_multiplier *= 1.2

        estimated_cost = base_cost * strategy_multiplier * complexity_multiplier

        logger.debug(
            f"Estimated cost: {estimated_cost:.2f} "
            f"(strategy={strategy.value}, complexity={complexity_multiplier:.2f})"
        )

        return estimated_cost

    def _make_cache_key(self, query: str) -> str:
        """Create cache key from query string.

        Uses SHA256 hash of query to create a unique, fixed-size key.

        Args:
            query: Query string

        Returns:
            Cache key (hex string)
        """
        # Normalize query: remove extra whitespace
        normalized = " ".join(query.split())

        # Create hash
        hash_obj = hashlib.sha256(normalized.encode())
        cache_key = hash_obj.hexdigest()[:16]  # Use first 16 chars

        return cache_key

    def clear_cache(self) -> None:
        """Clear all cached query plans."""
        self.plan_cache.clear()
        logger.debug("Query plan cache cleared")

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary containing cache statistics
        """
        return {
            "cached_plans": len(self.plan_cache),
            "max_cache_size": self.plan_cache_size,
            "cache_utilization": (
                len(self.plan_cache) / self.plan_cache_size if self.plan_cache_size > 0 else 0.0
            ),
        }
