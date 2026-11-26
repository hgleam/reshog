"""TypeScript / JavaScript の「形」を測る（scan.py から呼ばれる。標準ライブラリのみ）。

構文木を使わず、コメントを消して文字列・テンプレート・正規表現の中身を空白にしてから（text.py）、
括弧の対応で関数の範囲を取る。
向きを見るための物差しなので、同じ書き方なら毎回同じ数になることを優先している。

- 名前は外側のクラス・関数を `.` でつなぐ（`Box.open`・`arrow.inner`・getter は `A.v(get)`）
- 無名の関数は置かれた場所から名前を推す
  （`const f =`・`key:`・クラスのフィールド・`export default`・
  第 1 引数が文字列のメソッド呼び出し `app.get("/a", (c) => {})` → `app.get("/a")`。
  ルートの処理を 1 本ずつ測るため。
  文字列は並べ替えで変わらないので鍵にできる。同じ鍵が 2 本以上あれば全部畳む）。
  推せない無名（コールバック・IIFE）は
  1 本と数えず、関数の中なら外側の中身、
  外に無ければファイルに 1 本の `<top-level>`（モジュール直下の分岐も含む）に
  畳む。連番の鍵は並べ替えで値が入れ替わるので作らない
- 括弧の対応が取れなければ None（読めなかった）。黙って外さず、呼ぶ側が数える

読めない書き方: `)`・`}` の直後の正規表現
（`if (x) /re{/.test(y)`・ブロックの直後の行頭の `/re{/`）は割り算と見る
（unreadable に出る。`}` の直後を割り算と見るのは JSX の `{a}/{b}` のため）。
名前を推さない書き方（分岐は外側か `<top-level>` に入る）: 引用符つきのキー（`'k-1': () =>`）。
呼び出しでは、第 1 引数が
テンプレート文字列・呼び出しの結果に続くメソッド（`app.route("/x").get(`）・
間の引数に配列や 2 段以上の括弧があるもの・
2 つ目以降の無名の関数・入れ子の型引数（`get<A<B>>(`）・`get?.(`・`app!.get(`。
逆に、点つきの呼び出しはルートでなくても名前にする
（`el.on("click", …)`・`test.skip("x", …)`。
テストのファイルでは、この名前がケースかどうかを constants.TEST_CASE が判定し、ケースは測らない）。
"""

from __future__ import annotations

import re

from ..constants import (ANON_FUNCTION, ARROW_PARAM, BARE_ARROW, BRANCH, CLASS, EXPR_WORDS, HEADS,
                        KEYWORDS, METHOD_HEAD, TOP_LEVEL)
from ..jsx_lines import blank_jsx_comments
from .names import context_name
from .text import balanced, close_of, skip_space, strip_js


# ---- 括弧の対応と、関数の本体の範囲 ----

def _arrow_body(text: str, k: int) -> int | None:
    """`=>` の直後から本体の `{` を探す。関数を返すアロー（`() => () => {`）は内側の本体を返す。"""
    k = skip_space(text, k)
    if (text.startswith("async", k)
            and not (text[k + 5:k + 6].isalnum() or text[k + 5:k + 6] in "_$")):
        k = skip_space(text, k + 5)
    if k >= len(text):
        return None
    if text[k] == "{":
        return k
    if text[k] == "(":
        return _body_open(text, k, arrow_only=True)
    m = ARROW_PARAM.match(text, k)
    return _arrow_body(text, m.end()) if m else None


def _ends_statement(last: str, c: str) -> bool:
    """改行をまたいで、型の終わり（識別子・閉じ括弧）の後ろに語が来た＝セミコロンの無い次の文。"""
    return (last.isalnum() or last in "_$>])}") and (c.isalpha() or c in "_$")


def _typed_body(text: str, k: int, arrow_only: bool) -> int | None:
    """戻り値の型（`:` の直後）を読み飛ばして本体の `{` を探す。
    型の中の `{ ... }`（`:`・`|`・`&`・`<`・`,` の
    直後）と `( ... )` は型として飛ばす。"""
    last, newline = ":", False
    while k < len(text):
        c = text[k]
        if c.isspace():
            newline = newline or c == "\n"
            k += 1
            continue
        if newline and _ends_statement(last, c):
            return None  # 型が終わり、セミコロンの無い次の文（interface の次のメンバー等）に入った
        newline = False
        if text.startswith("=>", k):
            j = skip_space(text, k + 2)
            if text[j:j + 1] == "{":
                return j
            k, last = k + 2, ">"
            continue
        if c == "(" or (c == "{" and last in ":|&<,"):
            k, last = close_of(text, k) + 1, ")" if c == "(" else "}"
            continue
        if c == "{":
            return None if arrow_only else k
        if c in ";})=":
            return None
        last = c
        k += 1
    return None


