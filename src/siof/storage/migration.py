"""Migration tool for exporting and importing graph data between backends."""

import json
import logging
from pathlib import Path
from typing import Any

from siof.storage.backend import Edge, Node, StorageBackend
from siof.storage.exceptions import StorageException

logger = logging.getLogger(__name__)


class MigrationTool:
    """Tool for migrating data between storage backends.

    This tool enables exporting data from one backend (e.g., SQLite) and
    importing it into another (e.g., Neo4j, FalkorDB). It includes validation
    to ensure data consistency and provides rollback capability for failed imports.

    Attributes:
        source_backend: Source StorageBackend instance
        target_backend: Target StorageBackend instance
    """

    def __init__(
        self,
        source_backend: StorageBackend,
        target_backend: StorageBackend,
    ) -> None:
        """Initialize MigrationTool.

        Args:
            source_backend: Source backend to export from
            target_backend: Target backend to import to

        Raises:
            ValueError: If backends are None
        """
        if not source_backend:
            raise ValueError("source_backend cannot be None")
        if not target_backend:
            raise ValueError("target_backend cannot be None")

        self.source_backend = source_backend
        self.target_backend = target_backend
        self._exported_nodes: list[dict[str, Any]] = []
        self._exported_edges: list[dict[str, Any]] = []
        self._imported_nodes: list[str] = []
        self._imported_edges: list[tuple[str, str]] = []

    def export(self, output_file: str) -> dict[str, Any]:
        """Export all nodes and edges from source backend.

        Args:
            output_file: Path to write exported data as JSON

        Returns:
            Dictionary containing:
            - nodes_exported: Number of nodes exported
            - edges_exported: Number of edges exported
            - output_file: Path to output file
            - metadata: Export metadata (timestamp, source backend, etc.)

        Raises:
            StorageException: If export fails
        """
        logger.info(f"Starting export from {self.source_backend.get_backend_name()}")

        try:
            # Export all nodes
            nodes_data = self._export_nodes()
            logger.info(f"Exported {len(nodes_data)} nodes")

            # Export all edges
            edges_data = self._export_edges()
            logger.info(f"Exported {len(edges_data)} edges")

            # Validate exported data
            self._validate_export(nodes_data, edges_data)
            logger.info("Export validation passed")

            # Write to file
            export_data = {
                "metadata": {
                    "source_backend": self.source_backend.get_backend_name(),
                    "source_version": self.source_backend.get_backend_version(),
                    "target_backend": self.target_backend.get_backend_name(),
                    "target_version": self.target_backend.get_backend_version(),
                },
                "nodes": nodes_data,
                "edges": edges_data,
            }

            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w") as f:
                json.dump(export_data, f, indent=2)

            logger.info(f"Export written to {output_file}")

            # Store for potential validation
            self._exported_nodes = nodes_data
            self._exported_edges = edges_data

            return {
                "nodes_exported": len(nodes_data),
                "edges_exported": len(edges_data),
                "output_file": str(output_path.absolute()),
                "metadata": export_data["metadata"],
            }

        except Exception as e:
            logger.error(f"Export failed: {e}")
            raise StorageException(f"Export failed: {e}") from e

    def import_data(self, input_file: str) -> dict[str, Any]:
        """Import nodes and edges from JSON file to target backend.

        Args:
            input_file: Path to JSON file with exported data

        Returns:
            Dictionary containing:
            - nodes_imported: Number of nodes imported
            - edges_imported: Number of edges imported
            - validation_status: Status of validation
            - errors: List of any errors encountered

        Raises:
            StorageException: If import fails
        """
        logger.info(f"Starting import to {self.target_backend.get_backend_name()}")

        try:
            # Load data from file
            with open(input_file) as f:
                import_data = json.load(f)

            nodes_data = import_data.get("nodes", [])
            edges_data = import_data.get("edges", [])

            logger.info(f"Loaded {len(nodes_data)} nodes and {len(edges_data)} edges from file")

            # Import nodes
            nodes_imported = self._import_nodes(nodes_data)
            logger.info(f"Imported {nodes_imported} nodes")

            # Import edges
            edges_imported = self._import_edges(edges_data)
            logger.info(f"Imported {edges_imported} edges")

            # Validate import
            validation_status = self._validate_import(nodes_data, edges_data)
            logger.info(f"Import validation: {validation_status}")

            return {
                "nodes_imported": nodes_imported,
                "edges_imported": edges_imported,
                "validation_status": validation_status,
                "errors": [],
            }

        except Exception as e:
            logger.error(f"Import failed: {e}")
            # Attempt rollback
            try:
                self.rollback()
            except Exception as rollback_error:
                logger.error(f"Rollback failed: {rollback_error}")
            raise StorageException(f"Import failed: {e}") from e

    def validate_import(self) -> dict[str, Any]:
        """Validate that imported data matches exported data.

        Returns:
            Dictionary containing validation results:
            - valid: Whether validation passed
            - nodes_match: Number of matching nodes
            - edges_match: Number of matching edges
            - missing_nodes: List of missing node IDs
            - missing_edges: List of missing edges

        Raises:
            StorageException: If validation fails
        """
        logger.info("Validating import")

        try:
            if not self._exported_nodes or not self._exported_edges:
                raise StorageException("No exported data to validate against")

            # Check nodes
            missing_nodes = []
            for node_data in self._exported_nodes:
                node_id = node_data.get("id")
                if node_id not in self._imported_nodes:
                    missing_nodes.append(node_id)

            # Check edges
            missing_edges = []
            for edge_data in self._exported_edges:
                source_id = edge_data.get("source_id")
                target_id = edge_data.get("target_id")
                if (source_id, target_id) not in self._imported_edges:
                    missing_edges.append((source_id, target_id))

            valid = len(missing_nodes) == 0 and len(missing_edges) == 0

            result = {
                "valid": valid,
                "nodes_match": len(self._exported_nodes) - len(missing_nodes),
                "edges_match": len(self._exported_edges) - len(missing_edges),
                "missing_nodes": missing_nodes,
                "missing_edges": missing_edges,
            }

            logger.info(f"Validation result: {result}")
            return result

        except Exception as e:
            logger.error(f"Validation failed: {e}")
            raise StorageException(f"Validation failed: {e}") from e

    def rollback(self) -> None:
        """Rollback a failed import by deleting imported nodes and edges.

        Raises:
            StorageException: If rollback fails
        """
        logger.info("Rolling back import")

        try:
            # Delete edges first (to maintain referential integrity)
            for source_id, target_id in reversed(self._imported_edges):
                try:
                    self.target_backend.delete_edge(source_id, target_id)
                except Exception as e:
                    logger.warning(f"Failed to delete edge {source_id}->{target_id}: {e}")

            # Delete nodes
            for node_id in reversed(self._imported_nodes):
                try:
                    self.target_backend.delete_node(node_id)
                except Exception as e:
                    logger.warning(f"Failed to delete node {node_id}: {e}")

            # Clear tracking lists
            self._imported_nodes.clear()
            self._imported_edges.clear()

            logger.info("Rollback completed")

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            raise StorageException(f"Rollback failed: {e}") from e

    def _export_nodes(self) -> list[dict[str, Any]]:
        """Export all nodes from source backend.

        Returns:
            List of node dictionaries
        """
        logger.debug("Exporting nodes")

        try:
            # Query all nodes
            query = "MATCH (n:Node) RETURN n"
            results = self.source_backend.query(query, {})

            nodes = []
            for result in results:
                node_dict = self._node_to_dict(result)
                if node_dict:
                    nodes.append(node_dict)

            logger.debug(f"Exported {len(nodes)} nodes")
            return nodes

        except Exception as e:
            logger.error(f"Failed to export nodes: {e}")
            raise

    def _export_edges(self) -> list[dict[str, Any]]:
        """Export all edges from source backend.

        Returns:
            List of edge dictionaries
        """
        logger.debug("Exporting edges")

        try:
            # Query all edges
            query = "MATCH (s:Node)-[e:EDGE]->(t:Node) RETURN s, e, t"
            results = self.source_backend.query(query, {})

            edges = []
            for result in results:
                edge_dict = self._edge_to_dict(result)
                if edge_dict:
                    edges.append(edge_dict)

            logger.debug(f"Exported {len(edges)} edges")
            return edges

        except Exception as e:
            logger.error(f"Failed to export edges: {e}")
            raise

    def _node_to_dict(self, result: dict[str, Any]) -> dict[str, Any] | None:
        """Convert query result to node dictionary.

        Args:
            result: Query result from backend

        Returns:
            Node dictionary or None if conversion fails
        """
        try:
            # Handle different result formats
            if "n" in result:
                n = result["n"]
            else:
                # Try to find node-like object
                for value in result.values():
                    if isinstance(value, dict) and "id" in value:
                        n = value
                        break
                else:
                    return None

            # Extract node properties
            if isinstance(n, dict):
                return {
                    "id": n.get("id"),
                    "type": n.get("type"),
                    "name": n.get("name"),
                    "metadata": n.get("metadata", {}),
                }
            else:
                # Handle backend-specific node objects
                return {
                    "id": getattr(n, "id", None),
                    "type": getattr(n, "type", None),
                    "name": getattr(n, "name", None),
                    "metadata": getattr(n, "metadata", {}),
                }

        except Exception as e:
            logger.debug(f"Failed to convert result to node dict: {e}")
            return None

    def _edge_to_dict(self, result: dict[str, Any]) -> dict[str, Any] | None:
        """Convert query result to edge dictionary.

        Args:
            result: Query result from backend

        Returns:
            Edge dictionary or None if conversion fails
        """
        try:
            # Extract source, edge, and target
            source = result.get("s")
            edge = result.get("e")
            target = result.get("t")

            if not all([source, edge, target]):
                return None

            # Extract source ID
            if isinstance(source, dict):
                source_id = source.get("id")
            else:
                source_id = getattr(source, "id", None)

            # Extract target ID
            if isinstance(target, dict):
                target_id = target.get("id")
            else:
                target_id = getattr(target, "id", None)

            # Extract edge properties
            if isinstance(edge, dict):
                return {
                    "source_id": source_id,
                    "target_id": target_id,
                    "edge_type": edge.get("edge_type"),
                    "metadata": edge.get("metadata", {}),
                }
            else:
                return {
                    "source_id": source_id,
                    "target_id": target_id,
                    "edge_type": getattr(edge, "edge_type", None),
                    "metadata": getattr(edge, "metadata", {}),
                }

        except Exception as e:
            logger.debug(f"Failed to convert result to edge dict: {e}")
            return None

    def _import_nodes(self, nodes_data: list[dict[str, Any]]) -> int:
        """Import nodes to target backend.

        Args:
            nodes_data: List of node dictionaries

        Returns:
            Number of nodes imported
        """
        logger.debug(f"Importing {len(nodes_data)} nodes")

        imported = 0
        for node_data in nodes_data:
            try:
                node = self._dict_to_node(node_data)
                self.target_backend.create_node(node)
                self._imported_nodes.append(node.id)
                imported += 1
            except Exception as e:
                logger.warning(f"Failed to import node {node_data.get('id')}: {e}")

        logger.debug(f"Imported {imported} nodes")
        return imported

    def _import_edges(self, edges_data: list[dict[str, Any]]) -> int:
        """Import edges to target backend.

        Args:
            edges_data: List of edge dictionaries

        Returns:
            Number of edges imported
        """
        logger.debug(f"Importing {len(edges_data)} edges")

        imported = 0
        for edge_data in edges_data:
            try:
                edge = self._dict_to_edge(edge_data)
                self.target_backend.create_edge(edge)
                self._imported_edges.append((edge.source_id, edge.target_id))
                imported += 1
            except Exception as e:
                logger.warning(
                    f"Failed to import edge {edge_data.get('source_id')}->"
                    f"{edge_data.get('target_id')}: {e}"
                )

        logger.debug(f"Imported {imported} edges")
        return imported

    def _dict_to_node(self, data: dict[str, Any]) -> Node:
        """Convert dictionary to Node object.

        Args:
            data: Node dictionary

        Returns:
            Node object
        """
        return Node(
            id=data.get("id", ""),
            type=data.get("type", ""),
            name=data.get("name", ""),
            metadata=data.get("metadata", {}),
        )

    def _dict_to_edge(self, data: dict[str, Any]) -> Edge:
        """Convert dictionary to Edge object.

        Args:
            data: Edge dictionary

        Returns:
            Edge object
        """
        return Edge(
            source_id=data.get("source_id", ""),
            target_id=data.get("target_id", ""),
            edge_type=data.get("edge_type", ""),
            metadata=data.get("metadata", {}),
        )

    def _validate_export(
        self,
        nodes_data: list[dict[str, Any]],
        edges_data: list[dict[str, Any]],
    ) -> None:
        """Validate exported data for consistency.

        Args:
            nodes_data: List of exported nodes
            edges_data: List of exported edges

        Raises:
            StorageException: If validation fails
        """
        logger.debug("Validating exported data")

        # Check for duplicate node IDs
        node_ids = [n.get("id") for n in nodes_data]
        if len(node_ids) != len(set(node_ids)):
            raise StorageException("Duplicate node IDs in export")

        # Check for edges referencing non-existent nodes
        node_id_set = set(node_ids)
        for edge in edges_data:
            source_id = edge.get("source_id")
            target_id = edge.get("target_id")

            if source_id not in node_id_set:
                raise StorageException(f"Edge references non-existent source node: {source_id}")

            if target_id not in node_id_set:
                raise StorageException(f"Edge references non-existent target node: {target_id}")

        logger.debug("Export validation passed")

    def _validate_import(
        self,
        nodes_data: list[dict[str, Any]],
        edges_data: list[dict[str, Any]],
    ) -> str:
        """Validate imported data matches exported data.

        Args:
            nodes_data: List of exported nodes
            edges_data: List of exported edges

        Returns:
            Validation status string
        """
        logger.debug("Validating imported data")

        # Check node count
        if len(self._imported_nodes) != len(nodes_data):
            return "partial"

        # Check edge count
        if len(self._imported_edges) != len(edges_data):
            return "partial"

        logger.debug("Import validation passed")
        return "success"
