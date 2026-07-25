"""jsat._parsers.java — Java AST extractor using tree-sitter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

_METHOD_TYPES = {"method_declaration", "constructor_declaration"}


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

        # Classes
        for cls in _collect(root, {"class_declaration"}):
            nn = cls.child_by_field_name("name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": "java",
                "line_start": cls.start_point[0] + 1, "line_end": cls.end_point[0] + 1,
                "is_public": name[0].isupper(),
            }})

        # Methods and constructors
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
            result.nodes.append({"id": nid, "label": "Function", "properties": {
                "name": qual, "file": fid, "language": "java",
                "line_start": fn.start_point[0] + 1, "line_end": fn.end_point[0] + 1,
                "is_constructor": fn.type == "constructor_declaration",
                "is_public": bare[0].isupper(),
            }})

        # import_declaration → IMPORTS edges
        # tree-sitter-java represents `import foo.bar.Baz;` as an import_declaration
        # whose text is the full `import foo.bar.Baz;` string.
        for imp in _collect(root, {"import_declaration"}):
            # Children: "import" keyword, dotted name, optional "*", ";"
            # Walk children to collect the dotted-name text.
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

        # method_invocation → CALLS edges
        for call in _collect(root, {"method_invocation"}):
            # tree-sitter-java: field "name" holds the callee method name;
            # field "object" (if present) is the receiver expression.
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