def _body_open(text: str, paren_at: int, arrow_only: bool = False,
               same_line: bool = False) -> int | None:
    """引数の閉じ括弧の後ろから、本体の `{` の位置を探す
    （本体が無い・式だけのアロー関数なら None）。

    引数の直後に来てよいのは `{`（本体）・`=>`（アロー）・`:`（戻り値の型）だけ。
    それ以外（改行して次の文・
    `.then(`）なら関数ではなく呼び出し。
    arrow_only なら `=>` を通らない本体を認めない
    （無名のアローを探すとき。`if (x) {` を関数と見ない）。
    same_line なら `)` と本体の `{` の間に改行を認めない
    （メソッドの頭は呼び出しと形が同じ。`foo(a)\\n{` はブロック）。
    """
    after = close_of(text, paren_at) + 1
    k = skip_space(text, after)
    if k >= len(text):
        return None
    if text[k] == "{":
        return None if arrow_only or (same_line and "\n" in text[after:k]) else k
    if text.startswith("=>", k):
        return _arrow_body(text, k + 2)
    return _typed_body(text, k + 1, arrow_only) if text[k] == ":" else None


# ---- 関数を集める ----

def _named_bodies(text: str) -> dict[int, tuple[str, int]]:
    """名前のある関数の 本体の開き括弧の位置 → (名前, 閉じ括弧の位置)。"""
    named: dict[int, tuple[str, int]] = {}
    for pat in HEADS:
        for m in pat.finditer(text):
            name = m.group(m.lastindex or 1)
            if name in KEYWORDS:
                continue
            if pat is METHOD_HEAD and m.group(1):
                name = f"{name}({m.group(1)})"
            body = _body_open(text, m.end(), same_line=pat is METHOD_HEAD)
            if body is not None and body not in named:
                named[body] = (name, close_of(text, body))
    return named


def _anonymous_heads(text: str) -> list[tuple[int, int | None]]:
    """無名の関数の (頭の位置, 本体の `{` の位置)。"""
    heads: list[tuple[int, int | None]] = []
    for m in ANON_FUNCTION.finditer(text):
        heads.append((m.start(), _body_open(text, m.end())))
    for m in BARE_ARROW.finditer(text):
        heads.append((m.start(), _arrow_body(text, m.end())))
    for k, c in enumerate(text):
        if c != "(":
            continue
        offset = max(0, k - 40)  # 先頭から切り出すと `(` の数 × ファイル長になる
        before = text[offset:k].rstrip()
        word = re.search(r"([A-Za-z_$][\w$]*)$", before)
        if (word and word.group(1) not in EXPR_WORDS) or before.endswith((")", "]")):
            continue  # 呼び出し・if・for の括弧
        # `async (` は async から
        start = offset + word.start() if word and word.group(1) == "async" else k
        heads.append((start, _body_open(text, k, arrow_only=True)))
    return heads


def _tree(nodes: dict[int, tuple[str, int]]) -> dict[int, int | None]:
    """開き括弧の位置 → いちばん内側で包む節の位置（無ければ None）。
    並べてスタックでたどる（組を総当たりしない）。"""
    parent: dict[int, int | None] = {}
    stack: list[int] = []
    for start in sorted(nodes):
        while stack and nodes[stack[-1]][1] < start:
            stack.pop()
        parent[start] = stack[-1] if stack else None
        stack.append(start)
    return parent


class _Layout:
    """関数・無名の関数・クラスの範囲と、包む関係。位置はどれも本体の開き括弧。

    dataclass にしないのは、sys.modules に登録せずに読み込まれたとき
    （spec_from_file_location）に落ちるため。
    """

    def __init__(self, text: str, src: str, named: dict[int, tuple[str, int]]) -> None:
        self.text, self.src, self.lines = text, src, text  # lines は行数を数える用
        # （measure_js が入れる。位置は text と同じ）
        self.named = named  # → (名前, 閉じ括弧の位置)
        self.unnamed: dict[int, int] = {}  # → 閉じ括弧の位置
        self.fields: list[int] = []  # 名前をフィールドの形から推したもの
        self.routes: list[int] = []  # 名前を呼び出しと文字列から推したもの
        self.classes: dict[int, tuple[str, int]] = {}
        self.parent: dict[int, int | None] = {}

    def add_anonymous(self) -> None:
        for head, body in sorted(_anonymous_heads(self.text), key=lambda hb: hb[0]):
            if body is None or body in self.named or body in self.unnamed:
                continue
            got = context_name(self.text, self.src, head)
            if got is None:
                self.unnamed[body] = close_of(self.text, body)
                continue
            self.named[body] = (got[0], close_of(self.text, body))
            if got[1] == "field":
                self.fields.append(body)
            elif got[1] == "route":
                self.routes.append(body)

    def demote_fields(self) -> None:
        """フィールドの形でも、包むのがクラスでなければ関数の中の代入（無名として畳む）。"""
        for body in self.fields:
            up = self.parent[body]
            while up is not None and up in self.unnamed:
                up = self.parent[up]
            if up is None or up not in self.classes:
                self.unnamed[body] = self.named.pop(body)[1]

    def fold_duplicate_routes(self) -> None:
        """同じ鍵（親の連鎖つき）のルートが 2 本以上なら全部畳む
        （`#2` の連番は並べ替えで値が入れ替わる）。

        畳むと中のルートの鍵が短くなり、新しく同名ができることがあるので、
        畳むものが無くなるまで繰り返す。
        """
        while True:
            keys: dict[str, list[int]] = {}
            for body in self.routes:
                keys.setdefault(self.qualname(body), []).append(body)
            folded = [body for bodies in keys.values() if len(bodies) > 1 for body in bodies]
            if not folded:
                return
            for body in folded:
                self.unnamed[body] = self.named.pop(body)[1]
                self.routes.remove(body)

    def named_parent(self, at: int) -> int | None:
        """いちばん内側で包む名前つきの関数（クラス・無名は飛ばす）。"""
        up = self.parent[at]
        while up is not None and up not in self.named:
            up = self.parent[up]
        return up

    def qualname(self, start: int) -> str:
        chain, up = [self.named[start][0]], self.parent[start]
        while up is not None:
            if up not in self.unnamed:
                chain.append((self.classes.get(up) or self.named[up])[0])
            up = self.parent[up]
        return ".".join(reversed(chain))

    def children(self) -> dict[int | None, list[tuple[int, int]]]:
        """包む名前つきの関数（外なら None）ごとの、入れ子の名前つきの関数の範囲
        （無名は外側に含める）。"""
        out: dict[int | None, list[tuple[int, int]]] = {}
        for start, (_, end) in self.named.items():
            out.setdefault(self.named_parent(start), []).append((start, end))
        return out

    def outermost_unnamed(self) -> list[tuple[int, int]]:
        """名前つきの関数に包まれない無名のうち、いちばん外側のもの
        （無名の中の無名は数え重ねない）。"""
        return [(s, e) for s, e in self.unnamed.items()
                if self.named_parent(s) is None
                and (self.parent[s] is None or self.parent[s] not in self.unnamed)]


