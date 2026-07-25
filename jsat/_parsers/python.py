"""jsat._parsers.python — Python AST extractor using tree-sitter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult


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

        # Classes
        for cls in _collect(root, {"class_definition"}):
            nn = _child(cls, "name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": "python",
                "line_start": cls.start_point[0] + 1, "line_end": cls.end_point[0] + 1,
                "is_public": not name.startswith("_"),
            }})

        # Functions
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
            result.nodes.append({"id": nid, "label": "Function", "properties": {
                "name": qual, "file": fid, "language": "python",
                "line_start": fn.start_point[0] + 1, "line_end": fn.end_point[0] + 1,
                "is_async": fn.type == "async_function_definition",
                "is_public": not bare.startswith("_"),
            }})

        # Imports → IMPORTS edges
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

        # Calls → CALLS edges
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
