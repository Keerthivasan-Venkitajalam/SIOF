

from siof.indexer import (
    DTGBuilder,
    SymbolInfo,
)


class TestDTGBuilder:
    """Tests for DTGBuilder class."""

    def test_builder_initialization(self):
        """Test DTGBuilder initialization."""
        builder = DTGBuilder("myapp.core", "core.py")
        assert builder.module == "myapp.core"
        assert builder.file_path == "core.py"
        assert len(builder.nodes) == 0
        assert len(builder.edges) == 0

    def test_add_symbol_node(self):
        """Test adding a symbol node."""
        builder = DTGBuilder("myapp", "module.py")
        symbol = SymbolInfo(
            name="MyClass",
            kind="class",
            module="myapp",
            location="module.py:1",
            signature="class MyClass",
            docstring="A test class",
            decorators=[],
            type_hints={},
            scope="module",
            is_async=False,
            is_generator=False,
            is_property=False,
            is_abstract=False,
            bases=[],
            parameters=[],
        )

        qualified_name = builder.add_symbol_node("myapp.MyClass", symbol)

        assert qualified_name == "myapp.MyClass"
        assert len(builder.nodes) == 1
        assert builder.nodes[0].symbol == "myapp.MyClass"
        assert builder.nodes[0].kind == "class"

    def test_add_symbol_node_prevents_duplicates(self):
        """Test that duplicate nodes are not added."""
        builder = DTGBuilder("myapp", "module.py")
        symbol = SymbolInfo(
            name="func",
            kind="function",
            module="myapp",
            location="module.py:1",
            signature="def func()",
            docstring="",
            decorators=[],
            type_hints={},
            scope="module",
            is_async=False,
            is_generator=False,
            is_property=False,
            is_abstract=False,
            bases=[],
            parameters=[],
        )

        builder.add_symbol_node("myapp.func", symbol)
        builder.add_symbol_node("myapp.func", symbol)  # Add same symbol again

        assert len(builder.nodes) == 1  # Should still be 1

    def test_add_parameter_edges(self):
        """Test adding parameter edges for a function."""
        builder = DTGBuilder("myapp", "module.py")
        symbol = SymbolInfo(
            name="process",
            kind="function",
            module="myapp",
            location="module.py:5",
            signature="def process(x, y)",
            docstring="",
            decorators=[],
            type_hints={},
            scope="module",
            is_async=False,
            is_generator=False,
            is_property=False,
            is_abstract=False,
            bases=[],
            parameters=["x", "y"],
        )

        builder.add_symbol_node("myapp.process", symbol)
        builder.add_parameter_edges("myapp.process", symbol)

        # Should have 3 nodes: function + 2 parameters
        assert len(builder.nodes) == 3
        # Should have 2 edges: param->func for each param
        assert len(builder.edges) == 2

        # Check edge properties
        for edge in builder.edges:
            assert edge.transform_kind == "parameter"
            assert edge.confidence == 1.0

    def test_add_inheritance_edges(self):
        """Test adding inheritance edges for a class."""
        builder = DTGBuilder("myapp", "module.py")
        symbol = SymbolInfo(
            name="Child",
            kind="class",
            module="myapp",
            location="module.py:10",
            signature="class Child(Parent)",
            docstring="",
            decorators=[],
            type_hints={},
            scope="module",
            is_async=False,
            is_generator=False,
            is_property=False,
            is_abstract=False,
            bases=["Parent", "Mixin"],
            parameters=[],
        )

        builder.add_symbol_node("myapp.Child", symbol)
        builder.add_inheritance_edges("myapp.Child", symbol)

        assert len(builder.nodes) == 1
        assert len(builder.edges) == 2  # One edge per base class

        for edge in builder.edges:
            assert edge.transform_kind == "inheritance"
            assert edge.confidence == 1.0
            assert edge.target == "myapp.Child"

    def test_add_decorator_edges(self):
        """Test adding decorator edges."""
        builder = DTGBuilder("myapp", "module.py")
        symbol = SymbolInfo(
            name="decorated_func",
            kind="function",
            module="myapp",
            location="module.py:15",
            signature="@property\ndef decorated_func()",
            docstring="",
            decorators=["property", "cached"],
            type_hints={},
            scope="module",
            is_async=False,
            is_generator=False,
            is_property=True,
            is_abstract=False,
            bases=[],
            parameters=[],
        )

        builder.add_symbol_node("myapp.decorated_func", symbol)
        builder.add_decorator_edges("myapp.decorated_func", symbol)

        assert len(builder.nodes) == 1
        assert len(builder.edges) == 2  # One edge per decorator

        for edge in builder.edges:
            assert edge.transform_kind == "decorator"
            assert edge.confidence == 0.95

    def test_add_call_edge(self):
        """Test adding a call edge."""
        builder = DTGBuilder("myapp", "module.py")

        builder.add_call_edge(
            "myapp.helper",
            "myapp.process",
            transform_kind="call",
            location="module.py:20",
            confidence=0.9,
        )

        assert len(builder.edges) == 1
        edge = builder.edges[0]
        assert edge.source == "myapp.helper"
        assert edge.target == "myapp.process"
        assert edge.transform_kind == "call"
        assert edge.confidence == 0.9

    def test_add_assignment_transform_edge(self):
        """Test adding an assignment transform edge."""
        builder = DTGBuilder("myapp", "module.py")

        builder.add_assignment_transform_edge(
            "myapp.create_obj",
            "myapp.obj_instance",
            location="module.py:25",
            confidence=0.85,
        )

        assert len(builder.edges) == 1
        edge = builder.edges[0]
        assert edge.transform_kind == "assignment_transform"
        assert edge.confidence == 0.85

    def test_confidence_clamping(self):
        """Test that confidence scores are clamped to [0, 1]."""
        builder = DTGBuilder("myapp", "module.py")

        # Test over-confidence
        builder.add_call_edge("a", "b", confidence=1.5)
        assert builder.edges[0].confidence == 1.0

        # Test negative confidence
        builder.add_call_edge("c", "d", confidence=-0.5)
        assert builder.edges[1].confidence == 0.0

    def test_build_returns_nodes_and_edges(self):
        """Test that build() returns nodes and edges."""
        builder = DTGBuilder("myapp", "module.py")

        symbol = SymbolInfo(
            name="func",
            kind="function",
            module="myapp",
            location="module.py:1",
            signature="def func(x)",
            docstring="",
            decorators=[],
            type_hints={},
            scope="module",
            is_async=False,
            is_generator=False,
            is_property=False,
            is_abstract=False,
            bases=[],
            parameters=["x"],
        )

        builder.add_symbol_node("myapp.func", symbol)
        builder.add_parameter_edges("myapp.func", symbol)

        nodes, edges = builder.build()

        assert len(nodes) == 2  # func + parameter
        assert len(edges) == 1  # parameter edge

    def test_verify_integrity_detects_self_loops(self):
        """Test that verify_integrity detects self-loops."""
        builder = DTGBuilder("myapp", "module.py")

        # Add a self-loop (not allowed except for parameters)
        builder.add_call_edge("myapp.func", "myapp.func", transform_kind="call")

        violations = builder.verify_integrity()

        assert len(violations) > 0
        assert any("Self-loop" in v for v in violations)

    def test_verify_integrity_checks_confidence_bounds(self):
        """Test that verify_integrity checks confidence bounds."""
        builder = DTGBuilder("myapp", "module.py")

        # Manually add an invalid edge (bypassing clamping)
        from siof.models import TransformEdge
        builder.edges.append(
            TransformEdge(
                source="a",
                target="b",
                transform_symbol="a",
                transform_kind="call",
                location="test.py:1",
                confidence=1.5,  # Invalid
            )
        )

        violations = builder.verify_integrity()

        assert len(violations) > 0
        assert any("confidence" in v.lower() for v in violations)

    def test_complex_graph_building(self):
        """Test building a complex graph with multiple relationships."""
        builder = DTGBuilder("myapp.core", "models.py")

        # Add base class
        base_symbol = SymbolInfo(
            name="BaseModel",
            kind="class",
            module="myapp.core",
            location="models.py:1",
            signature="class BaseModel",
            docstring="",
            decorators=[],
            type_hints={},
            scope="module",
            is_async=False,
            is_generator=False,
            is_property=False,
            is_abstract=True,
            bases=[],
            parameters=[],
        )

        # Add derived class with decorators
        derived_symbol = SymbolInfo(
            name="User",
            kind="class",
            module="myapp.core",
            location="models.py:10",
            signature="@dataclass\nclass User(BaseModel)",
            docstring="User model",
            decorators=["dataclass"],
            type_hints={},
            scope="module",
            is_async=False,
            is_generator=False,
            is_property=False,
            is_abstract=False,
            bases=["BaseModel"],
            parameters=[],
        )

        # Add method with parameters
        method_symbol = SymbolInfo(
            name="validate",
            kind="method",
            module="myapp.core",
            location="models.py:15",
            signature="def validate(self, data)",
            docstring="",
            decorators=[],
            type_hints={},
            scope="myapp.core.User",
            is_async=False,
            is_generator=False,
            is_property=False,
            is_abstract=False,
            bases=[],
            parameters=["self", "data"],
        )

        # Build graph
        builder.add_symbol_node("myapp.core.BaseModel", base_symbol)
        builder.add_symbol_node("myapp.core.User", derived_symbol)
        builder.add_inheritance_edges("myapp.core.User", derived_symbol)
        builder.add_decorator_edges("myapp.core.User", derived_symbol)

        builder.add_symbol_node("myapp.core.User.validate", method_symbol)
        builder.add_parameter_edges("myapp.core.User.validate", method_symbol)

        # Add a call edge
        builder.add_call_edge(
            "myapp.core.User.validate",
            "myapp.validators.check_data",
            confidence=0.85,
        )

        nodes, edges = builder.build()

        # Verify structure
        assert len(nodes) >= 5  # base, derived, method, 2 parameters
        assert len(edges) >= 4  # inheritance, decorator, 2 parameters, call

        # Verify no integrity violations
        violations = builder.verify_integrity()
        assert len(violations) == 0
