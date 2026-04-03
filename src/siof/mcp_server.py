"""MCP Graph Server with schema validation, RBAC, and tracing.

Implements the Model Context Protocol for exposing DTG graph queries
with full authorization, schema validation, and observability.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, ClassVar

from .policy import PolicyContext, PolicyEngine
from .repository import Repository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MCPRequest:
    """MCP tool request."""
    tool: str
    args: dict[str, Any]
    role: str = "reader"
    approval_token: str | None = None
    org: str = "default"
    user_id: str | None = None
    request_id: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            object.__setattr__(self, "request_id", str(uuid.uuid4()))


@dataclass(slots=True)
class MCPResponse:
    """MCP tool response."""
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    request_id: str = ""
    latency_ms: float = 0.0
    trace_id: str = ""


class SchemaValidator:
    """JSON schema validator for MCP tool arguments."""

    TOOL_SCHEMAS: ClassVar[dict[str, dict]] = {
        "find_data_lineage": {
            "required": ["node_or_symbol"],
            "properties": {
                "node_or_symbol": {"type": "string", "minLength": 1},
                "depth": {"type": "integer", "minimum": 1, "maximum": 10},
            },
        },
        "impact_of_change": {
            "required": ["file_or_symbol"],
            "properties": {
                "file_or_symbol": {"type": "string", "minLength": 1},
            },
        },
        "validate_relationship": {
            "required": ["source", "target"],
            "properties": {
                "source": {"type": "string", "minLength": 1},
                "target": {"type": "string", "minLength": 1},
                "relation": {"type": "string", "enum": ["any", "transforms", "depends_on"]},
            },
        },
        "get_dead_paths": {
            "required": [],
            "properties": {
                "scope": {"type": "string"},
            },
        },
        "find_unhandled_exceptions": {
            "required": [],
            "properties": {
                "scope": {"type": "string"},
            },
        },
        "get_intent_history": {
            "required": ["symbol_or_area"],
            "properties": {
                "symbol_or_area": {"type": "string", "minLength": 1},
            },
        },
        "get_run_energy": {
            "required": ["run_id"],
            "properties": {
                "run_id": {"type": "string", "minLength": 1},
            },
        },
        "apply_patch_to_file": {
            "required": ["file_path", "patch"],
            "properties": {
                "file_path": {"type": "string", "minLength": 1},
                "patch": {"type": "string", "minLength": 1},
            },
        },
    }

    @classmethod
    def validate(cls, tool: str, args: dict[str, Any]) -> tuple[bool, str | None]:
        """Validate tool arguments against schema.

        Args:
            tool: Tool name
            args: Tool arguments

        Returns:
            Tuple of (is_valid, error_message)
        """
        schema = cls.TOOL_SCHEMAS.get(tool)
        if not schema:
            return False, f"Unknown tool: {tool}"

        # Check required fields
        for required in schema.get("required", []):
            if required not in args:
                return False, f"Missing required argument: {required}"

        # Validate field types and constraints
        for field_name, field_value in args.items():
            if field_name not in schema.get("properties", {}):
                return False, f"Unknown argument: {field_name}"

            field_schema = schema["properties"][field_name]
            field_type = field_schema.get("type")

            # Type check
            if field_type == "string" and not isinstance(field_value, str):
                return False, f"Argument {field_name} must be string"
            if field_type == "integer" and not isinstance(field_value, int):
                return False, f"Argument {field_name} must be integer"

            # Constraint checks
            if "minLength" in field_schema and len(str(field_value)) < field_schema["minLength"]:
                return False, f"Argument {field_name} too short"
            if "minimum" in field_schema and field_value < field_schema["minimum"]:
                return False, f"Argument {field_name} below minimum"
            if "maximum" in field_schema and field_value > field_schema["maximum"]:
                return False, f"Argument {field_name} exceeds maximum"
            if "enum" in field_schema and field_value not in field_schema["enum"]:
                return False, f"Argument {field_name} not in allowed values"

        return True, None


class Tracer:
    """Simple distributed tracing for MCP requests."""

    def __init__(self):
        """Initialize tracer."""
        self.traces: dict[str, dict[str, Any]] = {}

    def start_span(self, trace_id: str, span_name: str) -> None:
        """Start a trace span.

        Args:
            trace_id: Trace identifier
            span_name: Span name
        """
        if trace_id not in self.traces:
            self.traces[trace_id] = {
                "trace_id": trace_id,
                "spans": [],
                "start_time": time.time(),
            }
        self.traces[trace_id]["spans"].append({
            "name": span_name,
            "start_time": time.time(),
        })

    def end_span(self, trace_id: str) -> None:
        """End the current trace span.

        Args:
            trace_id: Trace identifier
        """
        if trace_id in self.traces and self.traces[trace_id]["spans"]:
            span = self.traces[trace_id]["spans"][-1]
            span["end_time"] = time.time()
            span["duration_ms"] = (span["end_time"] - span["start_time"]) * 1000

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Get trace data.

        Args:
            trace_id: Trace identifier

        Returns:
            Trace data or None
        """
        return self.traces.get(trace_id)


