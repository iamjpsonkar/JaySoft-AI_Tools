"""jsat._parsers.java — Java AST extractor using tree-sitter.

Extracts per-method: parameters (name+type), return_type, annotations,
cyclomatic complexity, loc, line alias, is_public (modifier-based).
Extracts per-class: bases (superclass + interfaces), annotations, method_count, line alias.
New edges: INHERITS (class→superclass), IMPLEMENTS (class→interface).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

_METHOD_TYPES = {"method_declaration", "constructor_declaration"}

_BRANCH_TYPES = {
    "if_statement", "for_statement", "enhanced_for_statement", "while_statement",
    "do_statement", "catch_clause", "switch_expression", "switch_label",
    "conditional_expression", "instanceof_expression",
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
        if cur.type == "class_declaration":
            return cur
        cur = cur.parent
    return None


def _has_modifier(node: Any, src: bytes, modifier: str) -> bool:
    mods = node.child_by_field_name("modifiers")
    if not mods:
        return False
    return modifier in _text(mods, src)


def _extract_params(fn_node: Any, src: bytes) -> list[dict]:
    params_node = fn_node.child_by_field_name("parameters")
    if not params_node:
        return []
    params: list[dict] = []
    for p in _collect(params_node, {"formal_parameter", "spread_parameter"}):
        type_n = p.child_by_field_name("type")
        name_n = p.child_by_field_name("name")
        entry: dict = {"name": _text(name_n, src) if name_n else "?"}
        if type_n:
            entry["type"] = _text(type_n, src)
        params.append(entry)
    return params


def _extract_return_type(fn_node: Any, src: bytes) -> str:
    type_n = fn_node.child_by_field_name("type")
    return _text(type_n, src).strip() if type_n else ""


def _extract_annotations(node: Any, src: bytes) -> list[str]:
    """Extract @Annotation names preceding a method/class declaration."""
    mods = node.child_by_field_name("modifiers")
    if not mods:
        return []
    anns: list[str] = []
    for ch in mods.children:
        if ch.type in ("annotation", "marker_annotation"):
            ann_n = ch.child_by_field_name("name") or (ch.children[1] if len(ch.children) > 1 else None)
            if ann_n:
                anns.append(_text(ann_n, src).strip())
    return anns


def _extract_docstring(node: Any, src: bytes) -> str:
    """Extract Javadoc comment immediately before the node."""
    start = node.start_byte
    preceding = src[max(0, start - 600):start].decode("utf-8", errors="replace")
    lines = preceding.strip().splitlines()
    doc_lines: list[str] = []
    in_doc = False
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.endswith("*/"):
            in_doc = True
        if in_doc:
            content = stripped.lstrip("/*").strip()
            if content and not content.startswith("@"):
                doc_lines.insert(0, content)
        if stripped.startswith("/**"):
            break
    if doc_lines:
        return " ".join(doc_lines)[:200]
    return ""


def _complexity(fn_node: Any) -> int:
    body = fn_node.child_by_field_name("body")
    if not body:
        return 1
    return 1 + len(_collect(body, _BRANCH_TYPES))


def _extract_bases(cls_node: Any, src: bytes) -> list[str]:
    bases: list[str] = []
    super_n = cls_node.child_by_field_name("superclass")
    if super_n:
        for ch in super_n.children:
            if ch.type in ("type_identifier", "generic_type"):
                bases.append(_text(ch, src).strip())
    return bases


def _extract_interfaces(cls_node: Any, src: bytes) -> list[str]:
    ifaces: list[str] = []
    interfaces_n = cls_node.child_by_field_name("interfaces")
    if interfaces_n:
        for ch in interfaces_n.children:
            if ch.type in ("type_identifier", "generic_type"):
                ifaces.append(_text(ch, src).strip())
    return ifaces


def _count_methods(cls_node: Any) -> int:
    body = cls_node.child_by_field_name("body")
    if not body:
        return 0
    return sum(1 for ch in _collect(body, _METHOD_TYPES))


def _file_node(file_id: str, loc: int) -> dict[str, Any]:
    return {"id": file_id, "label": "File",
            "properties": {"path": file_id, "language": "java", "loc": loc}}


class JavaParser(BaseParser):
    language = "java"

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
            log.warning("java_parse_read_error", file=fid, error=str(e))
            result.nodes.append(_file_node(fid, 0))
            return result

        loc = src.count(b"\n") + 1
        result.nodes.append(_file_node(fid, loc))

        try:
            import tree_sitter_java as tsjava
            from tree_sitter import Language, Parser
            tree = Parser(Language(tsjava.language())).parse(src)
        except Exception as e:
            log.warning("java_parse_failed", file=fid, error=str(e))
            return result

        root = tree.root_node
        fn_id_map: dict[int, str] = {}

        # ── Classes ───────────────────────────────────────────────────────────
        for cls in _collect(root, {"class_declaration"}):
            nn = cls.child_by_field_name("name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            bases = _extract_bases(cls, src)
            interfaces = _extract_interfaces(cls, src)
            line_s = cls.start_point[0] + 1
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": "java",
                "line_start": line_s, "line_end": cls.end_point[0] + 1,
                "line": line_s,
                "is_public": _has_modifier(cls, src, "public"),
                "bases": bases,
                "interfaces": interfaces,
                "decorators": _extract_annotations(cls, src),
                "docstring": _extract_docstring(cls, src),
                "method_count": _count_methods(cls),
            }})
            for base in bases:
                result.edges.append({"source": nid, "target": base,
                                     "type": "INHERITS", "properties": {}})
            for iface in interfaces:
                result.edges.append({"source": nid, "target": iface,
                                     "type": "IMPLEMENTS", "properties": {}})

        # ── Methods and constructors ──────────────────────────────────────────
        for fn in _collect(root, _METHOD_TYPES):
            nn = fn.child_by_field_name("name")
            if not nn:
                continue
            bare = _text(nn, src)
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
                "name": qual, "file": fid, "language": "java",
                "line_start": line_s, "line_end": line_e,
                "line": line_s,
                "loc": line_e - line_s + 1,
                "is_constructor": fn.type == "constructor_declaration",
                "is_public": _has_modifier(fn, src, "public"),
                "parameters": _extract_params(fn, src),
                "return_type": _extract_return_type(fn, src),
                "decorators": _extract_annotations(fn, src),
                "docstring": _extract_docstring(fn, src),
                "complexity": _complexity(fn),
            }})

        # ── import_declaration → IMPORTS edges ────────────────────────────────
        for imp in _collect(root, {"import_declaration"}):
            parts: list[str] = []
            for ch in imp.children:
                if ch.type in ("identifier", "scoped_identifier"):
                    parts.append(_text(ch, src).strip())
                elif ch.type == "asterisk":
                    parts.append("*")
            target = ".".join(parts) if parts else _text(imp, src).strip().removeprefix("import ").rstrip(";").strip()
            if target:
                result.edges.append({"source": fid, "target": target,
                                     "type": "IMPORTS", "properties": {}})

        # ── method_invocation → CALLS edges ──────────────────────────────────
        for call in _collect(root, {"method_invocation"}):
            name_node = call.child_by_field_name("name")
            if not name_node:
                continue
            callee = _text(name_node, src).strip()
            obj_node = call.child_by_field_name("object")
            if obj_node:
                callee = f"{_text(obj_node, src).strip()}.{callee}"
            if not callee:
                continue
            enc = _enclosing_fn(call)
            src_id = fn_id_map.get(enc.id, fid) if enc else fid
            result.edges.append({"source": src_id, "target": callee,
                                  "type": "CALLS", "properties": {}})

        log.info("java_parse_done", file=fid, nodes=len(result.nodes), edges=len(result.edges))
        return result
