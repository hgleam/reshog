"""コードの置き場所の約束を固定する(複雑度監査 2026-09-29 の指摘を戻さないため)。

どれも振る舞いのテストでは見えない。違反しても何も壊れず、次に手を入れたときに
「片方だけ直る」「置き場が決まらず育つ」形で効いてくる。
"""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "reshog"


def _tree(name: str) -> ast.Module:
    return ast.parse((SRC / name).read_text(encoding="utf-8"))


def _functions_calling(tree: ast.Module, module: str, prefix: str) -> set[str]:
    """`module.prefix*()` を呼んでいる関数名(最も内側の def)を集める。"""
    found: set[str] = set()

    def visit(node: ast.AST, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            name = owner
            if isinstance(child, ast.FunctionDef):
                name = child.name
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == module
                and child.func.attr.startswith(prefix)
                and owner is not None
            ):
                found.add(owner)
            visit(child, name)

    visit(tree, None)
    return found


def test_views_are_built_in_one_place() -> None:
    """表示の組み立て(report.build_*)を呼ぶのは cli の 1 関数だけ。

    通常表示と --watch が別々に振り分けを持っていると、表示を足すたびに両方へ書き足す
    必要があり、片方を忘れても何も壊れない(#16 で --project を両方へ書き足した)。
    """
    callers = _functions_calling(_tree("cli.py"), "report", "build_")
    assert callers == {"_render_view"}, callers


def test_render_functions_do_not_branch_on_view_kind() -> None:
    """アプリ別と PJ 別の表を 1 関数の `kind` 引数で描き分けない。

    見出し・列・提案が全部分岐し、1 関数の複雑度が膨らむ(#16 で 15 になった)。
    """
    tree = _tree("render.py")
    params = {
        a.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for a in node.args.args + node.args.kwonlyargs
    }
    assert "kind" not in params


_CONSTANT_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
# 定数の置き場・型の置き場。それ以外は実装のファイル。
_CONSTANTS_HOME = "constants.py"
_TYPES_HOME = "models.py"


def _module_level_names(tree: ast.Module) -> list[tuple[str, int]]:
    """モジュールの最上位(try・if の中も含む)で代入される名前。"""
    found: list[tuple[str, int]] = []

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Assign):
                found.extend((t.id, node.lineno) for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                found.append((node.target.id, node.lineno))
            elif isinstance(node, (ast.If, ast.Try)):
                visit(node.body)
                visit(node.orelse)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)

    visit(tree.body)
    return found


def _is_type_class(node: ast.ClassDef) -> bool:
    """メソッド(プロパティ以外)を持たないクラス = 型定義。"""
    return not any(
        isinstance(n, ast.FunctionDef)
        and not any(isinstance(d, ast.Name) and d.id == "property" for d in n.decorator_list)
        for n in node.body
    )


def _implementation_files() -> list[Path]:
    homes = {_CONSTANTS_HOME, _TYPES_HOME, "__init__.py"}
    files = [p for p in sorted(SRC.glob("*.py")) if p.name not in homes]
    # 母集団が空なら走査先を間違えている。0 件で緑にしない。
    assert len(files) >= 8, files
    return files


def test_implementation_files_hold_no_constants() -> None:
    """実装のファイルに大文字の定数を置かない(constants.py へ)。"""
    found = [
        f"{p.name}:{line} {name}"
        for p in _implementation_files()
        for name, line in _module_level_names(ast.parse(p.read_text(encoding="utf-8")))
        if _CONSTANT_NAME.match(name)
    ]
    assert not found, found


def test_implementation_files_hold_no_type_definitions() -> None:
    """実装のファイルに型定義(メソッドを持たないクラス)を置かない(models.py へ)。"""
    found = [
        f"{p.name}:{node.lineno} {node.name}"
        for p in _implementation_files()
        for node in ast.parse(p.read_text(encoding="utf-8")).body
        if isinstance(node, ast.ClassDef) and _is_type_class(node)
    ]
    assert not found, found


def test_types_home_holds_no_constants() -> None:
    """型の置き場にも定数を置かない(しきい値は constants.py の 1 か所)。"""
    names = _module_level_names(_tree(_TYPES_HOME))
    assert not [n for n, _ in names if _CONSTANT_NAME.match(n)], names


def test_no_constant_is_written_twice() -> None:
    """同じ値の定数を 2 つの名前で持たない(片方だけ直ってずれる)。"""
    from reshog import constants

    values: dict[str, list[str]] = {}
    for name in dir(constants):
        if _CONSTANT_NAME.match(name):
            values.setdefault(repr(getattr(constants, name)), []).append(name)
    assert len(values) >= 10, values
    duplicated = {v: names for v, names in values.items() if len(names) > 1}
    assert not duplicated, duplicated


# 文書に出てくる大文字の名前のうち、reshog の定数ではないもの(理由つき)。
_DOC_NAMES_NOT_CONSTANTS = {
    "GITHUB_TOKEN": "CI の環境変数",
    "PID": "列名・用語",
    "WATCH_PATTERNS": "scripts/check-spec-freshness.sh の変数",
}
_DOC_CONSTANT = re.compile(r"`(_?[A-Z][A-Z0-9_]{2,})(?: = [^`]*)?`")


def test_constants_named_in_docs_exist() -> None:
    """文書が名指しする定数が constants.py に実在する(改名しても文書は誰も落とさない)。

    実例: 定数を constants.py へ移して _MAX_CMD → MAX_CMD に改名したとき、testing.md の
    説明だけ古い名前のまま残った(レビューで見つかった)。
    """
    from reshog import constants

    root = SRC.parent.parent
    docs = [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
    named = {
        (m.group(1), doc.relative_to(root).as_posix())
        for doc in docs
        for m in _DOC_CONSTANT.finditer(doc.read_text(encoding="utf-8"))
    }
    assert len(named) >= 5, named
    missing = sorted(
        f"{path}: {name}"
        for name, path in named
        if name not in _DOC_NAMES_NOT_CONSTANTS and not hasattr(constants, name)
    )
    assert not missing, missing


def test_render_has_no_view_kind_comparisons() -> None:
    """render.py で表示の種類の文字列と比べる分岐を置かない(引数名を変えた再導入も拾う)。"""
    kinds = {"app", "group", "project", "processes"}
    found = [
        node.lineno
        for node in ast.walk(_tree("render.py"))
        if isinstance(node, ast.Compare)
        and any(
            isinstance(c, ast.Constant) and c.value in kinds
            for c in [node.left, *node.comparators]
        )
    ]
    assert not found, found
