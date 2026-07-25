"""jsat._parsers.rust — Rust AST extractor using tree-sitter.

Extracts per-function: parameters (name+type), return_type, attributes (#[...]),
cyclomatic complexity, loc, line alias.
Extracts per-struct/enum: attributes, docstring, method_count, line alias.
New edges: IMPLEMENTS (type→trait via impl Trait for Type).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

_FN_TYPES = {"function_item"}
_STRUCT_TYPES = {"struct_item", "enum_item"}

_BRANCH_TYPES = {
    "if_expression", "match_expression", "loop_expression",
    "while_expression", "for_expression", "match_arm",
    "while_let_expression", "if_let_expression",
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


def _enclosing_fn(node: Any) -> Any | None:
    cur = node.parent
    while cur:
        if cur.type in _FN_TYPES:
            return cur
        cur = cur.parent
    return None


def _enclosing_impl(node: Any) -> Any | None:
    cur = node.parent
    while cur:
        if cur.type == "impl_item":
            return cur
        cur = cur.parent
    return None


def _impl_type_name(impl_node: Any, src: bytes) -> str | None:
    type_node = impl_node.child_by_field_name("type")
    return _text(type_node, src).strip() if type_node else None


def _has_pub_visibility(fn_node: Any, src: bytes) -> bool:
    vis = fn_node.child_by_field_name("visibility_modifier")
    if vis is None:
        return False
    return _text(vis, src).strip() == "pub"


def _is_public_fn(fn_node: Any, src: bytes) -> bool:
    nn = fn_node.child_by_field_name("name")
    if nn and _text(nn, src).startswith("_"):
        return False
    return _has_pub_visibility(fn_node, src)


def _extract_params(fn_node: Any, src: bytes) -> list[dict]:
    params_node = fn_node.child_by_field_name("parameters")
    if not params_node:
        return []
    params: list[dict] = []
    for p in params_node.children:
        if p.type == "parameter":
            pattern_n = p.child_by_field_name("pattern")
            type_n = p.child_by_field_name("type")
            entry: dict = {"name": _text(pattern_n, src) if pattern_n else "?"}
            if type_n:
                entry["type"] = _text(type_n, src)
            params.append(entry)
        elif p.type == "self_parameter":
            pass  # skip self/&self/&mut self
        elif p.type == "variadic_parameter":
            params.append({"name": "..."})
    return params


def _extract_return_type(fn_node: Any, src: bytes) -> str:
    ret_n = fn_node.child_by_field_name("return_type")
    return _text(ret_n, src).lstrip("->").strip() if ret_n else ""


def _extract_attributes(node: Any, src: bytes) -> list[str]:
    """Extract #[attr] names preceding a struct/function item."""
    parent = node.parent
    if not parent:
        return []
    attrs: list[str] = []
    for ch in parent.children:
        if ch.end_byte > node.start_byte:
            break
        if ch.type == "attribute_item":
            raw = _text(ch, src).strip()
            # "#[derive(Debug, Clone)]" → "derive(Debug, Clone)"
            inner = raw.lstrip("#[").rstrip("]")
            if inner:
                attrs.append(inner)
    return attrs


def _extract_doc_comment(node: Any, src: bytes) -> str:
    """Extract /// comment lines immediately preceding the item."""
    start = node.start_byte
    preceding = src[max(0, start - 500):start].decode("utf-8", errors="replace")
    lines = preceding.rstrip().splitlines()
    doc_lines: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("///"):
            doc_lines.insert(0, stripped[3:].strip())
        elif stripped.startswith("//!"):
            doc_lines.insert(0, stripped[3:].strip())
        elif stripped.startswith("//"):
            break
        else:
            break
    return " ".join(doc_lines)[:200] if doc_lines else ""


def _complexity(fn_node: Any) -> int:
    body = fn_node.child_by_field_name("body")
    if not body:
        return 1
    return 1 + len(_collect(body, _BRANCH_TYPES))


def _count_methods(impl_nodes: list[Any]) -> int:
    """Count function_items across all impl blocks for this type."""
    total = 0
    for impl in impl_nodes:
        body = impl.child_by_field_name("body")
        if body:
            total += sum(1 for ch in body.children if ch.type == "function_item")
    return total


def _file_node(file_id: str, loc: int) -> dict[str, Any]:
    return {"id": file_id, "label": "File",
            "properties": {"path": file_id, "language": "rust", "loc": loc}}


