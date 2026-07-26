"""jsat._parsers.javascript — JS/TS AST extractor using tree-sitter.

Extracts per-function: parameters, return_type (TS), decorators (TS), docstring (JSDoc),
cyclomatic complexity, loc, line alias.
Extracts per-class: bases (extends), decorators, docstring, method_count, line alias.
New edges: INHERITS (class→parent via extends).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

_FUNC_TYPES = {"function_declaration", "function_expression", "arrow_function", "method_definition"}

_BRANCH_TYPES = {
    "if_statement", "for_statement", "for_in_statement", "for_of_statement",
    "while_statement", "do_statement", "catch_clause", "conditional_expression",
    "ternary_expression", "switch_case", "logical_expression", "nullish_coalescing",
}


def _text(node: Any, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _collect(root: Any, types: set[str]) -> list[Any]:
    out, stack = [], [root]
    while stack:
        n = stack.pop()
        if n.type in types:
            out.append(n)
        stack.extend(reversed(n.children))
    return out


def _fn_name(fn: Any, src: bytes) -> str | None:
    nn = fn.child_by_field_name("name")
    if nn:
        return _text(nn, src)
    par = fn.parent
    if par and par.type == "variable_declarator":
        idn = par.child_by_field_name("name")
        if idn:
            return _text(idn, src)
    if par and par.type == "pair":
        key = par.child_by_field_name("key")
        if key:
            return _text(key, src)
    return None


def _enclosing_fn(node: Any) -> Any | None:
    cur = node.parent
    while cur:
        if cur.type in _FUNC_TYPES:
            return cur
        cur = cur.parent
    return None


def _extract_params(fn_node: Any, src: bytes) -> list[dict]:
    params_node = fn_node.child_by_field_name("parameters") or \
                  fn_node.child_by_field_name("parameter")
    if not params_node:
        return []
    params: list[dict] = []
    for p in params_node.children:
        t = p.type
        if t == "identifier":
            params.append({"name": _text(p, src)})
        elif t == "required_parameter":
            name_n = p.child_by_field_name("pattern")
            type_n = p.child_by_field_name("type")
            entry: dict = {"name": _text(name_n, src) if name_n else "?"}
            if type_n:
                entry["type"] = _text(type_n, src).lstrip(":").strip()
            params.append(entry)
        elif t in ("optional_parameter",):
            name_n = p.child_by_field_name("pattern")
            type_n = p.child_by_field_name("type")
            entry = {"name": _text(name_n, src) if name_n else "?", "optional": True}
            if type_n:
                entry["type"] = _text(type_n, src).lstrip(":").strip()
            params.append(entry)
        elif t in ("rest_parameter",):
            name_n = p.children[-1] if p.children else None
            params.append({"name": "..." + (_text(name_n, src) if name_n else "")})
        elif t == "assignment_pattern":
            name_n = p.child_by_field_name("left")
            params.append({"name": _text(name_n, src) if name_n else "?"})
    return params


def _extract_return_type(fn_node: Any, src: bytes) -> str:
    ret_n = fn_node.child_by_field_name("return_type")
    if not ret_n:
        return ""
    return _text(ret_n, src).lstrip(":").strip()


def _extract_decorators(fn_node: Any, src: bytes) -> list[str]:
    parent = fn_node.parent
    if not parent:
        return []
    decorators: list[str] = []
    for ch in parent.children:
        if ch.end_byte > fn_node.start_byte:
            break
        if ch.type == "decorator":
            raw = _text(ch, src).lstrip("@").split("(")[0].strip()
            if raw:
                decorators.append(raw)
    return decorators


def _extract_jsdoc(fn_node: Any, src: bytes) -> str:
    """First content line from a // or /** comment immediately before the function."""
    start = fn_node.start_byte
    preceding = src[max(0, start - 500):start].decode("utf-8", errors="replace")
    lines = preceding.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip().lstrip("/*").lstrip("//").strip()  # noqa: B005
        if stripped and not stripped.startswith("*"):
            return stripped[:200]
        if stripped.startswith("*") and stripped.lstrip("*").strip():
            return stripped.lstrip("*").strip()[:200]
    return ""


def _complexity(fn_node: Any) -> int:
    body = fn_node.child_by_field_name("body")
    if not body:
        return 1
    return 1 + len(_collect(body, _BRANCH_TYPES))


