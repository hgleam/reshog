"""副作用（外部プロセス・ネットワーク・ファイルの書き換え）を持てるファイルを、
表で決めて固定する（init の雛形）。

仕様書の「層と副作用」の表に「副作用なし」と書いたファイルが、いつの間にかファイルを書き換える——
宣言と実装のずれは、宣言だけでは必ず起きる（python-conventions「層分割と副作用」）。
ここで表を機械で守る。

- `SIDE_EFFECT_MODULES`: 副作用のモジュール → それを import してよいファイル
- `FILE_WRITERS`: ファイルを書き換える呼び出し
  （`write_text`・`unlink`・`os.link`・書き込みの `open` 等）を持ってよいファイル
- 表に無いファイルで見つかったら落ちる。表に載っているのに使っていない行も落ちる
  （直したのに残すと、また足しても通る）
- 表は空のままでは落ちる（雛形のまま入れて、何も守らない門にしない）

コピー後に直すのは `PACKAGES`・`SIDE_EFFECT_MODULES`・`FILE_WRITERS` だけ。
仕様書の表と同じ内容にする。

拾えないもの: `Path.replace`・`Path.rename`（`str.replace` と構文で区別できない）、
`os.open` のフラグでの書き込み・
`os.chmod`・`os.system` 等の `WRITE_FUNCTIONS` に無い関数、関数を変数へ入れてから呼ぶ形、
サブモジュールの別名（`import os.path as o`）経由の呼び出し、`open` のモードを変数で渡す形、
`[rwxabt+]` の外の文字を含むモード（`tarfile.open(p, 'w:gz')`・`dbm.open(p, 'c')`）。
逆に、モードの文字だけでできたファイル名（`Image.open('a')`）は書き込みと取り違える。
`subprocess` 等を読む第三者ライブラリ経由の副作用。
別名（`import os as o`・`from os import link as l`）は解決して拾う。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 測るパッケージ（ROOT からの glob。配下を再帰で見る）
PACKAGES = ("src/*",)
#: 副作用のモジュール → import してよいファイル（ROOT からの相対パス）。
#: 例: {"subprocess": {"src/pkg/ffmpeg.py"}}
SIDE_EFFECT_MODULES: dict[str, set[str]] = {
    "subprocess": {"src/reshog/collect.py"},
    "urllib.request": {"src/reshog/collect.py"},
}
#: ファイルを書き換えてよいファイル（ROOT からの相対パス）
FILE_WRITERS: set[str] = {"src/reshog/report.py"}

#: メソッドの名前だけで、ファイルを書き換えるとみなすもの（Path 等）
WRITE_METHODS = ("write_text", "write_bytes", "unlink", "touch", "mkdir", "rmdir", "symlink_to",
                 "hardlink_to")
#: 関数の完全な名前で、ファイルを書き換えるもの
#: （`import os as o`・`from shutil import move` も解決して当てる）
WRITE_FUNCTIONS = frozenset(
    [f"os.{n}" for n in ("replace", "link", "rename", "renames", "remove", "unlink", "makedirs",
                         "mkdir", "rmdir", "removedirs", "symlink", "truncate")]
    + [f"shutil.{n}" for n in ("move", "copy", "copy2", "copyfile", "copytree", "rmtree")])
#: open のモードとみなす文字列（モードの文字だけでできた短いもの。パス・URL を取り違えない）
MODE_PATTERN = re.compile(r"[rwxabt+]{1,4}")
#: そのうち書き込みを表す文字
WRITE_MODE_CHARS = ("w", "a", "x", "+")


def imported_modules(tree: ast.Module) -> set[str]:
    """import しているモジュールの完全な名前（相対 import は見ない）。

    `from urllib import request` は `urllib` と `urllib.request` の両方を入れる
    （どちらも読みうる）。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names |= {f"{node.module}.{alias.name}" for alias in node.names}
    return names


def uses_module(names: set[str], module: str) -> bool:
    """表の名前 module そのものか、その下のモジュールを読んでいるか
    （`urllib.request` は `urllib.parse` に当たらない）。"""
    return any(n == module or n.startswith(module + ".") for n in names)


