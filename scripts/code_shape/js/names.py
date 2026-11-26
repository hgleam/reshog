"""無名の関数に、置かれた場所から名前を推す（shape.py が使う）。

推すのは `const f =`・`key:`・クラスのフィールド・`export default`・
第 1 引数が文字列のメソッド呼び出し（ルートの登録）。
推せる書き方・推さない書き方の一覧は shape.py の説明。
"""

from __future__ import annotations

import re

from ..constants import CONTEXT_NAMES, ROUTE_CALL


def context_name(text: str, src: str, at: int) -> tuple[str, str] | None:
    """無名の関数に、置かれた場所から (名前, 推した形) を推す（推せなければ None）。
    形は "field"・"route"・""。

    フィールドの形（`x = () => {}`）は関数の中の代入と見分けられないので、
    包むものがクラスのときだけ名前にする
    （判定は _Layout.demote_fields）。
    コールバックは、第 1 引数が文字列のメソッド呼び出し（ルートの登録）だけ推す。
    text は文字列の中身を空白にしたもの、
    src は元の文字列（位置は同じ。文字列の中身は src から取る）。
    """
    offset = max(0, at - 300)
    before = text[offset:at].rstrip()
    before = re.sub(r"<[^<>()]*>$", "", before).rstrip()  # const id = <T,>(x) =>
    before = re.sub(r"\basync$", "", before).rstrip()
    for pat, kind in CONTEXT_NAMES:
        m = pat.search(before)
        if m:
            return m.group(1), kind
    if re.search(r"\bexport\s+default$", before):
        return "default", ""
    m = ROUTE_CALL.search(before)
    if m:
        callee = re.sub(r"\s|\?", "", m.group(1))  # 改行をはさむ連鎖・`?.` も同じ鍵
        return f'{callee}("{src[offset + m.start(3):offset + m.end(3)]}")', "route"
    return None
