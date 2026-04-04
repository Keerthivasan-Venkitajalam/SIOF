"""Tests for LockFreeSymbolTable class."""

from __future__ import annotations

import threading

from siof.free_threaded_indexer import LockFreeSymbolTable
from siof.indexer import SymbolInfo


def create_symbol(name: str, kind: str, module: str = "test", location: str = "test.py:10", **kwargs):
    """Helper to create SymbolInfo with minimal required fields."""
    return SymbolInfo(
        name=name,
        kind=kind,
        module=module,
        location=location,
        **kwargs
    )


class TestLockFreeSymbolTable:
    """Tests for LockFreeSymbolTable class."""
    
    def test_init_creates_empty_table(self):
        """Test initialization creates an empty symbol table."""
        table = LockFreeSymbolTable()
        
        symbols = table.get_all_symbols()
        assert len(symbols) == 0
        assert isinstance(symbols, dict)
    
    def test_add_symbol_single_symbol(self):
        """Test adding a single symbol to the table."""
        table = LockFreeSymbolTable()
        
        symbol = create_symbol(
            name="test_func",
            kind="function",
            signature="def test_func():",
            docstring="Test function"
        )
        
        table.add_symbol("test.test_func", symbol)
        
        symbols = table.get_all_symbols()
        assert len(symbols) == 1
        assert "test.test_func" in symbols
        assert symbols["test.test_func"] == symbol
    
    def test_add_symbol_multiple_symbols(self):
        """Test adding multiple symbols to the table."""
        table = LockFreeSymbolTable()
        
        symbol1 = create_symbol(name="func1", kind="function", location="test.py:10")
        symbol2 = create_symbol(name="func2", kind="function", location="test.py:20")
        symbol3 = create_symbol(name="MyClass", kind="class", location="test.py:30")
        
        table.add_symbol("test.func1", symbol1)
        table.add_symbol("test.func2", symbol2)
        table.add_symbol("test.MyClass", symbol3)
        
        symbols = table.get_all_symbols()
        assert len(symbols) == 3
        assert "test.func1" in symbols
        assert "test.func2" in symbols
        assert "test.MyClass" in symbols
    
    def test_add_symbol_duplicate_keeps_first(self):
        """Test that adding a duplicate symbol keeps the first occurrence."""
        table = LockFreeSymbolTable()
        
        symbol1 = create_symbol(
            name="func",
            kind="function",
            location="test.py:10",
            docstring="First version"
        )
        
        symbol2 = create_symbol(
            name="func",
            kind="function",
            location="test.py:20",
            docstring="Second version"
        )
        
        table.add_symbol("test.func", symbol1)
        table.add_symbol("test.func", symbol2)  # Duplicate - should be ignored
        
        symbols = table.get_all_symbols()
        assert len(symbols) == 1
        assert symbols["test.func"].docstring == "First version"
    
    def test_get_all_symbols_returns_copy(self):
        """Test that get_all_symbols returns a copy, not the internal dict."""
        table = LockFreeSymbolTable()
        
        symbol = create_symbol(name="func", kind="function")
        
        table.add_symbol("test.func", symbol)
        
        # Get symbols
        symbols1 = table.get_all_symbols()
        
        # Modify the returned dict
        symbols1["test.other"] = symbol
        
        # Get symbols again - should not include the modification
        symbols2 = table.get_all_symbols()
        assert len(symbols2) == 1
        assert "test.other" not in symbols2
    
    def test_add_symbol_concurrent_access(self):
        """Test concurrent symbol addition from multiple threads."""
        table = LockFreeSymbolTable()
        num_threads = 10
        symbols_per_thread = 10
        
        def add_symbols(thread_id):
            """Add symbols from a single thread."""
            for i in range(symbols_per_thread):
                symbol = create_symbol(
                    name=f"func_{thread_id}_{i}",
                    kind="function",
                    module=f"test{thread_id}",
                    location=f"test{thread_id}.py:{i}"
                )
                table.add_symbol(f"test{thread_id}.func_{thread_id}_{i}", symbol)
        
        # Create and start threads
        threads = []
        for thread_id in range(num_threads):
            thread = threading.Thread(target=add_symbols, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all symbols were added
        symbols = table.get_all_symbols()
        expected_count = num_threads * symbols_per_thread
        assert len(symbols) == expected_count, (
            f"Expected {expected_count} symbols, got {len(symbols)}"
        )
        
        # Verify all expected symbols are present
        for thread_id in range(num_threads):
            for i in range(symbols_per_thread):
                qualified_name = f"test{thread_id}.func_{thread_id}_{i}"
                assert qualified_name in symbols, (
                    f"Missing symbol: {qualified_name}"
                )
    
    def test_add_symbol_concurrent_duplicates(self):
        """Test concurrent addition of duplicate symbols keeps first occurrence."""
        table = LockFreeSymbolTable()
        num_threads = 10
        
        def add_duplicate_symbol(thread_id):
            """Add the same symbol from multiple threads."""
            symbol = create_symbol(
                name="shared_func",
                kind="function",
                module="test",
                location=f"test{thread_id}.py:10",
                docstring=f"Version from thread {thread_id}"
            )
            table.add_symbol("test.shared_func", symbol)
        
        # Create and start threads
        threads = []
        for thread_id in range(num_threads):
            thread = threading.Thread(target=add_duplicate_symbol, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify only one symbol was kept
        symbols = table.get_all_symbols()
        assert len(symbols) == 1
        assert "test.shared_func" in symbols
        
        # Verify the docstring is from one of the threads (first occurrence wins)
        docstring = symbols["test.shared_func"].docstring
        assert docstring is not None
        assert "Version from thread" in docstring
    
    def test_add_symbol_with_different_kinds(self):
        """Test adding symbols of different kinds (function, class, method, variable)."""
        table = LockFreeSymbolTable()
        
        function_symbol = create_symbol(name="my_function", kind="function")
        class_symbol = create_symbol(name="MyClass", kind="class", location="test.py:20")
        method_symbol = create_symbol(
            name="my_method",
            kind="method",
            location="test.py:30",
            parameters=["self"]
        )
        variable_symbol = create_symbol(
            name="my_var",
            kind="variable",
            location="test.py:40",
            type_hints={"inferred": "int"}
        )
        
        table.add_symbol("test.my_function", function_symbol)
        table.add_symbol("test.MyClass", class_symbol)
        table.add_symbol("test.MyClass.my_method", method_symbol)
        table.add_symbol("test.my_var", variable_symbol)
        
        symbols = table.get_all_symbols()
        assert len(symbols) == 4
        assert symbols["test.my_function"].kind == "function"
        assert symbols["test.MyClass"].kind == "class"
        assert symbols["test.MyClass.my_method"].kind == "method"
        assert symbols["test.my_var"].kind == "variable"
    
    def test_get_all_symbols_empty_table(self):
        """Test get_all_symbols on an empty table."""
        table = LockFreeSymbolTable()
        
        symbols = table.get_all_symbols()
        assert len(symbols) == 0
        assert isinstance(symbols, dict)
    
    def test_add_symbol_with_complex_qualified_names(self):
        """Test adding symbols with complex qualified names."""
        table = LockFreeSymbolTable()
        
        # Module-level function
        symbol1 = create_symbol(
            name="func",
            kind="function",
            module="mypackage.module",
            location="module.py:10"
        )
        
        # Nested class method
        symbol2 = create_symbol(
            name="method",
            kind="method",
            module="mypackage.module",
            location="module.py:20",
            parameters=["self"]
        )
        
        table.add_symbol("mypackage.module.func", symbol1)
        table.add_symbol("mypackage.module.OuterClass.InnerClass.method", symbol2)
        
        symbols = table.get_all_symbols()
        assert len(symbols) == 2
        assert "mypackage.module.func" in symbols
        assert "mypackage.module.OuterClass.InnerClass.method" in symbols
