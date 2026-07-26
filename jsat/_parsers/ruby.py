"""jsat._parsers.ruby — Ruby AST extractor using tree-sitter.

Extracts per-method: parameters, cyclomatic complexity, loc, line alias.
Extracts per-class: bases (< SuperClass), method_count, docstring, line alias.
New edges: INHERITS (class→superclass).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

_METHOD_TYPES = {"method", "singleton_method"}
_CLASS_TYPES = {"class", "module"}

_BRANCH_TYPES = {
    "if", "unless", "while", "until", "rescue", "case", "when",
    "elsif", "if_modifier", "unless_modifier", "while_modifier", "until_modifier",
    "ternary",
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
        if cur.type in _METHOD_TYPES:
            return cur
        cur = cur.parent
    return None


def _enclosing_class(node: Any) -> Any | None:
    cur = node.parent
    while cur:
        if cur.type in _CLASS_TYPES:
            return cur
        cur = cur.parent
    return None


def _method_name(fn: Any, src: bytes) -> str | None:
    nn = fn.child_by_field_name("name")
    return _text(nn, src) if nn else None


def _extract_params(fn_node: Any, src: bytes) -> list[dict]:
    params_node = fn_node.child_by_field_name("parameters")
    if not params_node:
        return []
    params: list[dict] = []
    for p in params_node.children:
        t = p.type
        if t in ("identifier",):
            name = _text(p, src).lstrip("*&")
            if name:
                params.append({"name": name})
        elif t == "optional_parameter":
            name_n = p.child_by_field_name("name")
            if name_n:
                params.append({"name": _text(name_n, src), "default": True})
        elif t in ("splat_parameter", "hash_splat_parameter", "block_parameter"):
            # *args, **kwargs, &block
            inner = p.children[-1] if p.children else None
            if inner and inner.type == "identifier":
                prefix = (
                    "**"
                    if t == "hash_splat_parameter"
                    else ("&" if t == "block_parameter" else "*")
                )
                params.append({"name": prefix + _text(inner, src)})
        elif t == "keyword_parameter":
            name_n = p.child_by_field_name("name")
            if name_n:
                params.append({"name": _text(name_n, src) + ":", "keyword": True})
    return params


def _extract_doc_comment(node: Any, src: bytes) -> str:
    """Extract # comment lines immediately preceding a method/class."""
    start = node.start_byte
    preceding = src[max(0, start - 400):start].decode("utf-8", errors="replace")
    lines = preceding.rstrip().splitlines()
    doc_lines: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            doc_lines.insert(0, stripped[1:].strip())
        else:
            break
    return " ".join(doc_lines)[:200] if doc_lines else ""


def _complexity(fn_node: Any) -> int:
    return 1 + len(_collect(fn_node, _BRANCH_TYPES))


def _extract_bases(cls_node: Any, src: bytes) -> list[str]:
    """Ruby: class Foo < Bar — superclass is the `superclass` field."""
    super_n = cls_node.child_by_field_name("superclass")
    if not super_n:
        return []
    name = _text(super_n, src).lstrip("< ").strip()
    return [name] if name else []


def _count_methods(cls_node: Any) -> int:
    return len(_collect(cls_node, _METHOD_TYPES))


def _file_node(file_id: str, loc: int) -> dict[str, Any]:
    return {"id": file_id, "label": "File",
            "properties": {"path": file_id, "language": "ruby", "loc": loc}}


class RubyParser(BaseParser):
    language = "ruby"

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
            log.warning("ruby_parse_read_error", file=fid, error=str(e))
            result.nodes.append(_file_node(fid, 0))
            return result

        loc = src.count(b"\n") + 1
        result.nodes.append(_file_node(fid, loc))

        try:
            import tree_sitter_ruby as tsruby
            from tree_sitter import Language, Parser
            tree = Parser(Language(tsruby.language())).parse(src)
        except Exception as e:
            log.warning("ruby_parse_failed", file=fid, error=str(e))
            return result

        root = tree.root_node
        fn_id_map: dict[int, str] = {}

        # ── Classes and modules ───────────────────────────────────────────────
        for cls in _collect(root, _CLASS_TYPES):
            nn = cls.child_by_field_name("name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            bases = _extract_bases(cls, src)
            line_s = cls.start_point[0] + 1
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": "ruby",
                "kind": cls.type,
                "line_start": line_s, "line_end": cls.end_point[0] + 1,
                "line": line_s,
                "is_public": not name.startswith("_"),
                "bases": bases,
                "decorators": [],
                "docstring": _extract_doc_comment(cls, src),
                "method_count": _count_methods(cls),
            }})
            for base in bases:
                result.edges.append({"source": nid, "target": base,
                                     "type": "INHERITS", "properties": {}})

        # ── Methods ───────────────────────────────────────────────────────────
        for fn in _collect(root, _METHOD_TYPES):
            bare = _method_name(fn, src)
            if not bare:
                continue
            if fn.type == "singleton_method":
                obj_node = fn.child_by_field_name("object")
                receiver = _text(obj_node, src) if obj_node else "self"
                qual = f"{receiver}.{bare}"
            else:
                enc_cls = _enclosing_class(fn)
                if enc_cls:
                    cnn = enc_cls.child_by_field_name("name")
                    qual = f"{_text(cnn, src)}.{bare}" if cnn else bare
                else:
                    qual = bare
            nid = f"{fid}::{qual}"
            fn_id_map[fn.id] = nid
            line_s = fn.start_point[0] + 1
            line_e = fn.end_point[0] + 1
            result.nodes.append({"id": nid, "label": "Function", "properties": {
                "name": qual, "file": fid, "language": "ruby",
                "is_singleton": fn.type == "singleton_method",
                "line_start": line_s, "line_end": line_e,
                "line": line_s,
                "loc": line_e - line_s + 1,
                "is_public": not bare.startswith("_"),
                "parameters": _extract_params(fn, src),
                "return_type": "",
                "decorators": [],
                "docstring": _extract_doc_comment(fn, src),
                "complexity": _complexity(fn),
            }})

        # ── require / require_relative → IMPORTS edges ────────────────────────
        for call in _collect(root, {"call"}):
            method_node = call.child_by_field_name("method")
            if not method_node:
                continue
            method_name = _text(method_node, src)
            if method_name not in ("require", "require_relative"):
                continue
            args_node = call.child_by_field_name("arguments")
            if not args_node:
                continue
            for ch in args_node.children:
                if ch.type in ("string", "simple_string"):
                    raw = _text(ch, src).strip().strip("'\"")
                    if raw:
                        result.edges.append({"source": fid, "target": raw,
                                             "type": "IMPORTS", "properties": {
                                                 "require_type": method_name}})

        # ── Generic calls → CALLS edges ───────────────────────────────────────
        for call in _collect(root, {"call"}):
            method_node = call.child_by_field_name("method")
            if not method_node:
                continue
            callee_name = _text(method_node, src).strip()
            if callee_name in ("require", "require_relative"):
                continue
            receiver_node = call.child_by_field_name("receiver")
            callee = (
                f"{_text(receiver_node, src).strip()}.{callee_name}"
                if receiver_node
                else callee_name
            )
            if not callee:
                continue
            enc = _enclosing_fn(call)
            src_id = fn_id_map.get(enc.id, fid) if enc else fid
            result.edges.append({"source": src_id, "target": callee,
                                  "type": "CALLS", "properties": {}})

        log.info("ruby_parse_done", file=fid, nodes=len(result.nodes), edges=len(result.edges))
        return result
