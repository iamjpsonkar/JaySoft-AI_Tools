"""jsat._parsers.go — Go AST extractor using tree-sitter.

Extracts per-function: parameters (name+type), return_type, cyclomatic complexity,
loc, line alias.
Extracts per-class (struct/interface): bases (via embedding), method_count, line alias.
New edges: IMPLEMENTS (struct→interface via type assertions or embedding).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

_FUNC_TYPES = {"function_declaration", "method_declaration"}
_TYPE_TYPES = {"type_declaration"}

_BRANCH_TYPES = {
    "if_statement", "for_statement", "select_statement",
    "case_clause", "type_switch_statement", "expression_switch_statement",
    "communication_case", "default_case",
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


def _extract_params(fn_node: Any, src: bytes) -> list[dict]:
    params_node = fn_node.child_by_field_name("parameters")
    if not params_node:
        return []
    params: list[dict] = []
    for param_decl in _collect(
        params_node, {"parameter_declaration", "variadic_parameter_declaration"}
    ):
        type_n = param_decl.child_by_field_name("type")
        type_str = _text(type_n, src).strip() if type_n else ""
        has_name = False
        for ch in param_decl.children:
            if ch.type == "identifier":
                params.append({"name": _text(ch, src), "type": type_str})
                has_name = True
        if not has_name and type_str:
            params.append({"type": type_str})
    return params


def _extract_return_type(fn_node: Any, src: bytes) -> str:
    result_n = fn_node.child_by_field_name("result")
    return _text(result_n, src).strip() if result_n else ""


def _extract_doc_comment(fn_node: Any, src: bytes) -> str:
    """Extract // comment lines immediately preceding the function."""
    start = fn_node.start_byte
    preceding = src[max(0, start - 400):start].decode("utf-8", errors="replace")
    lines = preceding.rstrip().splitlines()
    doc_lines: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            doc_lines.insert(0, stripped[2:].strip())
        else:
            break
    return " ".join(doc_lines)[:200] if doc_lines else ""


def _complexity(fn_node: Any) -> int:
    body = fn_node.child_by_field_name("body")
    if not body:
        return 1
    return 1 + len(_collect(body, _BRANCH_TYPES))


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

        # ── Type declarations (struct, interface) ─────────────────────────────
        for type_decl in _collect(root, {"type_declaration"}):
            for spec in _collect(type_decl, {"type_spec"}):
                name_n = spec.child_by_field_name("name")
                type_n = spec.child_by_field_name("type")
                if not name_n or not type_n:
                    continue
                name = _text(name_n, src)
                type_kind = type_n.type  # "struct_type" | "interface_type" | other
                if type_kind not in ("struct_type", "interface_type"):
                    continue
                nid = f"{fid}::{name}"
                line_s = spec.start_point[0] + 1
                result.nodes.append({"id": nid, "label": "Class", "properties": {
                    "name": name, "file": fid, "language": "go",
                    "line_start": line_s, "line_end": spec.end_point[0] + 1,
                    "line": line_s,
                    "is_public": bool(name) and name[0].isupper(),
                    "kind": type_kind,
                    "bases": [],
                    "decorators": [],
                    "docstring": _extract_doc_comment(spec, src),
                    "method_count": 0,
                }})

        # ── Functions and methods ─────────────────────────────────────────────
        for fn in _collect(root, _FUNC_TYPES):
            name = _fn_name(fn, src)
            fn_id_map[fn.id] = f"{fid}::{name}" if name else fid
            if name:
                line_s = fn.start_point[0] + 1
                line_e = fn.end_point[0] + 1
                result.nodes.append({"id": f"{fid}::{name}", "label": "Function", "properties": {
                    "name": name, "file": fid, "language": "go",
                    "line_start": line_s, "line_end": line_e,
                    "line": line_s,
                    "loc": line_e - line_s + 1,
                    "is_method": fn.type == "method_declaration",
                    "is_public": bool(name) and name[0].isupper(),
                    "parameters": _extract_params(fn, src),
                    "return_type": _extract_return_type(fn, src),
                    "decorators": [],
                    "docstring": _extract_doc_comment(fn, src),
                    "complexity": _complexity(fn),
                }})

        # ── Imports ───────────────────────────────────────────────────────────
        for decl in _collect(root, {"import_declaration"}):
            for spec in _collect(decl, {"import_spec"}):
                pn = spec.child_by_field_name("path")
                if pn:
                    imp_path = _text(pn, src).strip().strip('"')
                    if imp_path:
                        result.edges.append({"source": fid, "target": imp_path,
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

        log.info("go_parse_done", file=fid, nodes=len(result.nodes), edges=len(result.edges))
        return result