def _extract_bases(cls_node: Any, src: bytes) -> list[str]:
    """Extract extends clause: class Foo extends Bar."""
    heritage = cls_node.child_by_field_name("heritage")
    if not heritage:
        return []
    bases: list[str] = []
    for ch in heritage.children:
        if ch.type in ("identifier", "member_expression"):
            name = _text(ch, src).strip()
            if name:
                bases.append(name)
    return bases


def _count_methods(cls_node: Any) -> int:
    body = cls_node.child_by_field_name("body")
    if not body:
        return 0
    return sum(1 for ch in body.children if ch.type == "method_definition")


def _file_node(file_id: str, lang: str, loc: int) -> dict[str, Any]:
    return {"id": file_id, "label": "File",
            "properties": {"path": file_id, "language": lang, "loc": loc}}


class JavaScriptParser(BaseParser):
    language = "javascript"

    def parse(self, file_path: Path, repo_root: Path) -> ParseResult:
        import structlog
        log = structlog.get_logger(__name__)
        result = ParseResult()

        try:
            rel = file_path.relative_to(repo_root)
        except ValueError:
            rel = file_path
        fid = str(rel)
        lang = "typescript" if file_path.suffix in (".ts", ".tsx") else "javascript"

        try:
            src = file_path.read_bytes()
        except OSError as e:
            log.warning("js_parse_read_error", file=fid, error=str(e))
            result.nodes.append(_file_node(fid, lang, 0))
            return result

        loc = src.count(b"\n") + 1
        result.nodes.append(_file_node(fid, lang, loc))

        try:
            import tree_sitter_javascript as tsjs
            from tree_sitter import Language, Parser
            tree = Parser(Language(tsjs.language())).parse(src)
        except Exception as e:
            log.warning("js_parse_failed", file=fid, error=str(e))
            return result

        root = tree.root_node
        fn_id_map: dict[int, str] = {}

        # ── Functions ─────────────────────────────────────────────────────────
        for fn in _collect(root, _FUNC_TYPES):
            name = _fn_name(fn, src)
            fn_id_map[fn.id] = f"{fid}::{name}" if name else fid
            if name:
                nid = f"{fid}::{name}"
                is_async = any(c.type == "async" for c in fn.children)
                line_s = fn.start_point[0] + 1
                line_e = fn.end_point[0] + 1
                result.nodes.append({"id": nid, "label": "Function", "properties": {
                    "name": name, "file": fid, "language": lang,
                    "line_start": line_s, "line_end": line_e,
                    "line": line_s,
                    "loc": line_e - line_s + 1,
                    "is_async": is_async,
                    "is_public": not name.startswith("_"),
                    "parameters": _extract_params(fn, src),
                    "return_type": _extract_return_type(fn, src),
                    "decorators": _extract_decorators(fn, src),
                    "docstring": _extract_jsdoc(fn, src),
                    "complexity": _complexity(fn),
                }})

        # ── Classes ───────────────────────────────────────────────────────────
        for cls in _collect(root, {"class_declaration", "class"}):
            nn = cls.child_by_field_name("name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            bases = _extract_bases(cls, src)
            line_s = cls.start_point[0] + 1
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": lang,
                "line_start": line_s, "line_end": cls.end_point[0] + 1,
                "line": line_s,
                "is_public": not name.startswith("_"),
                "bases": bases,
                "decorators": _extract_decorators(cls, src),
                "docstring": _extract_jsdoc(cls, src),
                "method_count": _count_methods(cls),
            }})
            for base in bases:
                result.edges.append({"source": nid, "target": base,
                                     "type": "INHERITS", "properties": {}})

        # ── Imports ───────────────────────────────────────────────────────────
        for imp in _collect(root, {"import_statement"}):
            sn = imp.child_by_field_name("source")
            if sn:
                mod = _text(sn, src).strip().strip("'\"")
                if mod:
                    result.edges.append({"source": fid, "target": mod,
                                         "type": "IMPORTS", "properties": {}})

        # ── Calls ─────────────────────────────────────────────────────────────
        for call in _collect(root, {"call_expression"}):
            fn_node = call.child_by_field_name("function")
            if not fn_node:
                continue
            callee = _text(fn_node, src).strip()
            if not callee:
                continue
            enc = _enclosing_fn(call)
            src_id = fn_id_map.get(enc.id, fid) if enc else fid
            result.edges.append({"source": src_id, "target": callee,
                                  "type": "CALLS", "properties": {}})

        log.info("js_parse_done", file=fid, nodes=len(result.nodes), edges=len(result.edges))
        return result