def _bindings(tree: ast.Module) -> dict[str, str]:
    """ファイルの中の名前 → 完全な名前
    （`import os as o` → o: os、`from os import link as l` → l: os.link）。"""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {(a.asname or a.name.split(".")[0]):
                    (a.name if a.asname else a.name.split(".")[0])
                    for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out |= {(a.asname or a.name): f"{node.module}.{a.name}" for a in node.names}
    return out


def _full_name(func: ast.expr, bindings: dict[str, str]) -> str:
    if isinstance(func, ast.Name):
        return bindings.get(func.id, func.id)
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{bindings.get(func.value.id, func.value.id)}.{func.attr}"
    return ""


def _writes_by_mode(node: ast.Call, mode_index: int) -> bool:
    mode = node.args[mode_index] if len(node.args) > mode_index else next(
        (k.value for k in node.keywords if k.arg == "mode"), None)
    return (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
            and bool(MODE_PATTERN.fullmatch(mode.value))
            and any(c in mode.value for c in WRITE_MODE_CHARS))


def file_writes(tree: ast.Module) -> list[str]:
    """ファイルを書き換える呼び出し（行番号つき）。"""
    bindings = _bindings(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func, full = node.func, _full_name(node.func, bindings)
        if full in WRITE_FUNCTIONS:
            found.append(f"{full}:{node.lineno}")
        elif full in ("open", "io.open") and _writes_by_mode(node, 1):
            found.append(f"open:{node.lineno}")
        elif (isinstance(func, ast.Attribute) and func.attr == "open"
                and full not in ("io.open", "os.open")
                and (_writes_by_mode(node, 0) or _writes_by_mode(node, 1))):
            # Path.open('w')・gzip.open(p, 'wb')
            found.append(f"{ast.unparse(func)}:{node.lineno}")
        elif isinstance(func, ast.Attribute) and func.attr in WRITE_METHODS:
            found.append(f"{ast.unparse(func)}:{node.lineno}")
    return found


def _files() -> dict[str, ast.Module]:
    out: dict[str, ast.Module] = {}
    for pattern in PACKAGES:
        for pkg in sorted(ROOT.glob(pattern)):
            for path in sorted(pkg.rglob("*.py")) if pkg.is_dir() else []:
                # パッケージの中に併置したテスト（test_*.py）は、
                # 一時ファイルを書くのが仕事なので見ない
                if "__pycache__" not in path.parts and not path.name.startswith("test_"):
                    out[path.relative_to(ROOT).as_posix()] = ast.parse(
                        path.read_text(encoding="utf-8"))
    return out


def test_table_is_filled() -> None:
    assert SIDE_EFFECT_MODULES or FILE_WRITERS, "表が空（仕様書の「層と副作用」を写す）"
    listed = set().union(*SIDE_EFFECT_MODULES.values(), FILE_WRITERS)
    missing = sorted(rel for rel in listed if not (ROOT / rel).is_file())
    assert not missing, f"表に載っているのに実在しないファイル: {missing}"
    assert _files(), "走査対象が 0 本（PACKAGES を確かめる）"


def test_side_effect_modules_stay_in_their_files() -> None:
    files = _files()
    bad, unused = [], []
    for module, allowed in SIDE_EFFECT_MODULES.items():
        users = {rel for rel, tree in files.items() if uses_module(imported_modules(tree), module)}
        bad += [f"{rel}: {module}" for rel in sorted(users - allowed)]
        unused += [f"{rel}: {module}" for rel in sorted(allowed - users)]
    assert not bad, (
        "表に無いファイルが副作用のモジュールを読んでいる"
        "（置き場所を直すか、仕様書と表を直す）:\n  "
        + "\n  ".join(bad))
    assert not unused, "表に載っているのに使っていない（行を消す）:\n  " + "\n  ".join(unused)


def test_file_writes_stay_in_their_files() -> None:
    files = _files()
    writers = {rel: w for rel, tree in files.items() if (w := file_writes(tree))}
    bad = [f"{rel}: {w}" for rel, w in sorted(writers.items()) if rel not in FILE_WRITERS]
    unused = sorted(FILE_WRITERS - set(writers))
    assert not bad, (
        "表に無いファイルがファイルを書き換えている（置き場所を直すか、仕様書と表を直す）:\n  "
        + "\n  ".join(bad))
    assert not unused, f"FILE_WRITERS に載っているのに書き換えていない（行を消す）: {unused}"


def test_detectors_fire() -> None:
    """陽性対照: 検出器が壊れて常に通る状態でないこと。"""
    tree = ast.parse(
        "import os, subprocess\nimport urllib.request\nfrom shutil import move\nfrom . import net\n"
        "def f(p, q):\n    p.write_text('x')\n    os.link(p, q)\n    q.unlink()\n"
        "    open(p, 'w')\n    open(p)\n    open(p, mode='ab')\n    'a.b'.replace('.', '_')\n"
        "    move(p, q)\n    p.open('w')\n    p.open()\n")
    names = imported_modules(tree) | {"urllib.parse"}
    assert {"os", "subprocess", "urllib.request", "shutil", "shutil.move"} <= names
    # 相対 import はパッケージの中なので見ない
    assert "net" not in names
    assert uses_module(names, "urllib") and uses_module(names, "urllib.request")
    # 副作用の無い兄弟モジュールには当てない
    assert not uses_module({"urllib.parse"}, "urllib.request")
    assert uses_module(imported_modules(ast.parse("from urllib import request\n")),
                       "urllib.request")
    # 読む open と str.replace は拾わない
    assert sorted(w.split(":")[0] for w in file_writes(tree)) == sorted([
        "p.write_text", "os.link", "q.unlink", "open", "open", "shutil.move", "p.open"])
    not_writes = ast.parse("import webbrowser, os\nfrom PIL import Image\nImage.open('cat.png')\n"
                           "webbrowser.open('https://x.com')\nos.open('text.txt', 0)\n"
                           "open('wax.txt')\n")
    # パス・URL の中のモード文字は数えない
    assert file_writes(not_writes) == []
    assert [w.split(":")[0] for w in file_writes(
        ast.parse("import gzip\ngzip.open(p, 'wb')\n"))] == ["gzip.open"]
    aliased = ast.parse("import os as o\nimport shutil\nfrom os import replace as r\nimport io\n"
                        "o.remove(1)\nshutil.rmtree(2)\nr(3, 4)\nio.open(5, 'w')\n")
    assert sorted(w.split(":")[0] for w in file_writes(aliased)) == sorted([
        "os.remove", "shutil.rmtree", "os.replace", "open"])
