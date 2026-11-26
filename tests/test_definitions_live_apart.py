"""実装のファイルに定数・型を置かない。定数は同じ値を 2 か所に置かない（init の雛形）。

- 実装のファイル（最上位に関数かクラスがあるファイル）は、最上位で大文字の名前へ代入しない。
  定数は同じディレクトリの `constants.py`、
  型（dataclass・例外・列挙・メソッドの無いクラス・型の別名）は
  `types.py` へ置き、実装は `from .constants import …` で読む。
- 定数・型のファイルどうしで、同じ値（字面が同じ式）の定数を 2 か所に書かない
  （片方だけ直ってずれる）。

なぜ・どう分けるかの正本は code-complexity-audit スキルの §3.7。
検出の関数（`_is_constant`〜`types_in`）は
claude-config の tests/test_definitions_live_apart.py と同じ字面で、一致を claude-config の
tests/test_definitions_template_parity.py が固定する（片方だけ直さない）。

コピー後に直すのは `PACKAGES`・`ALLOWED_MIXED`・`MIN_FILES` だけ。
新規プロジェクトは `ALLOWED_MIXED` を空のまま使う。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 測るパッケージ（ROOT からの glob。配下を再帰で見る）
PACKAGES = ("src/*",)
#: 途中導入のときだけ: 混在を黙認するファイル → 理由。直したら行を消す（直っているのに残ると落ちる）
ALLOWED_MIXED: dict[str, str] = {
    "src/reshog/models.py": (
        "型の置き場は models.py として既にある（tests/test_structure.py もそう呼ぶ）。"
        "types.py への改名は全 import とテストに及ぶので別の作業"
    ),
}
#: 実装のファイルの下限（走査が壊れて 0 本になったら落とす。導入時の本数の 8 割ほど）
MIN_FILES = 12  # 実測 15 本（models.py を含み、constants.py と __init__.py を除く）の 8 割

#: 定義を置くファイル（ここに定数・型があるのは正しい）
DEFINITION_FILES = ("constants.py", "types.py")
#: 型とみなす基底クラス（末尾の名前で見る）
TYPE_BASES = ("TypedDict", "Enum", "IntEnum", "StrEnum", "NamedTuple", "BaseModel", "Exception")
#: 同じ値とみなす式の最短の長さ（短い値（0・"" 等）は偶然一致するので見ない）
MIN_VALUE_CHARS = 12
#: 型の別名の右辺に現れる、型を作る名前（`dict[str, Any]`・`Optional[int]` 等）
ALIAS_HEADS = ("dict", "list", "tuple", "set", "frozenset", "type", "Dict", "List", "Tuple", "Set",
               "Optional", "Union", "Callable", "Literal", "Mapping", "Sequence", "Iterable",
               "Iterator")


def _is_constant(name: str) -> bool:
    core = name.strip("_")
    return (bool(core) and core.isupper() and any(c.isalpha() for c in core)
            and not name.startswith("__"))


def _stores(node: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]


def constants_in(tree: ast.Module) -> list[str]:
    """最上位（最上位の try・if・with の中を含む。
    `if __name__ == ...` は除く）で代入する大文字の名前。"""
    found = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            found += [n for n in _stores(node) if _is_constant(n)]
        elif isinstance(node, ast.ClassDef) and node.name not in types_in(
            ast.Module(body=[node], type_ignores=[])
        ):
            # 振る舞いを持つクラスの属性に置いた大文字の名前も定数（クラスへ移して検査を逃れない）
            found += [f"{node.name}.{n}" for x in node.body
                      if isinstance(x, (ast.Assign, ast.AnnAssign))
                      for n in _stores(x) if _is_constant(n)]
        elif isinstance(node, (ast.Try, ast.If, ast.With)):
            if isinstance(node, ast.If) and "__name__" in ast.unparse(node.test):
                continue
            found += [n for n in _stores(node) if _is_constant(n)]
    return found


def _is_type_alias(node: ast.stmt) -> bool:
    if isinstance(node, ast.AnnAssign) and "TypeAlias" in ast.unparse(node.annotation):
        return True
    return (isinstance(node, ast.Assign) and isinstance(node.value, ast.Subscript)
            and ast.unparse(node.value.value).split(".")[-1] in ALIAS_HEADS)


def types_in(tree: ast.Module) -> list[str]:
    """型: dataclass・型の基底を持つ・メソッドが 1 つも無いクラスと、型の別名。"""
    found = [n for node in tree.body if _is_type_alias(node) for n in _stores(node)]
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        decorators = [ast.unparse(d) for d in node.decorator_list]
        bases = [ast.unparse(b).split(".")[-1] for b in node.bases]
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if (any("dataclass" in d for d in decorators)
                or any(b in TYPE_BASES or b.endswith("Error") for b in bases)
                or not methods):
            found.append(node.name)
    return found


def _package_files() -> list[Path]:
    files: list[Path] = []
    for pattern in PACKAGES:
        for pkg in sorted(ROOT.glob(pattern)):
            if pkg.is_dir():
                files += [p for p in sorted(pkg.rglob("*.py")) if "__pycache__" not in p.parts]
    return files


def implementation_files() -> list[Path]:
    files = []
    for path in _package_files():
        if (path.name == "__init__.py" or path.name in DEFINITION_FILES
                or path.name.startswith("test_")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               for n in tree.body):
            files.append(path)
    return files


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    if consts := constants_in(tree):
        out.append(f"定数 {consts} → {path.parent.relative_to(ROOT).as_posix()}/constants.py")
    if kinds := types_in(tree):
        out.append(f"型 {kinds} → {path.parent.relative_to(ROOT).as_posix()}/types.py")
    return out


def test_implementation_files_hold_no_constants_or_types() -> None:
    files = implementation_files()
    assert len(files) >= MIN_FILES, f"走査対象が {len(files)} 本しかない（PACKAGES を確かめる）"
    bad = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel not in ALLOWED_MIXED:
            bad += [f"{rel}: {v}" for v in _violations(path)]
    assert not bad, "実装のファイルに定数・型がある（置き場所へ移す）:\n  " + "\n  ".join(bad)


def test_allowed_mixed_is_not_stale() -> None:
    """黙認の行は、実在して、まだ混在しているものだけ（直ったのに残すと、また混ぜても通る）。"""
    stale = [rel for rel in ALLOWED_MIXED
             if not (ROOT / rel).is_file() or not _violations(ROOT / rel)]
    assert not stale, f"ALLOWED_MIXED から消す行: {stale}"


def test_the_same_constant_value_is_not_written_twice() -> None:
    seen: dict[str, list[str]] = {}
    for path in _package_files():
        if path.name not in DEFINITION_FILES:
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                value = ast.unparse(node.value)
                if len(value) >= MIN_VALUE_CHARS:
                    seen.setdefault(value, []).append(
                        f"{path.relative_to(ROOT).as_posix()}:{_stores(node)}"
                    )
    dups = {v: where for v, where in seen.items() if len({w.split(":")[0] for w in where}) >= 2}
    assert not dups, (
        "同じ値の定数が 2 か所以上にある（正本を 1 つ決めて import する）:\n  "
        + "\n  ".join(f"{v[:60]!r}: {where}" for v, where in dups.items()))


def test_detectors_fire() -> None:
    """陽性対照: 検出器が壊れて常に通る状態でないこと。"""
    impl = ast.parse(
        "import re\nLIMIT = 60\n_RE = re.compile('x')\ntry:\n    import rich\n    HAS_RICH = True\n"
        "except ImportError:\n    HAS_RICH = False\n"
        "from dataclasses import dataclass\n@dataclass\nclass Job:\n    name: str\n"
        "class Oops(RuntimeError):\n    pass\n"
        "class Plain:\n    x = 1\nclass Behaves:\n    def run(self):\n        return 1\n"
        "def f():\n    LOCAL = 1\n    return LOCAL\n"
        "if __name__ == '__main__':\n    MAIN = 1\n")
    assert sorted(constants_in(impl)) == ["HAS_RICH", "HAS_RICH", "LIMIT", "_RE"]
    assert types_in(impl) == ["Job", "Oops", "Plain"]
    extra = ast.parse("from typing import Any\nEntry = dict[str, Any]\nfirst = items[0]\n"
                      "class Guard:\n    LIMIT = 60\n    def run(self):\n"
                      "        return self.LIMIT\n")
    # 型の別名。添字の取り出し（items[0]）は拾わない
    assert types_in(extra) == ["Entry"]
    assert constants_in(extra) == ["Guard.LIMIT"]
