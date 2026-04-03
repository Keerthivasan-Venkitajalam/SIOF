"""Performance benchmarks for DTGBuilder."""

import time
from pathlib import Path

from siof.indexer import DTGBuilder, SymbolExtractor, SymbolInfo


class TestDTGBuilderBenchmarks:
    """Performance benchmarks for DTGBuilder."""

    def test_build_simple_graph_performance(self):
        """Benchmark building a simple graph."""
        start = time.time()
        for _ in range(100):
            builder = DTGBuilder("myapp", "module.py")
            symbol = SymbolInfo(
                name="func",
                kind="function",
                module="myapp",
                location="module.py:1",
                signature="def func(x, y)",
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
            builder.add_symbol_node("myapp.func", symbol)
            builder.add_parameter_edges("myapp.func", symbol)
            result = builder.build()
            assert len(result[0]) == 3  # func + 2 params
            assert len(result[1]) == 2  # 2 edges

        elapsed = time.time() - start
        # 100 iterations should complete in < 1 second
        assert elapsed < 1.0, f"Simple graph building took {elapsed}s"

    def test_build_complex_graph_performance(self):
        """Benchmark building a complex graph with many relationships."""
        start = time.time()

        builder = DTGBuilder("myapp.core", "models.py")

        # Add 10 classes with inheritance
        for i in range(10):
            symbol = SymbolInfo(
                name=f"Class{i}",
                kind="class",
                module="myapp.core",
                location=f"models.py:{i*10}",
                signature=f"class Class{i}",
                docstring="",
                decorators=["dataclass"] if i % 2 == 0 else [],
                type_hints={},
                scope="module",
                is_async=False,
                is_generator=False,
                is_property=False,
                is_abstract=i % 3 == 0,
                bases=[f"Class{i-1}"] if i > 0 else [],
                parameters=[],
            )
            builder.add_symbol_node(f"myapp.core.Class{i}", symbol)
            builder.add_inheritance_edges(f"myapp.core.Class{i}", symbol)
            builder.add_decorator_edges(f"myapp.core.Class{i}", symbol)

        # Add methods with parameters
        for i in range(10):
            for j in range(5):
                method_symbol = SymbolInfo(
                    name=f"method{j}",
                    kind="method",
                    module="myapp.core",
                    location=f"models.py:{i*10+j}",
                    signature=f"def method{j}(self, x, y)",
                    docstring="",
                    decorators=[],
                    type_hints={},
                    scope=f"myapp.core.Class{i}",
                    is_async=False,
                    is_generator=False,
                    is_property=False,
                    is_abstract=False,
                    bases=[],
                    parameters=["self", "x", "y"],
                )
                builder.add_symbol_node(f"myapp.core.Class{i}.method{j}", method_symbol)
                builder.add_parameter_edges(f"myapp.core.Class{i}.method{j}", method_symbol)

        result = builder.build()
        elapsed = time.time() - start

        # 10 classes + 10*5 methods + 10*5*3 parameters = 210 nodes
        assert len(result[0]) >= 200
        # inheritance + decorators + parameters edges
        assert len(result[1]) >= 100
        # Should complete in < 0.5 seconds
        assert elapsed < 0.5, f"Complex graph building took {elapsed}s"

    def test_verify_integrity_performance(self):
        """Benchmark graph integrity verification."""
        builder = DTGBuilder("myapp", "module.py")

        # Build a graph with many edges
        for i in range(100):
            builder.add_call_edge(
                f"source_{i}",
                f"target_{i}",
                confidence=0.8 + (i % 20) * 0.01,
            )

        start = time.time()
        for _ in range(100):
            result = builder.verify_integrity()
            assert isinstance(result, list)
        elapsed = time.time() - start

        # 100 verifications should complete in < 1 second
        assert elapsed < 1.0, f"Integrity verification took {elapsed}s"

    def test_add_many_edges_performance(self):
        """Benchmark adding many edges."""
        builder = DTGBuilder("myapp", "module.py")

        start = time.time()
        for i in range(1000):
            builder.add_call_edge(
                f"source_{i}",
                f"target_{i}",
                confidence=0.8,
            )
        elapsed = time.time() - start

        assert len(builder.edges) == 1000
        # 1000 edges should be added in < 0.5 seconds
        assert elapsed < 0.5, f"Adding 1000 edges took {elapsed}s"

    def test_build_with_real_symbols(self, tmp_path: Path):
        """Benchmark building DTG from real extracted symbols."""
        # Create a test file with many symbols
        repo = tmp_path / "repo"
        repo.mkdir()

        code = """
class BaseModel:
    pass

class User(BaseModel):
    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email

    def validate(self, data):
        return True

    @property
    def display_name(self):
        return self.name

class Admin(User):
    def approve(self, item):
        return True

def create_user(name, email):
    return User(name, email)

def process_users(users):
    for user in users:
        user.validate({})
"""
        (repo / "models.py").write_text(code)

        start = time.time()
        for _ in range(10):
            import ast

            tree = ast.parse(code)
            extractor = SymbolExtractor("models", "models.py")
            symbols = extractor.extract(tree)

            builder = DTGBuilder("models", "models.py")
            for qualified_name, symbol in symbols.items():
                builder.add_symbol_node(qualified_name, symbol)
                builder.add_parameter_edges(qualified_name, symbol)
                builder.add_inheritance_edges(qualified_name, symbol)
                builder.add_decorator_edges(qualified_name, symbol)

            result = builder.build()
            assert len(result[0]) > 0
            assert len(result[1]) > 0

        elapsed = time.time() - start
        # 10 iterations should complete in < 1 second
        assert elapsed < 1.0, f"Building from real symbols took {elapsed}s"

    def test_duplicate_prevention_performance(self):
        """Benchmark duplicate node prevention."""
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

        start = time.time()
        for _ in range(1000):
            builder.add_symbol_node("myapp.func", symbol)
        elapsed = time.time() - start

        # Should still have only 1 node due to duplicate prevention
        assert len(builder.nodes) == 1
        # 1000 duplicate attempts should complete in < 0.5 seconds
        assert elapsed < 0.5, f"Duplicate prevention took {elapsed}s"

    def test_confidence_clamping_performance(self):
        """Benchmark confidence score clamping."""
        builder = DTGBuilder("myapp", "module.py")

        start = time.time()
        for i in range(1000):
            confidence = -0.5 + (i % 200) * 0.01  # Range from -0.5 to 1.5
            builder.add_call_edge(
                f"source_{i}",
                f"target_{i}",
                confidence=confidence,
            )
        elapsed = time.time() - start

        # All confidences should be clamped to [0, 1]
        for edge in builder.edges:
            assert 0.0 <= edge.confidence <= 1.0

        # 1000 edges with clamping should complete in < 0.5 seconds
        assert elapsed < 0.5, f"Confidence clamping took {elapsed}s"
