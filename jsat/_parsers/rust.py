"""jsat._parsers.rust — Rust AST extractor using tree-sitter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

# tree-sitter-rust node types for functions at the top level or inside impl blocks.
_FN_TYPES = {"function_item"}
# Struct / enum / impl containers.
_STRUCT_TYPES = {"struct_item", "enum_item"}


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
    """Return the nearest enclosing impl_item, if any."""
    cur = node.parent
    while cur:
        if cur.type == "impl_item":
            return cur
        cur = cur.parent
    return None


def _impl_type_name(impl_node: Any, src: bytes) -> str | None:
    """Extract the Self type name from an impl_item node.

    tree-sitter-rust: the "type" field of impl_item holds the implementing
    type (e.g. `MyStruct` in `impl MyStruct { ... }`).
    """
    type_node = impl_node.child_by_field_name("type")
    if type_node:
        return _text(type_node, src).strip()
    return None


def _has_pub_visibility(fn_node: Any, src: bytes) -> bool:
    """Return True if the function_item has an explicit `pub` visibility modifier."""
    vis = fn_node.child_by_field_name("visibility_modifier")
    if vis is None:
        return False
    vis_text = _text(vis, src).strip()
    # `pub` → fully public; `pub(crate)` → crate-private; others are restricted.
    return vis_text == "pub"


def _is_public_fn(fn_node: Any, src: bytes) -> bool:
    """Determine whether a function_item is considered public.

    Rules (matching the task specification):
    - No leading underscore on the function name.
    - Not restricted to `pub(crate)` only visibility.
    - Presence of `pub` keyword (without restriction) makes it public.
    - Top-level functions with no visibility modifier are crate-internal (not public).
    - Functions inside impl blocks with no visibility modifier are private.
    """
    nn = fn_node.child_by_field_name("name")
    if nn and _text(nn, src).startswith("_"):
        return False
    return _has_pub_visibility(fn_node, src)


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

        # Structs and enums
        for item in _collect(root, _STRUCT_TYPES):
            nn = item.child_by_field_name("name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": "rust",
                "kind": item.type,  # "struct_item" or "enum_item"
                "line_start": item.start_point[0] + 1, "line_end": item.end_point[0] + 1,
                "is_public": _has_pub_visibility(item, src),
            }})

        # Functions: top-level function_item and those inside impl_item blocks.
        for fn in _collect(root, _FN_TYPES):
            nn = fn.child_by_field_name("name")
            if not nn:
                continue
            bare = _text(nn, src)

            # Qualify with the impl type when nested inside an impl block.
            impl_node = _enclosing_impl(fn)
            if impl_node:
                type_name = _impl_type_name(impl_node, src)
                qual = f"{type_name}.{bare}" if type_name else bare
            else:
                qual = bare

            nid = f"{fid}::{qual}"
            fn_id_map[fn.id] = nid
            result.nodes.append({"id": nid, "label": "Function", "properties": {
                "name": qual, "file": fid, "language": "rust",
                "line_start": fn.start_point[0] + 1, "line_end": fn.end_point[0] + 1,
                "is_public": _is_public_fn(fn, src),
                "in_impl": impl_node is not None,
            }})

        # use_declaration → IMPORTS edges
        # tree-sitter-rust: use_declaration children contain the use path.
        # The "argument" field holds the path or use_wildcard/use_list.
        for use_decl in _collect(root, {"use_declaration"}):
            arg = use_decl.child_by_field_name("argument")
            if arg is None:
                continue
            # Flatten the use path to a string (handles `use foo::bar`, `use foo::*`,
            # `use foo::{A, B}` — for grouped imports we emit one edge per leaf).
            _emit_use_edges(result, fid, arg, src, prefix="")

        # call_expression → CALLS edges
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
    """Recursively walk a use argument node and emit IMPORTS edges.

    Handles:
    - scoped_identifier (e.g. foo::bar::Baz)
    - use_wildcard (e.g. foo::*)
    - use_list (e.g. {A, B, C})
    - identifier (leaf name)
    """
    ntype = node.type

    if ntype == "use_list":
        # Grouped imports: emit one edge per child item.
        for ch in node.children:
            if ch.type not in ("{", "}", ","):
                _emit_use_edges(result, fid, ch, src, prefix)
        return

    if ntype == "scoped_identifier":
        # path field is the left-hand path; name field is the rightmost segment.
        path_node = node.child_by_field_name("path")
        name_node = node.child_by_field_name("name")
        if path_node and name_node:
            left = _text(path_node, src).strip()
            right = _text(name_node, src).strip()
            full = f"{prefix}{left}::{right}" if not prefix else f"{prefix}{left}::{right}"
            result.edges.append({"source": fid, "target": full,
                                  "type": "IMPORTS", "properties": {}})
        else:
            # Fallback: emit the whole text.
            raw = _text(node, src).strip()
            if raw:
                target = f"{prefix}{raw}" if prefix else raw
                result.edges.append({"source": fid, "target": target,
                                      "type": "IMPORTS", "properties": {}})
        return

    if ntype == "use_wildcard":
        raw = _text(node, src).strip()
        if raw:
            target = f"{prefix}{raw}" if prefix else raw
            result.edges.append({"source": fid, "target": target,
                                  "type": "IMPORTS", "properties": {}})
        return

    if ntype == "identifier":
        name = _text(node, src).strip()
        if name:
            target = f"{prefix}{name}" if prefix else name
            result.edges.append({"source": fid, "target": target,
                                  "type": "IMPORTS", "properties": {}})
        return

    # Fallback for any other node type — emit the full text.
    raw = _text(node, src).strip()
    if raw:
        target = f"{prefix}{raw}" if prefix else raw
        result.edges.append({"source": fid, "target": target,
                              "type": "IMPORTS", "properties": {}})
