"""コードの形を測る道具の定数（測る場所・測らない場所・数え方の語）。

写した先で直すのは TARGETS（測る場所）・TEST_TARGETS（テストの置き場）・SKIP（測らない場所）だけ。
ほかは測り方なので変えない。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

#: リポジトリの直下（この道具は scripts/code_shape/ に置く）。
ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "metrics" / "code-shape.json"
KINDS = ("files", "functions", "complexity", "per_file", "dirs", "prefixes")

#: 測るディレクトリ（実装の置き場）。この中のテスト（scan.py の is_test_file）は
#: 行数と補助関数だけ測る（下の TEST_TARGETS）。
TARGETS = ("src", "scripts", "tools", "functions")
#: テストの置き場（下のファイルは名前を問わず全部テスト）。
#: テストはファイルの行数（files）と、テストケースでない関数（検査ロジックの補助）の
#: 長さ・複雑度を測る（ケースは長い手順が普通なので測らない。本数・ディレクトリの粒度も測らない。
#: 2026-11-12 は行数だけだったが、補助関数が育っても鳴らない穴を理由に 2026-11-16 に改めた）。
TEST_TARGETS = ("tests",)
#: テストケースの関数名（Python は `test_` で始まる関数・メソッド・その中の入れ子、
#: JS は `Deno.test("…")`・`test(`・`it(`・`describe(` の呼び出し）。
#: 素の `it(`・`test(` は名前が付かず <top-level> に畳まれる。
#: `Deno.test({ name, fn() {…} })` の形は鍵が `fn` になるので、それもケースに数える。
TEST_CASE = re.compile(
    r"(?:^|\.)test_|^fn(?:\.|$)|^(?:Deno\.)?(?:test|it|describe|bench)(?:\.\w+)*\("
)
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs"}
#: テストの置き場の名前（パスのどこかにあればテスト。code-complexity-audit の点検と同じ規則）。
TEST_DIRS = {"tests", "__tests__", "test", "spec", "e2e", "__mocks__"}
#: 測らない場所（生成物・依存・配信物）。パスのどこかにこの名前の部分があれば外す。
SKIP = {"node_modules", "dist", "build", "public", "__pycache__", ".venv", "vendor"}

# ---- ディレクトリの粒度を測る語（dir_shape.py） ----

#: 名前の頭を切る区切り（言語で慣習が違う。Python は `_`、TypeScript は `-` が多い）。
NAME_SEPARATORS = ("-", "_")
#: ディレクトリの指標（鍵が `ディレクトリ` か `ディレクトリ/頭*`）。
#: 台帳の書き直しで、名指ししたファイルの親も照らす。
DIR_KINDS = ("dirs", "prefixes")

PY_BRANCH = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler, ast.comprehension
)

# ---- TypeScript / JavaScript を測る語 ----

#: どの名前つきの関数にも入らない部分の鍵（関数ではないので per_file には数えない）。
TOP_LEVEL = "<top-level>"

BRANCH = re.compile(r"\b(?:if|for|while|case|catch)\b|&&|\|\||\?\?|\?(?![.?:])")
KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "with", "else", "do", "try",
    "async",
}
#: 関数の頭（名前と、引数の開き括弧まで）。引数・戻り値の型・本体の範囲は括弧の対応で取る
#: （引数の型に `{ ... }` があると、正規表現で決め打ちした範囲は壊れる）。
HEADS = [
    re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)\s*(?:<[^>(]*>)?\s*(?=\()"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]*)?=\s*(?:async\s+)?"
               r"(?:function\b\s*\*?\s*)?(?:<[^>(]*>)?\s*(?=\()"),
    #: メソッド（行頭か `{`・`}`・`,`・`;` の直後）。
    #: get/set は鍵に添える（同名の getter と setter を区別する）。
    re.compile(r"(?:^|(?<=[{},;]))[ \t]*"
               r"(?:(?:public|private|protected|static|async|readonly|override)\s+)*"
               r"(?:(get|set)\s+)?\*?\s*(#?[A-Za-z_$][\w$]*)\s*(?:<[^>(]*>)?\s*(?=\()", re.M),
]
#: メソッドの頭（呼び出しと形が同じ）。
#: 本体の `{` が `)` と同じ行に無ければ、呼び出しと次のブロックと見る。
METHOD_HEAD = HEADS[-1]
#: この語の直後の `(` は呼び出しではない（無名のアロー関数の引数になりうる）。
EXPR_WORDS = {"async", "return", "default", "yield", "await"}
#: クラスの頭から本体の `{` まで（`extends B<{ x: 1 }>` の型引数の `{` は飛ばす）。
CLASS = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)(?:[^{;<]|<(?:[^<>]|<[^<>]*>)*>)*\{")
#: 無名の関数の頭。`function (`・`x =>`（引数の括弧の無いアロー）。
#: 括弧つきのアローは `(` を順に見て拾う。
ANON_FUNCTION = re.compile(r"\bfunction\s*\*?\s*(?=\()")
BARE_ARROW = re.compile(r"(?<![\w$.])(?:async\s+)?[A-Za-z_$][\w$]*\s*=>")
ARROW_PARAM = re.compile(r"[A-Za-z_$][\w$]*\s*=>")
#: 無名の関数に名前を推す形（名前, 推した形。"field" はクラスのフィールドの形）。
CONTEXT_NAMES = (
    (re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^;]*)?(?<![=!<>])=$", re.M), ""),
    (re.compile(r"(?:^|[;{}])\s*(?:(?:public|private|protected|static|readonly|override)\s+)*"
                r"(#?[A-Za-z_$][\w$]*)\s*\??\s*(?::[^;=]*)?(?<![=!<>])=$", re.M), "field"),
    (re.compile(r"(?:^|[{,])\s*([A-Za-z_$][\w$]*)\s*:$", re.M), ""),
)
#: 第 1 引数が文字列のメソッド呼び出しの、最後の引数の手前まで（`app.post("/a", auth, `）。
#: 間の引数は名前か括弧 1 段の呼び出しだけ。
#: 素の呼び出し（`describe("d", `）は名前にしない（テストの塊を 1 本と数えない）。
ROUTE_CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*(?:\s*\??\.\s*[A-Za-z_$][\w$]*)+)"
                        r"\s*(?:<[^<>()]*>)?\s*\("
                        r"\s*([\"'])([^\"'\n]*)\2\s*,"
                        r"(?:\s*[\w$.]+(?:\([^()]*\))?\s*,)*$")

# ---- コメント・文字列を消すときの語 ----

#: この語の直後の `/` は割り算ではなく正規表現の始まり（`return /re/`）。
REGEX_AFTER = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void",
               "throw", "instanceof", "yield", "await"}
#: この語の直後の ' は文字列の始まり（アポストロフィではない。REGEX_AFTER に加えて）。
STRING_AFTER = {"from", "import", "export", "default", "as", "satisfies", "is", "extends"}
#: 直前の語を取る窓の長さ（キーワードの最長から導く。
#: 固定の数にすると、長い語を足したとき黙って効かなくなる）。
WORD_WINDOW = max(len(w) for w in REGEX_AFTER | STRING_AFTER) + 2
