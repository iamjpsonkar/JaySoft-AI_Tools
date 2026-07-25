"""Tests for jsat._parsers. CI-safe: writes real source files."""
from pathlib import Path
import pytest
from jsat._parsers import detect_language, get_parser
from jsat._parsers.go import GoParser
from jsat._parsers.javascript import JavaScriptParser
from jsat._parsers.python import PythonParser

def _nodes(r, label): return [n for n in r.nodes if n["label"] == label]
def _edges(r, t):     return [e for e in r.edges if e["type"] == t]

# Factory
@pytest.mark.ci
def test_get_python():   assert get_parser("python") is not None
@pytest.mark.ci
def test_get_js():       assert get_parser("javascript") is not None
@pytest.mark.ci
def test_get_go():       assert get_parser("go") is not None
@pytest.mark.ci
def test_get_unknown():  assert get_parser("cobol") is None
@pytest.mark.ci
def test_detect_py():    assert detect_language(Path("a.py")) == "python"
@pytest.mark.ci
def test_detect_go():    assert detect_language(Path("a.go")) == "go"
@pytest.mark.ci
def test_detect_js():    assert detect_language(Path("a.js")) == "javascript"
@pytest.mark.ci
def test_detect_ts():    assert detect_language(Path("a.ts")) == "typescript"
@pytest.mark.ci
def test_detect_none():  assert detect_language(Path("a.xyz")) is None

# Python
@pytest.mark.ci
def test_py_file_node(tmp_path):
    f = tmp_path/"s.py"; f.write_text("x=1\n")
    assert _nodes(PythonParser().parse(f, tmp_path), "File")

@pytest.mark.ci
def test_py_function(tmp_path):
    f = tmp_path/"fn.py"; f.write_text("def hello():\n pass\n")
    names = [n["properties"]["name"] for n in _nodes(PythonParser().parse(f, tmp_path), "Function")]
    assert "hello" in names

@pytest.mark.ci
def test_py_class(tmp_path):
    f = tmp_path/"c.py"; f.write_text("class Foo:\n pass\n")
    names = [n["properties"]["name"] for n in _nodes(PythonParser().parse(f, tmp_path), "Class")]
    assert "Foo" in names

@pytest.mark.ci
def test_py_import(tmp_path):
    f = tmp_path/"i.py"; f.write_text("import os\n")
    targets = [e["target"] for e in _edges(PythonParser().parse(f, tmp_path), "IMPORTS")]
    assert "os" in targets

@pytest.mark.ci
def test_py_from_import(tmp_path):
    f = tmp_path/"fi.py"; f.write_text("from pathlib import Path\n")
    targets = [e["target"] for e in _edges(PythonParser().parse(f, tmp_path), "IMPORTS")]
    assert "pathlib" in targets

@pytest.mark.ci
def test_py_empty(tmp_path):
    f = tmp_path/"e.py"; f.write_text("")
    assert len(PythonParser().parse(f, tmp_path).nodes) >= 1

@pytest.mark.ci
def test_py_async(tmp_path):
    f = tmp_path/"a.py"; f.write_text("async def fetch():\n pass\n")
    r = PythonParser().parse(f, tmp_path)
    fn = next((n for n in _nodes(r, "Function") if n["properties"].get("name") == "fetch"), None)
    assert fn and fn["properties"].get("is_async") is True

@pytest.mark.ci
def test_py_multi_functions(tmp_path):
    f = tmp_path/"m.py"; f.write_text("def alpha():\n pass\ndef beta():\n pass\n")
    names = [n["properties"]["name"] for n in _nodes(PythonParser().parse(f, tmp_path), "Function")]
    assert "alpha" in names and "beta" in names

# JavaScript
@pytest.mark.ci
def test_js_file_node(tmp_path):
    f = tmp_path/"e.js"; f.write_text("")
    assert _nodes(JavaScriptParser().parse(f, tmp_path), "File")

@pytest.mark.ci
def test_js_function(tmp_path):
    f = tmp_path/"g.js"; f.write_text("function greet() {}\n")
    names = [n["properties"]["name"] for n in _nodes(JavaScriptParser().parse(f, tmp_path), "Function")]
    assert "greet" in names

@pytest.mark.ci
def test_js_import(tmp_path):
    f = tmp_path/"a.js"; f.write_text("import foo from './foo';\n")
    targets = [e["target"] for e in _edges(JavaScriptParser().parse(f, tmp_path), "IMPORTS")]
    assert "./foo" in targets

@pytest.mark.ci
def test_js_language(tmp_path):
    f = tmp_path/"i.js"; f.write_text("const x=1;\n")
    fn = next(n for n in JavaScriptParser().parse(f, tmp_path).nodes if n["label"]=="File")
    assert fn["properties"].get("language") == "javascript"

@pytest.mark.ci
def test_js_multi_imports(tmp_path):
    f = tmp_path/"m.js"; f.write_text("import React from 'react';\nimport axios from 'axios';\n")
    targets = [e["target"] for e in _edges(JavaScriptParser().parse(f, tmp_path), "IMPORTS")]
    assert "react" in targets and "axios" in targets

# Go
@pytest.mark.ci
def test_go_file_node(tmp_path):
    f = tmp_path/"m.go"; f.write_text("package main\n")
    assert _nodes(GoParser().parse(f, tmp_path), "File")

@pytest.mark.ci
def test_go_function(tmp_path):
    f = tmp_path/"h.go"; f.write_text("package main\nfunc hello() {}\n")
    names = [n["properties"]["name"] for n in _nodes(GoParser().parse(f, tmp_path), "Function")]
    assert "hello" in names

