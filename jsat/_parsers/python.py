"""jsat._parsers.python — Python AST extractor using tree-sitter.

Extracts per-function: parameters (name+type+default), return_type, decorators,
docstring (first line), cyclomatic complexity, loc, line alias.
Extracts per-class: bases, decorators, docstring, method_count, line alias.
New edges: INHERITS (class→parent), RAISES (function→exception).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

# Branch node types for cyclomatic complexity
_BRANCH_TYPES = {
    "if_statement", "elif_clause", "for_statement", "while_statement",
    "except_clause", "match_statement", "case_clause",
    "conditional_expression", "boolean_operator",
}


def _text(node: Any, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _child(node: Any, field: str) -> Any | None:
    return node.child_by_field_name(field)


def _collect(root: Any, types: set[str]) -> list[Any]:
    out, stack = [], [root]
    while stack:
        n = stack.pop()
        if n.type in types:
            out.append(n)
        stack.extend(reversed(n.children))
    return out


def _enclosing_fn(node: Any) -> Any | None:
    cur = node.parent
    while cur:
        if cur.type in ("function_definition", "async_function_definition"):
            return cur
        cur = cur.parent
    return None


def _enclosing_class(node: Any) -> Any | None:
    cur = node.parent
    while cur:
        if cur.type == "class_definition":
            return cur
        cur = cur.parent
    return None


def _is_async_fn(fn_node: Any, source: bytes) -> bool:
    if fn_node.type == "async_function_definition":
        return True
    for child in fn_node.children:
        if child.type == "async":
            return True
    parent = fn_node.parent
    if parent:
        for child in parent.children:
            if child.type == "async" and child.end_byte <= fn_node.start_byte:
                return True
    fn_start = fn_node.start_byte
    preceding = source[max(0, fn_start - 10):fn_start].decode("utf-8", errors="replace")
    return "async" in preceding.lower()


def _extract_params(fn_node: Any, src: bytes) -> list[dict]:
    """Extract parameter dicts: {name, type?, default?}."""
    params_node = _child(fn_node, "parameters")
    if not params_node:
        return []
    params: list[dict] = []
    for p in params_node.children:
        t = p.type
        if t == "identifier":
            name = _text(p, src)
            if name not in ("self", "cls"):
                params.append({"name": name})
        elif t == "typed_parameter":
            name_n = _child(p, "name") or (p.children[0] if p.children else None)
            type_n = _child(p, "type")
            name = _text(name_n, src) if name_n else "?"
            if name not in ("self", "cls"):
                entry: dict = {"name": name}
                if type_n:
                    entry["type"] = _text(type_n, src)
                params.append(entry)
        elif t == "default_parameter":
            name_n = _child(p, "name")
            val_n = _child(p, "value")
            if name_n:
                entry = {"name": _text(name_n, src)}
                if val_n:
                    entry["default"] = _text(val_n, src)[:60]
                params.append(entry)
        elif t == "typed_default_parameter":
            name_n = _child(p, "name")
            type_n = _child(p, "type")
            val_n = _child(p, "value")
            if name_n:
                entry = {"name": _text(name_n, src)}
                if type_n:
                    entry["type"] = _text(type_n, src)
                if val_n:
                    entry["default"] = _text(val_n, src)[:60]
                params.append(entry)
        elif t in ("list_splat_pattern", "dictionary_splat_pattern"):
            prefix = "**" if t == "dictionary_splat_pattern" else "*"
            inner = p.children[-1] if p.children else None
            if inner and inner.type == "identifier":
                params.append({"name": prefix + _text(inner, src)})
    return params


def _extract_return_type(fn_node: Any, src: bytes) -> str:
    ret_n = _child(fn_node, "return_type")
    if not ret_n:
        return ""
    return _text(ret_n, src).lstrip("->").strip()


def _extract_decorators(fn_node: Any, src: bytes) -> list[str]:
    """Decorators live on the decorated_definition parent node."""
    parent = fn_node.parent
    if not parent or parent.type != "decorated_definition":
        return []
    decorators: list[str] = []
    for ch in parent.children:
        if ch.type == "decorator":
            raw = _text(ch, src).lstrip("@").split("(")[0].strip()
            if raw:
                decorators.append(raw)
    return decorators


def _extract_docstring(fn_node: Any, src: bytes) -> str:
    """First line of the first string literal in the function body."""
    body = _child(fn_node, "body")
    if not body:
        return ""
    for ch in body.children:
        if ch.type == "expression_statement":
            for gc in ch.children:
                if gc.type == "string":
                    raw = _text(gc, src).strip()
                    for q in ('"""', "'''", '"', "'"):
                        if raw.startswith(q) and len(raw) > len(q) * 2:
                            raw = raw[len(q):]
                            raw = raw[: raw.rfind(q)] if q in raw else raw
                            break
                    return raw.split("\n")[0].strip()[:200]
    return ""


def _complexity(fn_node: Any) -> int:
    """Cyclomatic complexity: 1 + branch count within function body."""
    body = _child(fn_node, "body")
    if not body:
        return 1
    return 1 + len(_collect(body, _BRANCH_TYPES))


def _extract_bases(cls_node: Any, src: bytes) -> list[str]:
    """Return base class names from class Foo(Base1, Base2):"""
    args = _child(cls_node, "superclasses")
    if not args:
        return []
    bases: list[str] = []
    for ch in args.children:
        if ch.type in ("identifier", "attribute", "subscript"):
            name = _text(ch, src).strip()
            if name:
                bases.append(name)
    return bases


