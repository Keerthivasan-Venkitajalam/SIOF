"""Performance benchmarks for symbol extraction."""

import time
from pathlib import Path

import pytest

from siof.indexer import PythonIndexer, SymbolExtractor


class TestSymbolExtractionBenchmarks:
    """Benchmarks for symbol extraction performance."""

    def test_symbol_extraction_simple_module(self, tmp_path: Path):
        """Benchmark symbol extraction on simple module."""
        repo = tmp_path / "repo"
        repo.mkdir()
        
        code = """
class DataProcessor:
    '''Process data efficiently.'''
    
    def __init__(self, name: str):
        self.name = name
    
    @property
    def status(self) -> str:
        return "ready"
    
    async def process(self, items: list) -> bool:
        '''Process items asynchronously.'''
        for item in items:
            yield item

def helper_function(x: int) -> int:
    '''Helper function.'''
    return x * 2

CONFIG = {"debug": True}
"""
        (repo / "module.py").write_text(code)
        
        db = tmp_path / "siof.db"
        idx = PythonIndexer(repo=repo, db_path=db)
        idx.init()
        
        start = time.time()
        result = idx.build()
        elapsed = time.time() - start
        
        idx.close()
        
        # Should complete in < 1 second
        assert elapsed < 1.0
        assert result["files"] == 1
        assert result["nodes"] >= 5

    def test_symbol_extraction_large_module(self, tmp_path: Path):
        """Benchmark symbol extraction on larger module."""
        repo = tmp_path / "repo"
        repo.mkdir()
        
        # Generate a large module with many classes and functions
        code_parts = []
        for i in range(50):
            code_parts.append(f"""
class Class{i}:
    '''Class {i}.'''
    
    def method1(self, x: int) -> int:
        return x * 2
    
    def method2(self, y: str) -> str:
        return y.upper()
    
    @property
    def prop(self) -> str:
        return "value"

def function{i}(a: int, b: str) -> bool:
    '''Function {i}.'''
    return True
""")
        
        code = "\n".join(code_parts)
        (repo / "large_module.py").write_text(code)
        
        db = tmp_path / "siof.db"
        idx = PythonIndexer(repo=repo, db_path=db)
        idx.init()
        
        start = time.time()
        result = idx.build()
        elapsed = time.time() - start
        
        idx.close()
        
        # Should complete in < 5 seconds
        assert elapsed < 5.0
        assert result["files"] == 1
        # 50 classes + 50 functions + methods + properties
        assert result["nodes"] >= 200

    def test_symbol_extraction_multiple_files(self, tmp_path: Path):
        """Benchmark symbol extraction on multiple files."""
        repo = tmp_path / "repo"
        repo.mkdir()
        
        # Create 100 small modules
        for i in range(100):
            code = f"""
class Module{i}Class:
    def method(self):
        pass

def module{i}_function():
    pass
"""
            (repo / f"module{i}.py").write_text(code)
        
        db = tmp_path / "siof.db"
        idx = PythonIndexer(repo=repo, db_path=db)
        idx.init()
        
        start = time.time()
        result = idx.build()
        elapsed = time.time() - start
        
        idx.close()
        
        # Should complete in < 10 seconds
        assert elapsed < 10.0
        assert result["files"] == 100
        # 100 classes + 100 functions + methods
        assert result["nodes"] >= 300

    def test_symbol_extraction_nested_classes(self, tmp_path: Path):
        """Benchmark symbol extraction with nested classes."""
        repo = tmp_path / "repo"
        repo.mkdir()
        
        code = """
class OuterClass:
    class InnerClass1:
        def method(self):
            pass
    
    class InnerClass2:
        def method(self):
            pass
    
    def outer_method(self):
        pass
"""
        (repo / "nested.py").write_text(code)
        
        db = tmp_path / "siof.db"
        idx = PythonIndexer(repo=repo, db_path=db)
        idx.init()
        
        start = time.time()
        result = idx.build()
        elapsed = time.time() - start
        
        idx.close()
        
        assert elapsed < 1.0
        assert result["files"] == 1
        # OuterClass, InnerClass1, InnerClass2, methods
        assert result["nodes"] >= 4

    def test_symbol_extraction_with_decorators(self, tmp_path: Path):
        """Benchmark symbol extraction with many decorators."""
        repo = tmp_path / "repo"
        repo.mkdir()
        
        code_parts = []
        for i in range(50):
            code_parts.append(f"""
@decorator1
@decorator2
@decorator3
def decorated_function{i}():
    pass

class DecoratedClass{i}:
    @property
    def prop(self):
        return 42
    
    @staticmethod
    def static():
        pass
    
    @classmethod
    def cls_method(cls):
        pass
""")
        
        code = "\n".join(code_parts)
        (repo / "decorated.py").write_text(code)
        
        db = tmp_path / "siof.db"
        idx = PythonIndexer(repo=repo, db_path=db)
        idx.init()
        
        start = time.time()
        result = idx.build()
        elapsed = time.time() - start
        
        idx.close()
        
        assert elapsed < 5.0
        assert result["files"] == 1
        # Should have decorator edges
        assert result["edges"] >= 50

    def test_symbol_extraction_with_type_hints(self, tmp_path: Path):
        """Benchmark symbol extraction with complex type hints."""
        repo = tmp_path / "repo"
        repo.mkdir()
        
        code = """
from typing import List, Dict, Optional, Union, Callable

def complex_function(
    items: List[Dict[str, int]],
    callback: Callable[[str], bool],
    optional: Optional[str] = None,
    union_type: Union[int, str] = 0,
) -> Dict[str, List[int]]:
    return {}

class ComplexClass:
    items: List[str]
    mapping: Dict[str, int]
    optional: Optional[str]
    
    def method(self, x: List[int]) -> Dict[str, bool]:
        return {}
"""
        (repo / "typed.py").write_text(code)
        
        db = tmp_path / "siof.db"
        idx = PythonIndexer(repo=repo, db_path=db)
        idx.init()
        
        start = time.time()
        result = idx.build()
        elapsed = time.time() - start
        
        idx.close()
        
        assert elapsed < 1.0
        assert result["files"] == 1
        assert result["nodes"] >= 5

    def test_symbol_extraction_scaling(self, tmp_path: Path):
        """Test symbol extraction scaling with increasing file count."""
        repo = tmp_path / "repo"
        repo.mkdir()
        
        # Create files with increasing complexity
        for file_count in [10, 50, 100]:
            for i in range(file_count):
                code = f"""
class Class{i}:
    def method(self):
        pass

def function{i}():
    pass
"""
                (repo / f"file{i}.py").write_text(code)
            
            db = tmp_path / f"siof_{file_count}.db"
            idx = PythonIndexer(repo=repo, db_path=db)
            idx.init()
            
            start = time.time()
            result = idx.build()
            elapsed = time.time() - start
            
            idx.close()
            
            # Verify linear scaling
            assert result["files"] == file_count
            # Should scale roughly linearly
            assert elapsed < file_count * 0.1  # 100ms per file max
            
            # Clean up for next iteration
            for f in repo.glob("*.py"):
                f.unlink()