@pytest.mark.ci
def test_go_import(tmp_path):
    f = tmp_path/"f.go"; f.write_text('package main\nimport "fmt"\nfunc main(){fmt.Println("hi")}\n')
    targets = [e["target"] for e in _edges(GoParser().parse(f, tmp_path), "IMPORTS")]
    assert "fmt" in targets

@pytest.mark.ci
def test_go_grouped_import(tmp_path):
    f = tmp_path/"g.go"; f.write_text('package main\nimport(\n"fmt"\n"os"\n)\nfunc main(){}\n')
    targets = [e["target"] for e in _edges(GoParser().parse(f, tmp_path), "IMPORTS")]
    assert "fmt" in targets and "os" in targets

@pytest.mark.ci
def test_go_language(tmp_path):
    f = tmp_path/"l.go"; f.write_text("package main\n")
    fn = next(n for n in GoParser().parse(f, tmp_path).nodes if n["label"]=="File")
    assert fn["properties"].get("language") == "go"

# Java / Ruby / Rust — require jsat[standard] tree-sitter grammars
# These tests skip automatically if the grammar package is not installed.

@pytest.mark.ci
def test_java_file_node(tmp_path):
    pytest.importorskip("tree_sitter_java", reason="tree-sitter-java not installed (pip install 'jsat[standard]')")
    f = tmp_path / "Hello.java"; f.write_text("public class Hello {}\n")
    from jsat._parsers.java import JavaParser
    assert any(n["label"] == "File" for n in JavaParser().parse(f, tmp_path).nodes)

@pytest.mark.ci
def test_java_class(tmp_path):
    pytest.importorskip("tree_sitter_java")
    f = tmp_path / "Foo.java"; f.write_text("public class Foo { public void bar(){} }\n")
    from jsat._parsers.java import JavaParser
    r = JavaParser().parse(f, tmp_path)
    assert any(n["label"] == "Class" for n in r.nodes)

@pytest.mark.ci
def test_java_import(tmp_path):
    pytest.importorskip("tree_sitter_java")
    f = tmp_path / "A.java"; f.write_text("import java.util.List;\npublic class A {}\n")
    from jsat._parsers.java import JavaParser
    targets = [e["target"] for e in JavaParser().parse(f, tmp_path).edges if e["type"] == "IMPORTS"]
    assert "java.util.List" in targets or any("java" in t for t in targets)

# Ruby
@pytest.mark.ci
def test_ruby_file_node(tmp_path):
    pytest.importorskip("tree_sitter_ruby")
    f = tmp_path / "app.rb"; f.write_text("puts 'hello'\n")
    from jsat._parsers.ruby import RubyParser
    assert any(n["label"] == "File" for n in RubyParser().parse(f, tmp_path).nodes)

@pytest.mark.ci
def test_ruby_method(tmp_path):
    pytest.importorskip("tree_sitter_ruby")
    f = tmp_path / "svc.rb"; f.write_text("def greet\n  'hi'\nend\n")
    from jsat._parsers.ruby import RubyParser
    names = [n["properties"]["name"] for n in RubyParser().parse(f, tmp_path).nodes if n["label"] == "Function"]
    assert "greet" in names

@pytest.mark.ci
def test_ruby_require(tmp_path):
    pytest.importorskip("tree_sitter_ruby")
    f = tmp_path / "app.rb"; f.write_text("require 'json'\n")
    from jsat._parsers.ruby import RubyParser
    targets = [e["target"] for e in RubyParser().parse(f, tmp_path).edges if e["type"] == "IMPORTS"]
    assert any("json" in t for t in targets)

# Rust
@pytest.mark.ci
def test_rust_file_node(tmp_path):
    pytest.importorskip("tree_sitter_rust")
    f = tmp_path / "main.rs"; f.write_text("fn main() {}\n")
    from jsat._parsers.rust import RustParser
    assert any(n["label"] == "File" for n in RustParser().parse(f, tmp_path).nodes)

@pytest.mark.ci
def test_rust_function(tmp_path):
    pytest.importorskip("tree_sitter_rust")
    f = tmp_path / "lib.rs"; f.write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n")
    from jsat._parsers.rust import RustParser
    names = [n["properties"]["name"] for n in RustParser().parse(f, tmp_path).nodes if n["label"] == "Function"]
    assert "add" in names

@pytest.mark.ci
def test_rust_use(tmp_path):
    pytest.importorskip("tree_sitter_rust")
    f = tmp_path / "lib.rs"; f.write_text("use std::collections::HashMap;\nfn main(){}\n")
    from jsat._parsers.rust import RustParser
    targets = [e["target"] for e in RustParser().parse(f, tmp_path).edges if e["type"] == "IMPORTS"]
    assert any("std" in t or "HashMap" in t for t in targets)

# Parser factory — new languages
@pytest.mark.ci
def test_get_parser_java():
    assert get_parser("java") is not None

@pytest.mark.ci
def test_get_parser_ruby():
    assert get_parser("ruby") is not None

@pytest.mark.ci
def test_get_parser_rust():
    assert get_parser("rust") is not None

@pytest.mark.ci
def test_detect_java():
    assert detect_language(Path("Foo.java")) == "java"

@pytest.mark.ci
def test_detect_ruby():
    assert detect_language(Path("app.rb")) == "ruby"

@pytest.mark.ci
def test_detect_rust():
    assert detect_language(Path("lib.rs")) == "rust"
