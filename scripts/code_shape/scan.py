"""測る対象のファイルを集め、ファイルごとの形を組み立てる。"""

from __future__ import annotations

from pathlib import Path

from .constants import (
    EXTENSIONS,
    KINDS,
    ROOT,
    SKIP,
    TARGETS,
    TEST_CASE,
    TEST_DIRS,
    TEST_TARGETS,
    TOP_LEVEL,
)
from .dir_shape import measure_dirs
from .js.shape import measure_js
from .py_shape import measure_python


def is_test(path: Path) -> bool:
    """テストのファイルか（code-complexity-audit の点検と同じ規則。
    揃っていることは claude-config が固定する）。"""
    n = path.name
    return (n.startswith("test_") or n.split(".", 1)[0].endswith("_test")
            or ".test." in n or ".spec." in n
            or bool(TEST_DIRS & set(path.parts)))


def _walk(root: Path, dirs: tuple[str, ...]) -> list[Path]:
    files = {p for d in dirs if (root / d).is_dir() for p in (root / d).rglob("*")
             if p.suffix in EXTENSIONS and p.is_file()}
    return sorted(p for p in files if not SKIP & set(p.relative_to(root).parts))


def is_test_file(rel: Path) -> bool:
    """行数と補助関数だけ測るテストのファイルか。TEST_TARGETS の置き場の下は名前を問わず全部
    （conftest・ヘルパーも。is_test の名前の規則に合わない置き場名でも漏らさない）。"""
    path = rel.as_posix()
    return is_test(rel) or any(path.startswith(d.rstrip("/") + "/") for d in TEST_TARGETS)


def targets(root: Path = ROOT) -> list[Path]:
    """実装のファイル（全部の指標を測る）。"""
    return [p for p in _walk(root, TARGETS) if not is_test_file(p.relative_to(root))]


def targets_of_tests(root: Path = ROOT) -> list[Path]:
    """テストのファイル（行数と補助関数だけ測る）。実装の置き場に併置したテストも含む。"""
    return [p for p in _walk(root, (*TARGETS, *TEST_TARGETS)) if is_test_file(p.relative_to(root))]


def _read(path: Path) -> tuple[int, dict] | None:
    """測った形。読めない（utf-8 でない・読み出せない・括弧の対応が取れない）なら None。"""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return measure_python(src) if path.suffix == ".py" else measure_js(src)


def _record(shape: dict[str, dict[str, int]], root: Path, path: Path, *, is_impl: bool) -> None:
    """1 ファイルを測って shape に足す。読めなければ unreadable に数える（黙って外さない）。

    実装は全部の指標を測る。テストは行数と、テストケースでない関数（検査ロジックの補助）の
    長さ・複雑度だけ（ケースと、本体を含む <top-level> は除く。本数と粒度は測らない）。"""
    got = _read(path)
    rel = path.relative_to(root).as_posix()
    if got is None:
        shape["unreadable"][rel] = 1
        return
    exec_lines, funcs = got
    shape["files"][rel] = exec_lines
    if is_impl:
        shape["per_file"][rel] = len(funcs) - (TOP_LEVEL in funcs)
    for name, (lines, complexity) in funcs.items():
        if is_impl or (name != TOP_LEVEL and not TEST_CASE.search(name)):
            shape["functions"][f"{rel}::{name}"] = lines
            shape["complexity"][f"{rel}::{name}"] = complexity


def measure(root: Path = ROOT) -> dict[str, dict[str, int]]:
    """KINDS ごとの {鍵: 値} と、読めなかったファイルの unreadable
    （{パス: 1}。黙って外さず数える）。"""
    shape: dict[str, dict[str, int]] = {k: {} for k in (*KINDS, "unreadable")}
    paths = targets(root)
    for path in paths:
        _record(shape, root, path, is_impl=True)
    for path in targets_of_tests(root):
        _record(shape, root, path, is_impl=False)
    # 読めなかったファイルも置き場には在るので、粒度には数える（テストは粒度に数えない）
    shape.update(measure_dirs([p.relative_to(root).as_posix() for p in paths]))
    return shape