def _extract_class_decorators(cls_node: Any, src: bytes) -> list[str]:
    parent = cls_node.parent
    if not parent or parent.type != "decorated_definition":
        return []
    decorators: list[str] = []
    for ch in parent.children:
        if ch.type == "decorator":
            raw = _text(ch, src).lstrip("@").split("(")[0].strip()
            if raw:
                decorators.append(raw)
    return decorators


def _count_methods(cls_node: Any) -> int:
    body = _child(cls_node, "body")
    if not body:
        return 0
    count = 0
    for ch in body.children:
        if ch.type in ("function_definition", "async_function_definition"):
            count += 1
        elif ch.type == "decorated_definition":
            for gc in ch.children:
                if gc.type in ("function_definition", "async_function_definition"):
                    count += 1
                    break
    return count


def _file_node(file_id: str, loc: int) -> dict[str, Any]:
    return {"id": file_id, "label": "File",
            "properties": {"path": file_id, "language": "python", "loc": loc}}


class PythonParser(BaseParser):
    language = "python"

    def parse(self, file_path: Path, repo_root: Path) -> ParseResult:
        import structlog
        log = structlog.get_logger(__name__)
        result = ParseResult()

        try:
            rel = file_path.relative_to(repo_root)
        except ValueError:
            rel = file_path
        fid = str(rel)

        try:
            src = file_path.read_bytes()
        except OSError as e:
            log.warning("python_parse_read_error", file=fid, error=str(e))
            result.nodes.append(_file_node(fid, 0))
            return result

        loc = src.count(b"\n") + 1
        result.nodes.append(_file_node(fid, loc))

        try:
            import tree_sitter_python as tspy
            from tree_sitter import Language, Parser
            tree = Parser(Language(tspy.language())).parse(src)
        except Exception as e:
            log.warning("python_parse_failed", file=fid, error=str(e))
            return result

        root = tree.root_node
        fn_id_map: dict[int, str] = {}

        # ── Classes ───────────────────────────────────────────────────────────
        for cls in _collect(root, {"class_definition"}):
            nn = _child(cls, "name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            bases = _extract_bases(cls, src)
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": "python",
                "line_start": cls.start_point[0] + 1,
                "line_end": cls.end_point[0] + 1,
                "line": cls.start_point[0] + 1,
                "is_public": not name.startswith("_"),
                "bases": bases,
                "decorators": _extract_class_decorators(cls, src),
                "docstring": _extract_docstring(cls, src),
                "method_count": _count_methods(cls),
            }})
            for base in bases:
                result.edges.append({"source": nid, "target": base,
                                     "type": "INHERITS", "properties": {}})

        # ── Functions ─────────────────────────────────────────────────────────
        for fn in _collect(root, {"function_definition", "async_function_definition"}):
            nn = _child(fn, "name")
            if not nn:
                continue
            bare = _text(nn, src)
            enc_cls = _enclosing_class(fn)
            if enc_cls:
                cnn = _child(enc_cls, "name")
                qual = f"{_text(cnn, src)}.{bare}" if cnn else bare
            else:
                qual = bare
            nid = f"{fid}::{qual}"
            fn_id_map[fn.id] = nid
            line_s = fn.start_point[0] + 1
            line_e = fn.end_point[0] + 1
            result.nodes.append({"id": nid, "label": "Function", "properties": {
                "name": qual, "file": fid, "language": "python",
                "line_start": line_s, "line_end": line_e,
                "line": line_s,
                "loc": line_e - line_s + 1,
                "is_async": _is_async_fn(fn, src),
                "is_public": not bare.startswith("_"),
                "parameters": _extract_params(fn, src),
                "return_type": _extract_return_type(fn, src),
                "decorators": _extract_decorators(fn, src),
                "docstring": _extract_docstring(fn, src),
                "complexity": _complexity(fn),
            }})
            # RAISES edges
            body = _child(fn, "body")
            if body:
                for raise_stmt in _collect(body, {"raise_statement"}):
                    for ch in raise_stmt.children:
                        if ch.type not in ("raise",):
                            exc_name = _text(ch, src).split("(")[0].strip()
                            if exc_name and exc_name != "from":
                                result.edges.append({"source": nid, "target": exc_name,
                                                     "type": "RAISES", "properties": {}})
                            break

        # ── Imports → IMPORTS edges ───────────────────────────────────────────
        for imp in _collect(root, {"import_statement", "import_from_statement"}):
            if imp.type == "import_statement":
                for ch in imp.children:
                    if ch.type in ("dotted_name", "aliased_import"):
                        nn2 = ch if ch.type == "dotted_name" else _child(ch, "name")
                        if nn2:
                            result.edges.append({"source": fid, "target": _text(nn2, src).strip(),
                                                 "type": "IMPORTS", "properties": {}})
            else:
                mn = _child(imp, "module_name")
                if mn:
                    result.edges.append({"source": fid, "target": _text(mn, src).strip(),
                                         "type": "IMPORTS", "properties": {}})

        # ── Calls → CALLS edges ───────────────────────────────────────────────
        for call in _collect(root, {"call"}):
            fn_node = _child(call, "function")
            if not fn_node:
                continue
            callee = _text(fn_node, src).strip()
            if not callee:
                continue
            enc = _enclosing_fn(call)
            src_id = fn_id_map.get(enc.id, fid) if enc else fid
            result.edges.append({"source": src_id, "target": callee,
                                  "type": "CALLS", "properties": {}})

        log.info("python_parse_done", file=fid, nodes=len(result.nodes), edges=len(result.edges))
        return result
