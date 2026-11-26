"""行数を数える用に、JSX の説明 `{/* … */}` の括弧を空白にする（js/shape.py が使う）。

説明は実行行に数えない（数えると、説明を書くほど行数の門が鳴り、説明を書かなくなる）。
関数の範囲を取る文字列
（strip_js の出力）には手を入れず、行数を数える用の写しだけを変える
（範囲を取る側から括弧を消すと、コメントだけの
本体を持つ関数が一覧から黙って落ちる）。
JSX の子かどうかは「子でない」を既定にし、直前（JSX の地の文は飛ばす）が
タグの閉じ `>` か、JSX の式の `}` のときだけ子とみなす
（制御文・型の宣言・引数のオブジェクトのコメントだけの `{ }` は
数え続ける）。

後ろへ戻る走査は SCAN_LIMIT 文字で打ち切り、打ち切ったら子でないとみなす
（行を数える側に倒す。1 つの `{` の手間が
一定になり、全体は件数に比例する）。地の文は `;` を越えて戻らず、
戻った区間にコードの語（CODE_WORDS）があれば子でないとみなす。
限界: 地の文が `;` を含むか（`A&nbsp;B`・`&amp;` など）、
NOT_CHILD_AFTER の文字（`)` `=` `,` `(` `[` `:` `?` `|` `&` `+`。`C++`・`合計 +` など）で終わるか、
コードの語（英語の for など）を含むか、
空白なしで開きタグに続く（`foo<b>`）ときの直後の説明は数える側に、
.ts の古い型の断定 `<T>{ … }` と、
セミコロンを書かずに JSX で終わる文の直後の裸のブロック（`const a = <b/>` の次の行の
`{/* … */}`）と、
セミコロンを書かずに前の行に比較の `<` がある `a > b` の直後のブロックは消す側に倒れる。
縮めた（minify した）JS は測る対象の外（SKIP の dist・build・public）に置く前提。
"""

from __future__ import annotations

import re

#: 後ろへ戻る走査の上限（タグの頭・地の文の頭までの文字数。
#: これより長いタグ・地の文は子でないとみなす）
SCAN_LIMIT = 1000
#: 直後の `{` を JSX の子とみなさない文字
#: （制御文・呼び出し・代入・引数・配列・型の注記・三項・演算子の後ろ）
NOT_CHILD_AFTER = ")=,([:?|&+"
#: タグの頭までに出てよい文字（英数字・空白のほか。名前の `_` `$`・属性の `=` `"` `'` `-`・
#: 部品の `.`・名前空間の `:`・閉じの `/`・型引数の `,`）。
#: 属性の `{ … }` は対の括弧で飛ばすので、中のバッククォートなどはここに要らない
TAG_CHARS = "_$=\"'.:-/,"
#: 地の文に出ればコードとみなす語
#: （JSX で終わる文の後ろの `else {/* */}`・`interface P {/* */}` を子と取り違えない）
CODE_WORDS = re.compile(r"\b(?:else|try|finally|do|return|if|for|while|switch|interface|enum|"
                        r"namespace|class|type|"
                        r"declare|module|function|const|let|var|import|export|static)\b")


def blank_jsx_comments(src: str, text: str, bodies: set[int]) -> str:
    """text（strip_js の出力）のうち、JSX の子の位置にあり、
    元にコメントだけがあった `{ }` の括弧を空白にする。

    bodies は関数・クラスの本体の開き括弧の位置。改行と長さは保つ。
    text を 1 回走査して括弧の対を取るので、
    閉じない `{/*` が並んでも件数の二乗にならない。
    """
    pairs = _brace_pairs(text)
    opens = {close: start for start, (close, _) in pairs.items()}
    out = list(text)
    # JSX の子の位置にある `{`（後ろに並ぶ `{ }` が JSX の子かを、直前の `}` から引く）
    jsx: set[int] = set()
    for start in sorted(pairs):
        if start in bodies or not _jsx_child_at(text, start, opens, jsx):
            continue
        jsx.add(start)
        close, empty = pairs[start]
        if empty and src[start + 1:close].strip():  # 消した後は空白だけで、元にはコメントがあった
            out[start] = out[close] = " "
    return "".join(out)


def _brace_pairs(text: str) -> dict[int, tuple[int, bool]]:
    """`{` の位置 → (対の `}` の位置, 中身が空白だけか)。"""
    pairs: dict[int, tuple[int, bool]] = {}
    stack: list[list] = []  # [開き括弧の位置, 中に空白以外があったか]
    for i, c in enumerate(text):
        if c == "}" and stack:
            start, seen = stack.pop()
            pairs[start] = (i, not seen)
        if stack and not c.isspace():
            stack[-1][1] = True
        if c == "{":
            stack.append([i, False])
    return pairs


def _jsx_child_at(text: str, at: int, opens: dict[int, int], jsx: set[int]) -> bool:
    k = _solid_before(text, at)
    # `;` の後ろは、地の文を戻る走査（_text_start）が `;` で止めて落とす
    if k < 0 or text[k] in NOT_CHILD_AFTER:
        return False
    j = _text_start(text, k)
    if j >= 0 and text[j] == "}":
        return opens.get(j) in jsx
    # `=>` の `>` はタグの頭が見つからず落ちる
    return j >= 0 and text[j] == ">" and _is_tag_end(text, j, opens)


def _solid_before(text: str, at: int) -> int:
    """at より前で、空白でない最後の文字の位置（無ければ -1）。"""
    k = at - 1
    while k >= 0 and text[k].isspace():
        k -= 1
    return k


def _text_start(text: str, k: int) -> int:
    """k から JSX の地の文（`{}<>;` を含まない）を戻り、最初に当たる `{}<>` の位置。
    上限まで無い・`;` に当たった・戻った区間にコードの語があれば -1。"""
    j, stop = k, max(k - SCAN_LIMIT, -1)
    while j > stop and text[j] not in "{}<>;":
        j -= 1
    # `;` に当たったら、呼び出し側で子でないとみなす
    if j <= stop or CODE_WORDS.search(text, j + 1, k + 1):
        return -1
    return j


def _is_tag_end(text: str, k: int, opens: dict[int, int]) -> bool:
    """k の `>` がタグの閉じか（型引数の `Props<T>` の閉じではないか）。"""
    j = _tag_open(text, k, opens)
    if j < 0:
        return False
    # 閉じタグ（`x</b>`）は前が地の文でもタグ。型引数は `<` の前が名前
    return text[j + 1:j + 2] == "/" or not (j > 0 and _is_name(text[j - 1]))


def _tag_open(text: str, k: int, opens: dict[int, int]) -> int:
    """k の `>` に対応するタグの頭の `<` の位置。
    属性の `{ … }` は飛ばし、`<List<T>>` の内側の `<T>` は入れ子として
    数える。タグに出ない文字に当たる・上限まで見つからなければ -1。"""
    j, depth, stop = k - 1, 0, max(k - SCAN_LIMIT, -1)
    while j > stop:
        c = text[j]
        if c == "<" and depth == 0:
            return j
        depth += (c == ">") - (c == "<")
        if c == "}":
            j = opens.get(j, j)
        elif c not in "<>" and not _tag_char(c):
            return -1
        j -= 1
    return -1


def _tag_char(c: str) -> bool:
    return c.isalnum() or c.isspace() or c in TAG_CHARS


def _is_name(c: str) -> bool:
    return c.isalnum() or c in "_$"
