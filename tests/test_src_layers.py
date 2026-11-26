"""パッケージの直下を層で切り、層ごとに読んでよい層を表で決めて固定する（init の雛形）。

同じ階層の兄弟が別々の軸（層・外部の相手・定義の種類）で切られていると、
新しいものの置き場が
ディレクトリから決まらない。本数の門（test_code_shape_ratchet.py の dirs）は本数しか見ないので、
ここで「直下は層だけ」「層ごとの基準が書いてある」「読む向きが表どおり」を機械で守る
（code-complexity-audit §3.6 の 5 つ目）。

- `LAYERS`: 層（直下のディレクトリ、または型の層のファイル）→ 読んでよい層。
  自分の層は書かなくても読める
- `TOP_FILES`: 直下に置いてよい、層ではないファイル
- 各層のディレクトリの README.md に `- 基準:`・`- 置くもの:`・`- 置かないもの:` の行が要る
- import はパッケージの中のもの
  （相対 import と、パッケージ名から始まる絶対 import）だけを見る

層の名前と数はリポの中身から決める
（参照実装・この雛形の例の名前を写さない。code-complexity-audit §3.6）。
コピー後に直すのは
`PACKAGE`・`LAYERS`・`TOP_FILES`・`STDLIB_NAME_ALLOWED`・`MIN_FILES`・`MIN_EDGES` だけ。
`PACKAGE` と `LAYERS` は空のままでは落ちる（雛形のまま入れて、何も守らない門にしない）。
参照実装: page-media-fetch の `tests/test_src_layers.py`。

拾えないもの: `importlib.import_module` の文字列・`__import__`・
関数の中で組み立てた名前の import。
Python 3.9 で標準ライブラリの名前を集めるとき、Windows の C 拡張（`DLLs/*.pyd`）は拾わない
（3.10 以降は `sys.stdlib_module_names` を使う）。
層の中身が基準に合っているか（判断が外部連携の層に紛れていないか等）は見ない
（レビューで見る）。
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 測るパッケージ（ROOT からの相対パス）
PACKAGE = "src/reshog"
#: 層 → 読んでよい層（自分の層は書かなくても読める）。型の層はファイル（拡張子を除いた名前）で書く
#: 例（名前は写さない）:
#: {"cli": {"pipeline", "types"}, "pipeline": {"external", "types"}, "external": {"types"},
#:  "types": set()}
LAYERS: dict[str, set[str]] = {
    # 層は 1 ファイル 1 層（16 モジュールが直下に平置き。束ねるのは設計判断で別の作業）。
    # 向きは導入時の import をそのまま写した。循環は無い。
    "constants": set(),
    "control": set(),
    "models": {"constants"},
    "claude": {"constants"},
    "collect": {"constants"},
    "llama": {"constants"},
    "aggregate": {"models"},
    "known": {"constants", "models"},
    "origin": {"constants", "models"},
    "parse": {"constants", "models"},
    "group": {"aggregate", "constants", "models"},
    "churn": {"constants", "group", "models"},
    "trend": {"churn", "constants", "models", "origin"},
    "render": {"churn", "constants", "known", "models", "origin"},
    "report": {"aggregate", "churn", "claude", "collect", "constants", "control", "group", "llama",
               "models", "origin", "parse", "trend"},
    "cli": {"constants", "control", "known", "models", "render", "report"},
}
#: 直下に置いてよい、層ではないファイル。
#: このうち .py はパッケージの入口として、どの層を読んでもよい
#: （`__main__.py` の `from .cli import main`・`__init__.py` の再エクスポート）。
#: .py は入口だけを足す
#: （ここに足した .py は import の向きを見なくなる。中身のあるものは層へ置く）
TOP_FILES = {"__init__.py", "__main__.py", "README.md", "py.typed"}
#: 層のディレクトリの README に要る行の書き出し
README_LINES = ("- 基準:", "- 置くもの:", "- 置かないもの:")
#: 標準ライブラリと同じ名前でも置いてよいファイル → 理由。
#: そのディレクトリを作業場所にして Python を起こすと、
#: 標準ライブラリより先に見つかって落ちる（フックの `python -c` も落ちる）。
#: 新しく足すものは名前を変えて避ける。
#: `types.py` だけは、同じ init の test_definitions_live_apart.py の雛形が
#: 型の置き場の名前として決めているので、
#: ここで落とすと 2 つの雛形がぶつかる。危険は残るので、そのディレクトリを作業場所にしない
STDLIB_NAME_ALLOWED: dict[str, str] = {
    "types.py": "test_definitions_live_apart.py の雛形が型の置き場の名前に決めている",
}
#: 走査の母集団の下限（読み取りが壊れて 0 近くになったら落とす。
#: 導入時の実測の 8 割ほど。既定の 1 のままにしない）
MIN_FILES = 14  # 実測 17 本（`__init__.py` を含む）の 8 割
MIN_EDGES = 36  # 実測 45 本の 8 割


def test_layer_table_is_filled_in():
    assert PACKAGE and LAYERS, "PACKAGE と LAYERS をこのリポの層で書く（空のままでは何も守らない）"
    unknown = sorted({d for deps in LAYERS.values() for d in deps} - set(LAYERS))
    assert unknown == [], f"LAYERS の読み先に、層として書いていない名前がある: {unknown}"


def layer_of(rel: Path) -> str:
    """パッケージからの相対パスが属する層（直下のファイルは拡張子を除いた名前）。"""
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def imported_modules(
    tree: ast.Module, rel: Path, package_name: str
) -> list[tuple[int, tuple[str, ...]]]:
    """パッケージの中の import 先を、パッケージからの部品の並びで返す（行番号つき）。

    `from . import ffmpeg` は `ffmpeg` まで、`from .types import Plan` は `types` までを返す。
    """
    here = rel.parent.parts
    out: list[tuple[int, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                up = node.level - 1
                if up > len(here):  # パッケージの外
                    continue
                base = here[: len(here) - up]
                mod = tuple(node.module.split(".")) if node.module else ()
                if node.module:
                    out.append((node.lineno, base + mod))
                else:
                    out += [(node.lineno, (*base, a.name)) for a in node.names]
            # from pkg import cli は、相対の from . import cli と同じに読む
            elif node.module == package_name:
                out += [(node.lineno, (a.name,)) for a in node.names]
            elif node.module and node.module.split(".")[0] == package_name:
                out.append((node.lineno, tuple(node.module.split(".")[1:])))
        elif isinstance(node, ast.Import):
            out += [(node.lineno, tuple(a.name.split(".")[1:])) for a in node.names
                    if a.name.split(".")[0] == package_name]
    return out


def violations(files: dict[Path, str], package_name: str, layers: dict[str, set[str]],
               top_files: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """表に無い向きの import を「ファイル:行 層 → 層」で返す。
    files はパッケージからの相対パス → 本文。

    直下の top_files（`__init__.py`・`__main__.py`）は入口なので見ない。
    層から入口を読むものは落とす。
    """
    out: list[str] = []
    for rel, text in sorted(files.items()):
        if len(rel.parts) == 1 and rel.name in top_files:
            continue
        src = layer_of(rel)
        for lineno, parts in imported_modules(ast.parse(text), rel, package_name):
            if not parts or parts[0] not in layers:
                out.append(f"{rel}:{lineno} 層でないもの"
                           "（パッケージの入口 __init__ 等）を読んでいる")
                continue
            dst = parts[0]
            if dst != src and dst not in layers.get(src, set()):
                out.append(f"{rel}:{lineno} {src} → {dst}")
    return out


def stray_entries(names: list[str], layers: dict[str, set[str]], top_files: set[str]) -> list[str]:
    """直下にある、層でも許したファイルでもないもの。"""
    allowed = {f"{n}.py" for n in layers} | set(layers) | top_files
    return sorted(n for n in names
                  if n not in allowed and not n.startswith(".") and n != "__pycache__")


def _package_files() -> dict[Path, str]:
    pkg = ROOT / PACKAGE
    return {p.relative_to(pkg): p.read_text(encoding="utf-8")
            for p in sorted(pkg.rglob("*.py"))
            if "__pycache__" not in p.parts}


def test_package_top_has_only_layers():
    names = [p.name for p in (ROOT / PACKAGE).iterdir()]
    assert stray_entries(names, LAYERS, TOP_FILES) == [], (
        "直下には層（LAYERS）と TOP_FILES だけを置く")


def test_every_layer_exists_and_states_its_criterion():
    pkg = ROOT / PACKAGE
    missing: list[str] = []
    for name in LAYERS:
        if (pkg / f"{name}.py").is_file():
            if (pkg / name).is_dir():
                missing.append(f"{name}.py と {name}/ が並んでいる（層はどちらか 1 つ）")
            continue
        readme = pkg / name / "README.md"
        if not readme.is_file():
            missing.append(f"{name}/README.md が無い（層のディレクトリか {name}.py が要る）")
            continue
        lines = readme.read_text(encoding="utf-8").splitlines()
        missing += [f"{name}/README.md に「{w}」の行が無い" for w in README_LINES
                    if not any(line.startswith(w) for line in lines)]
    assert missing == []


def test_imports_follow_the_layer_table():
    files = _package_files()
    name = Path(PACKAGE).name
    edges = sum(len(imported_modules(ast.parse(t), r, name)) for r, t in files.items())
    assert len(files) >= MIN_FILES, f"走査したファイルが少なすぎる: {len(files)}"
    assert edges >= MIN_EDGES, f"読み取った import が少なすぎる: {edges}"
    assert violations(files, name, LAYERS, TOP_FILES) == []


def stdlib_names() -> frozenset[str]:
    """標準ライブラリのトップのモジュール名
    （3.9 には sys.stdlib_module_names が無いので、置き場を読んで作る）。"""
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return frozenset(names)
    # 置き場は実際に読み込まれた場所から取る
    # （pyenv の framework 版では sysconfig の stdlib が実物と食い違う）
    lib = Path(os.__file__).parent
    found: set[str] = set()
    # zip の中（Windows の embeddable 版）は読めない。数が足りなくなり、下の検査が落ちて知らせる
    if lib.is_dir():
        found = {p.stem for p in lib.iterdir()
                 if p.suffix == ".py" or (p / "__init__.py").is_file()}
    for dynload in {lib / "lib-dynload",
                    *(Path(e) for e in sys.path if Path(e).name == "lib-dynload")}:
        if dynload.is_dir():  # C 拡張（math・array・select 等）
            found |= {p.name.split(".")[0] for p in dynload.iterdir() if p.suffix == ".so"}
    return frozenset(sys.builtin_module_names) | frozenset(found)


def stdlib_shadows(rels: list[Path], allowed: dict[str, str]) -> list[str]:
    """標準ライブラリのモジュールと同じ名前のファイル・ディレクトリ（許したものを除く）。

    ディレクトリは先頭からのパスに / を付けて返す（`a/logging/`）。
    allowed には部品の名前に / を付けて書き
    （`logging/`）、どの階層のその名前にも効く。
    `test/` のような標準ライブラリにもある名前を残すなら、ここで理由を書く。
    """
    names = stdlib_names()
    out = {str(r) for r in rels if r.stem in names and r.name not in allowed}
    for r in rels:
        for i, part in enumerate(r.parts[:-1]):
            if part in names and f"{part}/" not in allowed:
                out.add(Path(*r.parts[: i + 1]).as_posix() + "/")
    return sorted(out)


#: 標準ライブラリの名前の数の下限
#: （読み取りが壊れて少なくなったら、照合が黙って通るので落とす。実測は 3.9 で 306）
MIN_STDLIB_NAMES = 200


def test_no_module_shadows_the_standard_library():
    assert len(stdlib_names()) >= MIN_STDLIB_NAMES, (
        "標準ライブラリの名前を集められない（置き場が zip の中など）")
    assert stdlib_shadows(list(_package_files()), STDLIB_NAME_ALLOWED) == []


def test_checks_fire_on_synthetic_violations():
    # 陽性対照: 数え方そのものが壊れると、上の検査は空振りで通る
    layers = {"a": {"t"}, "b": {"a", "t"}, "t": set()}
    files = {
        # a → b は表に無い。同じ層は通る
        Path("a/x.py"): "from ..b.y import f\nfrom . import z\n",
        # 絶対 import の a → b
        Path("a/z.py"): "from ..t import T\nimport pkg.b.y\n",
        # 表どおり
        Path("b/y.py"): "from ..a import x\nfrom ..t import T\n",
        # 型の層から a
        Path("t.py"): "from .a.x import g\n",
        # 型の層（ファイル）・パッケージの外
        Path("b/w.py"): "from .. import t\nfrom ...outside import q\n",
        # 絶対 import で層を名指し（表どおり）
        Path("b/v.py"): "from pkg import a, t\nfrom pkg import b\n",
        # 絶対 import で層を名指し（表に無い）
        Path("t2/u.py"): "from pkg import b\n",
        # 層から入口の名前を読む
        Path("a/e.py"): "from pkg import VERSION\n",
        # 入口はどの層を読んでもよい
        Path("__main__.py"): "from .b.y import f\nfrom pkg import a\n",
    }
    # 読み飛ばしが過剰でないこと: パッケージの中へ上る相対 import は拾い、外へ出るものだけ飛ばす
    assert imported_modules(
        ast.parse(files[Path("b/w.py")]), Path("b/w.py"), "pkg") == [(1, ("t",))]
    layers = {**layers, "t2": {"a"}}
    got = violations(files, "pkg", layers, {"__main__.py"})
    assert got == ["a/e.py:1 層でないもの（パッケージの入口 __init__ 等）を読んでいる",
                   "a/x.py:1 a → b", "a/z.py:2 a → b", "t.py:1 t → a", "t2/u.py:1 t2 → b"], got
    assert stray_entries(["a", "b", "t.py", "misc.py", "__init__.py", "__pycache__", ".DS_Store"],
                         layers, {"__init__.py"}) == ["misc.py"]
    assert {"json", "types", "http", "math", "array"} <= stdlib_names()
    assert stdlib_shadows([Path("external/http.py"), Path("types.py"), Path("external/net.py"),
                           Path("json/x.py"), Path("json/y.py"), Path("a/logging/z.py")],
                          {"types.py": "x"}) == ["a/logging/", "external/http.py", "json/"]
