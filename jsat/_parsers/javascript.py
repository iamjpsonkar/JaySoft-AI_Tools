"""jsat._parsers.javascript — JS/TS AST extractor using tree-sitter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

_FUNC_TYPES = {"function_declaration", "function_expression", "arrow_function", "method_definition"}


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
    return None


def _enclosing_fn(node: Any) -> Any | None:
    cur = node.parent
    while cur:
        if cur.type in _FUNC_TYPES:
            return cur
        cur = cur.parent
    return None


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

        # Functions
        for fn in _collect(root, _FUNC_TYPES):
            name = _fn_name(fn, src)
            fn_id_map[fn.id] = f"{fid}::{name}" if name else fid
            if name:
                nid = f"{fid}::{name}"
                is_async = any(c.type == "async" for c in fn.children)
                result.nodes.append({"id": nid, "label": "Function", "properties": {
                    "name": name, "file": fid, "language": lang,
                    "line_start": fn.start_point[0] + 1, "line_end": fn.end_point[0] + 1,
                    "is_async": is_async, "is_public": not name.startswith("_"),
                }})

        # Classes
        for cls in _collect(root, {"class_declaration"}):
            nn = cls.child_by_field_name("name")
            if not nn:
                continue
            name = _text(nn, src)
            result.nodes.append({"id": f"{fid}::{name}", "label": "Class", "properties": {
                "name": name, "file": fid, "language": lang,
                "line_start": cls.start_point[0] + 1, "line_end": cls.end_point[0] + 1,
            }})

        # Imports
        for imp in _collect(root, {"import_statement"}):
            sn = imp.child_by_field_name("source")
            if sn:
                mod = _text(sn, src).strip().strip("'\"")
                if mod:
                    result.edges.append({"source": fid, "target": mod,
                                         "type": "IMPORTS", "properties": {}})

        # Calls
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
