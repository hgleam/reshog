"""git 管理下のディレクトリが README.md を持っているか検証する（標準ライブラリのみ）。

**なぜ要るか**: ディレクトリを開いたとき、何のための場所か・何を置いてよいかがその場で
分かるようにするため。README の中身（何のための場所か・置くもの / 置かないもの）は
SKILL.md「ディレクトリごとの README」節が決める。

**この検査だけを入れない。** 有るかどうかしか見ないので、単独で入れると古い README を
量産する仕組みになる。直下のツリーが実ファイルと合っているかは test_doc_tree.py が見る
（必ず組で入れる）。散文（何のための場所か）が実物と合っているかは、どちらも見ない。

コピー後に直すのは次の 3 つだけ（ルートの README の最初の節名 ROOT_FIRST_SECTION は変えない）:

  - EXCLUDED: README を置くと困るディレクトリ（前方一致）と、その理由
  - BASELINE: 途中導入で、いま README が無いディレクトリ（減る方向にしか動かせない）
  - MIN_DIRS: EXCLUDED を除いたいまのディレクトリ数の 8 割ほど（既定の 1 のままだと、走査が壊れて
    数個しか返らなくても緑になる）

実行: python3 tests/test_directory_readmes.py   -> 末尾に ALL_PASS
"""
import os
import re
import subprocess
from pathlib import PurePosixPath

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# README を置くと困るディレクトリ（前方一致）と理由。理由の無い除外は足さない。
# 足してよいのは: 配信される場所（README が公開先から見えてしまう）／生成物だけの場所／
# 置くとツールの動作が壊れる場所／別の形式の説明が正本の場所（スキルの SKILL.md 等）。
EXCLUDED: dict[str, str] = {
    ".claude": (
        "rules/ の中の .md は毎ターン全文が読まれる規則として扱われる。README を置くと規則に混ざる"
    ),
}

# README を置いてはいけないディレクトリ（そのディレクトリ自身だけ。配下は対象のまま）と、その理由。
# 足してよいのは、置くと別の検査・ツールが落ちる場所
# （例: 全ファイルに実行ビットを要求するフックの置き場）。
# 配下にもディレクトリがあり、それも置けないなら EXCLUDED（前方一致）へ入れる。
NO_README: dict[str, str] = {
    # GitHub はリポジトリのトップに出す README を .github/ → ルート → docs/ の順で探すので、
    # .github/README.md があるとトップにルートの README が出なくなる
    # （ファイルを読む確認では見えない）。
    ".github": "README があると GitHub のトップにルートの README が出なくなる（GitHub の仕様）",
}

# 上の 3 つ（EXCLUDED・NO_README・BASELINE）は、キーも値もリテラルで書く（定数名や式を混ぜない）。
# ~/claude-private/.claude/hooks/missing-dir-readme-guard.py が
# このファイルを ast.literal_eval で読むので、
# 読めないと「判定できない」としてファイルを書くたびに止める
# （下の test_lists_are_literals が見る）。

# 途中導入で、まだ README を書けていないディレクトリ（逃げ道。導入したらその場で全部書くのが既定で、
# 書ききれなかった分だけ載せる。下書きは ~/claude-private/.claude/scripts/readme-draft.py）。
# 新しいディレクトリはここへ足さない（足すと、この門を自分で無効にすることになる）。
# README を書いたら行を消す。
BASELINE: set[str] = set()

# ルートの README の最初の `## ` 節。初めて開いた人が「これは何か」を最初に読めるようにする
# （節を足し続けると、冒頭の説明が配信・置き場所の節に埋もれる）。
ROOT_FIRST_SECTION = "何をするものか"

# 見るディレクトリがこれより少なければ、走査が壊れているとみなす（常に緑の空検査を防ぐ）。
# コピーしたら、EXCLUDED を除いたいまのディレクトリ数の 8 割ほどへ上げる
# （1 のままでは守りにならない）。
MIN_DIRS = 14  # 実測 17 個（.claude を除く）の 8 割