class MCPGraphServer:
    """MCP server exposing graph query tools with full enterprise features.

    Features:
    - Schema validation for all tool arguments
    - RBAC with role hierarchy and rate limiting
    - Distributed tracing and metrics
    - Comprehensive error handling
    """

    def __init__(self, db_path: Path | str):
        """Initialize MCP server.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self.repo = Repository(self.db_path)
        self.repo.init()
        self.policy = PolicyEngine()
        self.validator = SchemaValidator()
        self.tracer = Tracer()
        self.metrics = {
            "total_requests": 0,
            "total_errors": 0,
            "total_latency_ms": 0.0,
            "tool_counts": {},
        }
        logger.info(f"Initialized MCP server with db at {db_path}")

    def close(self) -> None:
        """Close server and cleanup resources."""
        self.repo.close()
        logger.info("MCP server closed")

    def handle(self, request: MCPRequest) -> MCPResponse:
        """Handle a single MCP request with full validation and tracing.

        Args:
            request: MCP request

        Returns:
            MCP response
        """
        start_time = time.time()
        trace_id = str(uuid.uuid4())

        try:
            # Start tracing
            self.tracer.start_span(trace_id, "authorize")

            # Validate schema
            is_valid, error = self.validator.validate(request.tool, request.args)
            if not is_valid:
                logger.warning(f"Schema validation failed: {error}")
                return MCPResponse(
                    ok=False,
                    error=error,
                    request_id=request.request_id,
                    trace_id=trace_id,
                    latency_ms=(time.time() - start_time) * 1000,
                )

            # Check authorization
            ctx = PolicyContext(
                role=request.role,
                approval_token=request.approval_token,
                org=request.org,
                user_id=request.user_id,
            )

            if not self.policy.authorize(request.tool, ctx):
                logger.warning(
                    f"Unauthorized access: tool={request.tool}, role={request.role}"
                )
                return MCPResponse(
                    ok=False,
                    error="unauthorized",
                    request_id=request.request_id,
                    trace_id=trace_id,
                    latency_ms=(time.time() - start_time) * 1000,
                )

            # Check rate limit
            if not self.policy.check_rate_limit(ctx):
                logger.warning(f"Rate limit exceeded for {ctx.org}:{ctx.role}")
                return MCPResponse(
                    ok=False,
                    error="rate_limit_exceeded",
                    request_id=request.request_id,
                    trace_id=trace_id,
                    latency_ms=(time.time() - start_time) * 1000,
                )

            self.tracer.end_span(trace_id)

            # Execute tool
            self.tracer.start_span(trace_id, f"execute_{request.tool}")
            result = self._execute_tool(request.tool, request.args)
            self.tracer.end_span(trace_id)

            # Update metrics
            self.metrics["total_requests"] += 1
            self.metrics["tool_counts"][request.tool] = (
                self.metrics["tool_counts"].get(request.tool, 0) + 1
            )

            latency_ms = (time.time() - start_time) * 1000
            self.metrics["total_latency_ms"] += latency_ms

            logger.info(
                f"Tool executed: {request.tool}, latency={latency_ms:.2f}ms"
            )

            return MCPResponse(
                ok=True,
                result=result,
                request_id=request.request_id,
                trace_id=trace_id,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            logger.error(f"Tool execution failed: {exc}", exc_info=True)
            self.metrics["total_errors"] += 1
            return MCPResponse(
                ok=False,
                error=str(exc),
                request_id=request.request_id,
                trace_id=trace_id,
                latency_ms=(time.time() - start_time) * 1000,
            )

    def _execute_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a specific tool.

        Args:
            tool: Tool name
            args: Tool arguments

        Returns:
            Tool result
        """
        if tool == "find_data_lineage":
            symbol = str(args["node_or_symbol"])
            depth = int(args.get("depth", 3))
            result = self.repo.find_data_lineage(symbol, depth)
            return asdict(result)

        if tool == "impact_of_change":
            item = str(args["file_or_symbol"])
            result = self.repo.impact_of_change(item)
            return asdict(result)

        if tool == "validate_relationship":
            source = str(args["source"])
            target = str(args["target"])
            relation = str(args.get("relation", "any"))
            valid = self.repo.validate_relationship(source, target, relation)
            return {
                "source": source,
                "target": target,
                "relation": relation,
                "valid": valid,
            }

        if tool == "get_dead_paths":
            result = self.repo.get_dead_paths()
            return asdict(result)

        if tool == "find_unhandled_exceptions":
            scope = str(args.get("scope", ""))
            return self.repo.find_unhandled_exceptions(scope)

        if tool == "get_intent_history":
            query = str(args["symbol_or_area"])
            result = self.repo.get_intent_history(query)
            return asdict(result)

        if tool == "get_run_energy":
            run_id = str(args["run_id"])
            return self.repo.get_run_energy(run_id)

        raise ValueError(f"Unknown tool: {tool}")

    def get_metrics(self) -> dict[str, Any]:
        """Get server metrics.

        Returns:
            Dictionary with metrics
        """
        avg_latency = (
            self.metrics["total_latency_ms"] / self.metrics["total_requests"]
            if self.metrics["total_requests"] > 0
            else 0.0
        )
        return {
            "total_requests": self.metrics["total_requests"],
            "total_errors": self.metrics["total_errors"],
            "average_latency_ms": avg_latency,
            "tool_counts": self.metrics["tool_counts"],
        }

    def serve_stdio(self) -> None:
        """Serve MCP protocol over stdio.

        Protocol: line-delimited JSON
        Input:  {"tool":"find_data_lineage","args":{...},"role":"reader"}
        Output: {"ok":true,"result":{...},"request_id":"...","latency_ms":...}
        """
        logger.info("MCP server started on stdio")
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                if line == "quit":
                    logger.info("MCP server shutting down")
                    break

                try:
                    payload = json.loads(line)
                    req = MCPRequest(
                        tool=payload.get("tool", ""),
                        args=payload.get("args", {}),
                        role=payload.get("role", "reader"),
                        approval_token=payload.get("approval_token"),
                        org=payload.get("org", "default"),
                        user_id=payload.get("user_id"),
                    )
                    response = self.handle(req)
                    response_dict = asdict(response)
                    sys.stdout.write(json.dumps(response_dict) + "\n")
                    sys.stdout.flush()
                except json.JSONDecodeError as exc:
                    logger.error(f"JSON parse error: {exc}")
                    error_response = {
                        "ok": False,
                        "error": f"JSON parse error: {exc}",
                    }
                    sys.stdout.write(json.dumps(error_response) + "\n")
                    sys.stdout.flush()
                except Exception as exc:
                    logger.error(f"Request handling error: {exc}", exc_info=True)
                    error_response = {
                        "ok": False,
                        "error": str(exc),
                    }
                    sys.stdout.write(json.dumps(error_response) + "\n")
                    sys.stdout.flush()
        finally:
            self.close()