class RustParser(BaseParser):
    language = "rust"

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
            log.warning("rust_parse_read_error", file=fid, error=str(e))
            result.nodes.append(_file_node(fid, 0))
            return result

        loc = src.count(b"\n") + 1
        result.nodes.append(_file_node(fid, loc))

        try:
            import tree_sitter_rust as tsrust
            from tree_sitter import Language, Parser
            tree = Parser(Language(tsrust.language())).parse(src)
        except Exception as e:
            log.warning("rust_parse_failed", file=fid, error=str(e))
            return result

        root = tree.root_node
        fn_id_map: dict[int, str] = {}

        # Gather all impl_item nodes for method_count calculation
        all_impls = _collect(root, {"impl_item"})
        impl_by_type: dict[str, list[Any]] = {}
        for impl in all_impls:
            type_n = impl.child_by_field_name("type")
            if type_n:
                key = _text(type_n, src).strip()
                impl_by_type.setdefault(key, []).append(impl)

        # ── Structs and enums ─────────────────────────────────────────────────
        for item in _collect(root, _STRUCT_TYPES):
            nn = item.child_by_field_name("name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            line_s = item.start_point[0] + 1
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": "rust",
                "kind": item.type,
                "line_start": line_s, "line_end": item.end_point[0] + 1,
                "line": line_s,
                "is_public": _has_pub_visibility(item, src),
                "bases": [],
                "decorators": _extract_attributes(item, src),
                "docstring": _extract_doc_comment(item, src),
                "method_count": _count_methods(impl_by_type.get(name, [])),
            }})

        # ── impl Trait for Type → IMPLEMENTS edges ────────────────────────────
        for impl in all_impls:
            trait_n = impl.child_by_field_name("trait")
            type_n = impl.child_by_field_name("type")
            if trait_n and type_n:
                type_name = _text(type_n, src).strip()
                trait_name = _text(trait_n, src).strip()
                result.edges.append({
                    "source": f"{fid}::{type_name}",
                    "target": trait_name,
                    "type": "IMPLEMENTS",
                    "properties": {},
                })

        # ── Functions ─────────────────────────────────────────────────────────
        for fn in _collect(root, _FN_TYPES):
            nn = fn.child_by_field_name("name")
            if not nn:
                continue
            bare = _text(nn, src)
            impl_node = _enclosing_impl(fn)
            if impl_node:
                type_name = _impl_type_name(impl_node, src)
                qual = f"{type_name}.{bare}" if type_name else bare
            else:
                qual = bare
            nid = f"{fid}::{qual}"
            fn_id_map[fn.id] = nid
            line_s = fn.start_point[0] + 1
            line_e = fn.end_point[0] + 1
            result.nodes.append({"id": nid, "label": "Function", "properties": {
                "name": qual, "file": fid, "language": "rust",
                "line_start": line_s, "line_end": line_e,
                "line": line_s,
                "loc": line_e - line_s + 1,
                "is_public": _is_public_fn(fn, src),
                "in_impl": impl_node is not None,
                "parameters": _extract_params(fn, src),
                "return_type": _extract_return_type(fn, src),
                "decorators": _extract_attributes(fn, src),
                "docstring": _extract_doc_comment(fn, src),
                "complexity": _complexity(fn),
            }})

        # ── use_declaration → IMPORTS edges ──────────────────────────────────
        for use_decl in _collect(root, {"use_declaration"}):
            arg = use_decl.child_by_field_name("argument")
            if arg is None:
                continue
            _emit_use_edges(result, fid, arg, src, prefix="")

        # ── call_expression → CALLS edges ────────────────────────────────────
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

        log.info("rust_parse_done", file=fid, nodes=len(result.nodes), edges=len(result.edges))
        return result


def _emit_use_edges(result: ParseResult, fid: str, node: Any, src: bytes,
                    prefix: str) -> None:
    ntype = node.type
    if ntype == "use_list":
        for ch in node.children:
            if ch.type not in ("{", "}", ","):
                _emit_use_edges(result, fid, ch, src, prefix)
        return
    if ntype == "scoped_identifier":
        path_node = node.child_by_field_name("path")
        name_node = node.child_by_field_name("name")
        if path_node and name_node:
            full = f"{prefix}{_text(path_node, src)}::{_text(name_node, src)}"
            result.edges.append({"source": fid, "target": full.strip(),
                                  "type": "IMPORTS", "properties": {}})
        else:
            raw = _text(node, src).strip()
            if raw:
                result.edges.append({"source": fid, "target": raw,
                                      "type": "IMPORTS", "properties": {}})
        return
    raw = _text(node, src).strip()
    if raw:
        result.edges.append({"source": fid, "target": raw,
                              "type": "IMPORTS", "properties": {}})