def tracked() -> list[str]:
    # `-z` で取る。既定の出力は非 ASCII のパスを引用符付きでエスケープするため、
    # 日本語名のディレクトリが別のパスとして扱われる。
    out = subprocess.run(["git", "-C", REPO, "ls-files", "-z"],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def directories(files: list[str]) -> set[str]:
    """追跡ファイルを 1 つ以上含むディレクトリ（ルートを除く）。"""
    dirs = set()
    for f in files:
        for parent in PurePosixPath(f).parents:
            if str(parent) != ".":
                dirs.add(str(parent))
    return dirs


def excluded(d: str, rules: dict[str, str]) -> bool:
    return any(d == e or d.startswith(e + "/") for e in rules)


def missing_readmes(files: list[str], rules: dict[str, str]) -> list[str]:
    """README.md を持たないディレクトリ（除外を除く）。"""
    have = {str(PurePosixPath(f).parent) for f in files if PurePosixPath(f).name == "README.md"}
    return sorted(d for d in directories(files)
                  if not excluded(d, rules) and d not in have and d not in NO_README)


def shadowing_readmes(files: list[str]) -> list[str]:
    """README を置いてはいけないディレクトリにある README（readme.md・README.rst 等の別名も）。"""
    return sorted(f for f in files if str(PurePosixPath(f).parent) in NO_README
                  and PurePosixPath(f).name.lower().split(".")[0] == "readme")


def outline(readme: str) -> tuple[str, str, str]:
    """(最初の `## ` 節の前の本文, 最初の `## ` 節の名前, その節の本文)。

    コードブロック（``` か ~~~ で開き、同じ記号で同じ長さ以上の行で閉じる範囲）は、
    見出しとしても本文としても数えない（文で「これは何か」を言っていることを見るため）。
    本文からは、空行・見出し・バッジ・HTML コメント・区切り線の行も除く。
    """
    intro: list[str] = []
    name = ""
    body: list[str] = []
    fence = ""
    for raw in readme.lstrip("\ufeff").splitlines():
        line = raw.rstrip("\r")
        if fence:
            close = re.fullmatch(r" {0,3}(`{3,}|~{3,})\s*", line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                fence = ""
            continue
        mark = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line)
        # バッククォートの開きの後ろに ` がある行はインラインコード（```a``` 説明）で、
        # フェンスではない
        if mark and not (mark.group(1)[0] == "`" and "`" in mark.group(2)):
            fence = mark.group(1)
            continue
        if line.startswith("## "):
            if name:
                break
            name = line[3:].strip()
            continue
        (body if name else intro).append(line)

    def is_text(line: str) -> bool:
        s = line.strip()
        return bool(s) and not (
            re.match(r"#{1,6}(\s|$)", s)              # 見出し（#34 のような文は残す）
            or re.fullmatch(r"([-*_])(\s*\1){2,}", s)  # 区切り線（---・***）
            or s.startswith(("[![", "<!--"))          # バッジ・HTML コメント
        )

    def text(lines: list[str]) -> str:
        return "\n".join(x for x in lines if is_text(x))

    return text(intro), name, text(body)


def root_outline() -> tuple[str, str, str]:
    path = os.path.join(REPO, "README.md")
    if not os.path.exists(path):
        return "", "", ""
    with open(path, encoding="utf-8") as fh:
        return outline(fh.read())


def checks(files: list[str], rules: dict[str, str], baseline: set[str],
           min_dirs: int, root: tuple[str, str, str]) -> list[tuple[str, bool]]:
    dirs = directories(files)
    missing = set(missing_readmes(files, rules))
    new = sorted(missing - baseline)
    fixed = sorted(baseline - missing)
    stale = sorted(e for e in rules if e not in dirs)
    no_reason = sorted(e for e, why in rules.items() if not why.strip())
    seen = len([d for d in dirs if not excluded(d, rules)])
    intro, root_first, root_body = root
    shadows = shadowing_readmes(files)
    return [
        (f"README.md が無いディレクトリが増えていない（増えた: {new or 'なし'}。"
         "README を置くか、置くと困る理由があれば EXCLUDED へ理由付きで足す）", not new),
        (f"README を書いたディレクトリが BASELINE に残っていない"
         f"（残り: {fixed or 'なし'}。行を消す）",
         not fixed),
        (f"除外がいまも在るディレクトリを指している（もう無い: {stale or 'なし'}。"
         "残すと、同じ名前で作り直したときに黙って素通りする）", not stale),
        (f"除外に理由が書いてある（理由なし: {no_reason or 'なし'}）", not no_reason),
        (f"見るディレクトリが {min_dirs} 個以上ある（{seen} 個。少なければ走査が壊れている）",
         seen >= min_dirs),
        (f"README を置いてはいけないディレクトリ（NO_README）に README が無い"
         f"（ある: {shadows or 'なし'}。消す）",
         not shadows),
        (f"ルートの README の最初の節が「{ROOT_FIRST_SECTION}」（いま: {root_first or '節なし'}）",
         root_first == ROOT_FIRST_SECTION),
        ("ルートの README が最初の節の前に、これは何かを 1 文以上で述べている", bool(intro)),
        (f"ルートの README の「{ROOT_FIRST_SECTION}」に本文がある", bool(root_body)),
    ]


def failures() -> list[str]:
    """満たされていない検査項目のラベル。"""
    return [label for label, ok in checks(tracked(), EXCLUDED, BASELINE, MIN_DIRS, root_outline())
            if not ok]


def test_missing_readme_is_detected() -> None:
    """陽性対照: README の無いディレクトリを挙げる（判定が常に空を返していないか）。"""
    files = ["a/README.md", "a/x.ts", "a/b/y.ts", "public/z/w.html"]
    assert missing_readmes(files, {"public": "配信する"}) == ["a/b"]


def test_outline_detects_infra_first() -> None:
    """陽性対照: 技術の節が先に来ている README を見分け、コードブロックの中の `## ` は無視する。"""
    assert outline("# x\n\n説明\n\n## どこで動くか\n\n## 何をするものか\n")[1] == "どこで動くか"
    assert outline("# x\n\n説明\n\n```\n## 例\n```\n\n## 何をするものか\n本文\n") == (
        "説明", "何をするものか", "本文")


def test_lists_are_literals() -> None:
    """EXCLUDED・NO_README・BASELINE がリテラルで書かれている
    （フックが literal_eval で読めないと書き込みを全部止める）。"""
    import ast
    with open(os.path.realpath(__file__), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = {"EXCLUDED", "NO_README", "BASELINE"}
    found = set()
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None)
        if isinstance(target, ast.Name) and target.id in names and node.value is not None:
            value = node.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id in ("set", "frozenset") and not value.args):
                # フックと同じく set にする。名前・式は ValueError、
                # ハッシュできない中身や数は TypeError で落ちる
                set(ast.literal_eval(value))
            found.add(target.id)
    assert found == names, f"見つからない: {names - found}"


def test_exclusions_have_reasons() -> None:
    assert all(why.strip() for why in {**EXCLUDED, **NO_README}.values())


def test_directory_readmes() -> None:
    """pytest から収集されたときも同じ検査を行う（import 時には何も実行しない）。"""
    assert not failures(), "\n".join(failures())


if __name__ == "__main__":
    ok = True
    for label, res in checks(tracked(), EXCLUDED, BASELINE, MIN_DIRS, root_outline()):
        print(("PASS " if res else "FAIL ") + label)
        ok = ok and res
    print()
    print("ALL_PASS" if ok else "HAS_FAILURE")
    raise SystemExit(0 if ok else 1)
