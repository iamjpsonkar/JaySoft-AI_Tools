"""jsat._parsers.ruby — Ruby AST extractor using tree-sitter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jsat._parsers import BaseParser, ParseResult

# tree-sitter-ruby uses "method" for instance methods and
# "singleton_method" for `def self.foo` / `def ClassName.foo`.
_METHOD_TYPES = {"method", "singleton_method"}
_CLASS_TYPES = {"class", "module"}


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


def _file_node(file_id: str, loc: int) -> dict[str, Any]:
    return {"id": file_id, "label": "File",
            "properties": {"path": file_id, "language": "ruby", "loc": loc}}


def _method_name(fn: Any, src: bytes) -> str | None:
    """Return the bare method name from a method or singleton_method node.

    For singleton_method (`def self.foo`) tree-sitter-ruby places the method
    name in the "name" field.  The receiver ("self" or a constant) is in the
    "object" field.  We return just the name part; the caller decides how to
    qualify it.
    """
    nn = fn.child_by_field_name("name")
    return _text(nn, src) if nn else None


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

        # Classes and modules
        for cls in _collect(root, _CLASS_TYPES):
            nn = cls.child_by_field_name("name")
            if not nn:
                continue
            name = _text(nn, src)
            nid = f"{fid}::{name}"
            result.nodes.append({"id": nid, "label": "Class", "properties": {
                "name": name, "file": fid, "language": "ruby",
                "kind": cls.type,  # "class" or "module"
                "line_start": cls.start_point[0] + 1, "line_end": cls.end_point[0] + 1,
                "is_public": not name.startswith("_"),
            }})

        # Methods (instance) and singleton methods (def self.foo)
        for fn in _collect(root, _METHOD_TYPES):
            bare = _method_name(fn, src)
            if not bare:
                continue

            if fn.type == "singleton_method":
                # Qualify with the receiver object (e.g. "self" or "ClassName")
                obj_node = fn.child_by_field_name("object")
                receiver = _text(obj_node, src) if obj_node else "self"
                qual = f"{receiver}.{bare}"
            else:
                # Instance method — qualify with enclosing class/module if any
                enc_cls = _enclosing_class(fn)
                if enc_cls:
                    cnn = enc_cls.child_by_field_name("name")
                    qual = f"{_text(cnn, src)}.{bare}" if cnn else bare
                else:
                    qual = bare

            nid = f"{fid}::{qual}"
            fn_id_map[fn.id] = nid
            result.nodes.append({"id": nid, "label": "Function", "properties": {
                "name": qual, "file": fid, "language": "ruby",
                "is_singleton": fn.type == "singleton_method",
                "line_start": fn.start_point[0] + 1, "line_end": fn.end_point[0] + 1,
                # Ruby convention: methods starting with _ are private/internal.
                "is_public": not bare.startswith("_"),
            }})

        # require / require_relative → IMPORTS edges
        # In tree-sitter-ruby these appear as "call" nodes whose method name
        # is an identifier with text "require" or "require_relative".
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
            # The argument list wraps the string literal(s).
            for ch in args_node.children:
                if ch.type in ("string", "simple_string"):
                    # Strip surrounding quotes from the string content.
                    raw = _text(ch, src).strip().strip("'\"")
                    if raw:
                        result.edges.append({"source": fid, "target": raw,
                                             "type": "IMPORTS", "properties": {
                                                 "require_type": method_name,
                                             }})

        # Generic method calls → CALLS edges
        # tree-sitter-ruby "call" nodes cover `obj.method(args)` as well as
        # bare `method(args)` invocations.
        for call in _collect(root, {"call"}):
            method_node = call.child_by_field_name("method")
            if not method_node:
                continue
            callee_name = _text(method_node, src).strip()
            # Skip require/require_relative — already handled as IMPORTS.
            if callee_name in ("require", "require_relative"):
                continue
            receiver_node = call.child_by_field_name("receiver")
            if receiver_node:
                callee = f"{_text(receiver_node, src).strip()}.{callee_name}"
            else:
                callee = callee_name
            if not callee:
                continue
            enc = _enclosing_fn(call)
            src_id = fn_id_map.get(enc.id, fid) if enc else fid
            result.edges.append({"source": src_id, "target": callee,
                                  "type": "CALLS", "properties": {}})

        log.info("ruby_parse_done", file=fid, nodes=len(result.nodes), edges=len(result.edges))
        return result
