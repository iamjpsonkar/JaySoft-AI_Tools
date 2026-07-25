"""jsat._parsers.go — Go AST extractor using tree-sitter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

_FUNC_TYPES = {"function_declaration", "method_declaration"}


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


def _receiver_type(recv: Any, src: bytes) -> str | None:
    stack = list(recv.children)
    while stack:
        c = stack.pop()
        if c.type == "type_identifier":
            return _text(c, src)
        stack.extend(c.children)
    return None


def _fn_name(fn: Any, src: bytes) -> str | None:
    nn = fn.child_by_field_name("name")
    if not nn:
        return None
    name = _text(nn, src)
    if fn.type == "method_declaration":
        recv = fn.child_by_field_name("receiver")
        if recv:
            rt = _receiver_type(recv, src)
            if rt:
                return f"{rt}.{name}"
    return name


def _enclosing_fn(node: Any) -> Any | None:
    cur = node.parent
    while cur:
        if cur.type in _FUNC_TYPES:
            return cur
        cur = cur.parent
    return None


def _file_node(file_id: str, loc: int) -> dict[str, Any]:
    return {"id": file_id, "label": "File",
            "properties": {"path": file_id, "language": "go", "loc": loc}}


class GoParser(BaseParser):
    language = "go"

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
            log.warning("go_parse_read_error", file=fid, error=str(e))
            result.nodes.append(_file_node(fid, 0))
            return result

        loc = src.count(b"\n") + 1
        result.nodes.append(_file_node(fid, loc))

        try:
            import tree_sitter_go as tsgo
            from tree_sitter import Language, Parser
            tree = Parser(Language(tsgo.language())).parse(src)
        except Exception as e:
            log.warning("go_parse_failed", file=fid, error=str(e))
            return result

        root = tree.root_node
        fn_id_map: dict[int, str] = {}

        # Functions and methods
        for fn in _collect(root, _FUNC_TYPES):
            name = _fn_name(fn, src)
            fn_id_map[fn.id] = f"{fid}::{name}" if name else fid
            if name:
                result.nodes.append({"id": f"{fid}::{name}", "label": "Function", "properties": {
                    "name": name, "file": fid, "language": "go",
                    "line_start": fn.start_point[0] + 1, "line_end": fn.end_point[0] + 1,
                    "is_method": fn.type == "method_declaration",
                    "is_public": bool(name) and name[0].isupper(),
                }})

        # Imports
        for decl in _collect(root, {"import_declaration"}):
            for spec in _collect(decl, {"import_spec"}):
                pn = spec.child_by_field_name("path")
                if pn:
                    path = _text(pn, src).strip().strip('"')
                    if path:
                        result.edges.append({"source": fid, "target": path,
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

        log.info("go_parse_done", file=fid, nodes=len(result.nodes), edges=len(result.edges))
        return result
