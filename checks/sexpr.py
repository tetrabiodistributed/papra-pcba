"""Tiny s-expression reader for KiCad files. Returns nested lists; atoms are str,
quoted strings are str (unquoted), numbers stay str so callers decide the type."""
from __future__ import annotations

from pathlib import Path


def parse(text: str) -> list:
    i, n = 0, len(text)
    stack: list[list] = [[]]
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "(":
            stack.append([])
            i += 1
        elif c == ")":
            done = stack.pop()
            stack[-1].append(done)
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while text[j] != '"':
                if text[j] == "\\":
                    j += 1
                buf.append(text[j])
                j += 1
            stack[-1].append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            stack[-1].append(text[i:j])
            i = j
    return stack[0][0]


def load(path: Path) -> list:
    return parse(path.read_text())


def children(node: list, tag: str):
    """All direct children of `node` whose head atom is `tag`."""
    for c in node:
        if isinstance(c, list) and c and c[0] == tag:
            yield c


def child(node: list, tag: str, default=None):
    return next(children(node, tag), default)


def prop(node: list, name: str, default: str = "") -> str:
    for p in children(node, "property"):
        if len(p) >= 3 and p[1] == name:
            return p[2]
    return default
