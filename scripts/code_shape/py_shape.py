"""Python の「形」を測る（標準ライブラリの ast・tokenize）。scan.py から呼ばれる。"""

from __future__ import annotations

import ast
import io
import tokenize

from .constants import PY_BRANCH


def _py_exec_lines(src: str, tree: ast.Module) -> int:
    doc = 0
    for node in ast.walk(tree):
        holds = isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if holds and node.body and ast.get_docstring(node, clean=False):
            first = node.body[0]
            doc += (first.end_lineno or first.lineno) - first.lineno + 1
    comment = blank = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                comment += 1
            elif tok.type == tokenize.NL and not tok.line.strip():
                blank += 1
    except (tokenize.TokenError, IndentationError):
        pass
    return max(0, src.count("\n") - doc - comment - blank)


def _py_complexity(node: ast.AST) -> int:
    score = 1

    def walk(current: ast.AST) -> None:
        nonlocal score
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # 入れ子の関数は、その関数自身が別に 1 本として数えられる
            if isinstance(child, PY_BRANCH):
                score += 1
            elif isinstance(child, ast.BoolOp):
                score += len(child.values) - 1
            # match 文は 3.10 から。無い版では現れない
            elif isinstance(child, getattr(ast, "Match", ())):
                score += len(child.cases)
            walk(child)

    walk(node)
    return score


def _py_body_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    body = node.body[1:] if ast.get_docstring(node, clean=False) is not None else node.body
    return (body[-1].end_lineno or body[-1].lineno) - body[0].lineno + 1 if body else 0


def measure_python(src: str) -> tuple[int, dict[str, tuple[int, int]]] | None:
    """(実行行, {関数名: (中身の行数, 複雑度)})。構文として読めなければ None。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    funcs: dict[str, tuple[int, int]] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                if not isinstance(child, ast.ClassDef):
                    funcs[qual] = (_py_body_lines(child), _py_complexity(child))
                walk(child, qual)
            else:
                walk(child, prefix)

    walk(tree, "")
    return _py_exec_lines(src, tree), funcs