def _layout(text: str, src: str) -> _Layout:
    lay = _Layout(text, src, _named_bodies(text))
    lay.add_anonymous()
    lay.classes = {m.end() - 1: (m.group(1), close_of(text, m.end() - 1))
                   for m in CLASS.finditer(text)}
    lay.parent = _tree({**lay.classes, **lay.named, **{s: ("", e) for s, e in lay.unnamed.items()}})
    lay.demote_fields()
    lay.fold_duplicate_routes()
    return lay


# ---- 数える ----

def _own(text: str, start: int, end: int, holes: list[tuple[int, int]]) -> str:
    """start〜end の中身から、holes（入れ子の関数の中身。重ならない前提）を除いた文字列。"""
    parts, at = [], start + 1
    for s, e in sorted(holes):
        parts.append(text[at:s])
        at = e + 1
    parts.append(text[at:end])
    return " ".join(parts)


def _nonblank(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _function_shapes(lay: _Layout, children: dict[int | None, list[tuple[int, int]]]
                     ) -> dict[str, tuple[int, int]]:
    funcs: dict[str, tuple[int, int]] = {}
    seen: dict[str, int] = {}  # 同じ鍵が何本目か（`while key in funcs` で探すと
    # 同名の本数の二乗になる）
    for start, (_, end) in sorted(lay.named.items()):
        own = _own(lay.text, start, end, children.get(start, []))
        qual = lay.qualname(start)
        seen[qual] = seen.get(qual, 0) + 1  # 同じ場所に同じ名前（ふつうは書かない）
        key = qual if seen[qual] == 1 else f"{qual}#{seen[qual]}"
        funcs[key] = (_nonblank(lay.lines[start + 1:end]), 1 + len(BRANCH.findall(own)))
    return funcs


def _top_level_shape(lay: _Layout, children: dict[int | None, list[tuple[int, int]]]
                     ) -> tuple[int, int] | None:
    """どの名前つきの関数にも入らない部分（モジュール直下・推せない無名）の (行数, 複雑度)。
    分岐はここに数える。

    行数は、いちばん外側の無名の中身から名前つきの入れ子を除いたもの
    （モジュール直下の宣言はファイルの行で見る）。
    """
    top = children.get(None, [])
    own = _own(lay.text, -1, len(lay.text), top)
    outside = list(lay.lines)
    for s, e in top:
        outside[s:e + 1] = " " * (e + 1 - s)
    outermost = lay.outermost_unnamed()
    lines = sum(_nonblank("".join(outside[s + 1:e])) for s, e in outermost)
    branches = len(BRANCH.findall(own))
    return (lines, 1 + branches) if outermost or branches else None


def measure_js(src: str) -> tuple[int, dict[str, tuple[int, int]]] | None:
    """(実行行, {関数名: (中身の行数, 複雑度)})。括弧の対応が取れなければ None（読めなかった）。"""
    text = strip_js(src)
    if not balanced(text):
        return None
    lay = _layout(text, src)
    lay.lines = blank_jsx_comments(src, text, set(lay.named) | set(lay.unnamed) | set(lay.classes))
    children = lay.children()
    funcs = _function_shapes(lay, children)
    if top := _top_level_shape(lay, children):
        funcs[TOP_LEVEL] = top
    return _nonblank(lay.lines), funcs
