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
