"""TypeScript / JavaScript のコメントを消し、文字列・テンプレート・正規表現の中身を空白にする。
消した後の括弧の対応も見る（どちらも shape.py が使う）。

改行と長さは保つ（位置がそのまま元のソースの位置になる）。
テンプレート文字列の `${ ... }` の中はコードとして残す
（入れ子のテンプレートも同じ）。
行末までに閉じない ' " / は文字列・正規表現と見ない（JSX の文の `Don't` 等）。
"""

from __future__ import annotations

import re

from ..constants import REGEX_AFTER, STRING_AFTER, WORD_WINDOW


class _Stripper:
    """strip_js の走査（位置・直前の意味のある文字とその位置を持つ）。"""

    def __init__(self, src: str) -> None:
        self.src, self.out, self.n = src, list(src), len(src)
        self.i = 0
        self.prev = ""  # 直前の意味のある文字（正規表現か割り算かの見分けに使う）
        self.prev_at = -1  # その位置（間の空白・改行がいくつあっても、ここから語を取る）
        self.depth = 0  # コードの `{` の深さ
        # 入っている `${` の、入ったときの深さ（対応する `}` でテンプレートへ戻る）
        self.templates: list[int] = []

    def run(self) -> str:
        while self.i < self.n:
            self._step()
        return "".join(self.out)

    def _step(self) -> None:
        c, nxt = self.src[self.i], self.src[self.i + 1:self.i + 2]
        if c == "/" and nxt in ("/", "*"):
            self._comment(nxt)
        elif c == "'" and self._apostrophe():
            self._mark(c, self.i)
            self.i += 1
        elif c == "`":
            self._template(self.i + 1)
        elif c in "'\"" or (c == "/" and self._regex_starts()):
            self._literal(c)
        else:
            self._code(c)

    def _code(self, c: str) -> None:
        if c == "}" and self.templates and self.depth == self.templates[-1]:
            self.templates.pop()  # `${ ... }` の閉じ: テンプレートの続きへ
            self._blank(self.i, self.i + 1)
            self._template(self.i + 1)
            return
        self.depth += (c == "{") - (c == "}")
        if not c.isspace():
            self._mark(c, self.i)
        self.i += 1

    def _template(self, start: int) -> None:
        """テンプレート文字列の地の文を start から消す。
        `${` に来たら、そこからはコードとして読む（入れ子も同じ）。"""
        j = start
        while j < self.n and self.src[j] != "`" and not self.src.startswith("${", j):
            j += 2 if self.src[j] == "\\" else 1
        self._blank(start, min(j, self.n))
        if j < self.n and self.src[j] == "`":
            self._mark("a", j)
            self.i = j + 1
        elif j < self.n:
            self._blank(j, j + 2)
            self.templates.append(self.depth)
            self._mark("(", j + 1)  # 式の始まり（直後の `/` は正規表現）
            self.i = j + 2
        else:
            self.i = self.n

    def _mark(self, c: str, at: int) -> None:
        self.prev, self.prev_at = c, at

    def _blank(self, a: int, b: int) -> None:
        for k in range(a, b):
            if self.out[k] != "\n":
                self.out[k] = " "

    def _comment(self, kind: str) -> None:
        if kind == "/":
            j = self.src.find("\n", self.i)
            j = self.n if j < 0 else j
        else:
            j = self.src.find("*/", self.i + 2)
            j = self.n if j < 0 else j + 2
        self._blank(self.i, j)
        self.i = j

    def _apostrophe(self) -> bool:
        """識別子の直後の ' はアポストロフィ（JSX の文の `It's`・`users'`）。
        JS で文字列は識別子に続かない
        （キーワードの直後 `case'a'`・`return'a'` は除く）。"""
        i, src = self.i, self.src
        # 数字・日本語の直後も（`1990's`）
        if i == 0 or not (src[i - 1].isalnum() or src[i - 1] in "_$"):
            return False
        word = re.search(r"([A-Za-z_$][\w$]*)$", src[max(0, i - WORD_WINDOW):i])
        return not word or word.group(1) not in REGEX_AFTER | STRING_AFTER

    def _regex_starts(self) -> bool:
        prev, at = self.prev, self.prev_at
        if prev == "<":  # JSX の `</div>`
            return False
        if at > 0 and "".join(self.out[at - 1:at + 1]) in ("++", "--"):  # コメントを消した後で見る
            return False  # `n++ / 2` は割り算
        # `}` の直後は割り算と見る（JSX の `{a}/{b}`・`<Foo b={1} />`。
        # ブロックの直後の行頭の正規表現はまれで、当たっても unreadable に出る）
        if prev == "" or prev in "(,=:[!&|?{;+-*%<>~^":
            return True
        word = re.search(r"([A-Za-z_$][\w$]*)$", self.src[max(0, at + 1 - WORD_WINDOW):at + 1])
        return bool(word) and word.group(1) in REGEX_AFTER

    def _literal_end(self, c: str) -> int:
        """引用・正規表現の閉じの位置（閉じないまま行末・末尾に来たらその位置）。"""
        j, in_class = self.i + 1, False
        while j < self.n:
            d = self.src[j]
            if d == "\\":
                j += 2
                continue
            if c == "/" and d in "[]":
                in_class = d == "["
            elif (d == c and not in_class) or (d == "\n" and c in "'\"/"):
                break
            j += 1
        return j

    def _literal(self, c: str) -> None:
        j = self._literal_end(c)
        if c in "'\"/" and (j >= self.n or self.src[j] != c):
            # 行末までに閉じない: JS では文字列・正規表現になりえない（JSX の文の `Don't` 等）
            self._mark(c, self.i)
            self.i += 1
            return
        self._blank(self.i + 1, min(j, self.n))
        # 閉じた引用の位置（語ではないので、後ろの語の判定に効かない）
        self._mark("a", min(j, self.n - 1))
        self.i = j + 1


def strip_js(src: str) -> str:
    """コメントを消し、文字列・テンプレート・正規表現の中身を空白にする
    （改行と長さは保つ。括弧には手を入れない）。"""
    return _Stripper(src).run()


# ---- 消した後の括弧の対応 ----

def balanced(text: str) -> bool:
    """括弧の対応が取れているか（取れていなければ、関数の範囲を正しく取れない）。"""
    depth = {"{": 0, "(": 0}
    for c in text:
        if c in "{(":
            depth[c] += 1
        elif c in "})":
            depth["{" if c == "}" else "("] -= 1
            if min(depth.values()) < 0:
                return False
    return not any(depth.values())


def close_of(text: str, open_at: int) -> int:
    """open_at の括弧（( か {）に対応する閉じ括弧の位置。"""
    pair = {"(": ")", "{": "}"}[text[open_at]]
    depth = 0
    for k in range(open_at, len(text)):
        if text[k] == text[open_at]:
            depth += 1
        elif text[k] == pair:
            depth -= 1
            if depth == 0:
                return k
    return len(text) - 1


def skip_space(text: str, k: int) -> int:
    while k < len(text) and text[k].isspace():
        k += 1
    return k
