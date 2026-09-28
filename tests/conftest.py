"""テスト共通の道具。"""

from collections.abc import Callable

import pytest


def _cell(rendered: str, pid: int, column: str) -> str:
    """描画済みの表から、PID の行の指定列のセルを取り出す。

    「行のどこかに - がある」で見ると、別の列の - に当たって素通りする。
    見出しの並びと突き合わせて、列を名指しで取る。
    """
    lines = rendered.splitlines()
    header = next(ln for ln in lines if f"┃ {column}" in ln or f"{column} ┃" in ln)
    names = [c.strip() for c in header.strip().strip("┃").split("┃")]
    row = next(
        ln
        for ln in lines
        if "│" in ln and str(pid) in [c.strip() for c in ln.strip().strip("│").split("│")]
    )
    cells = [c.strip() for c in row.strip().strip("│").split("│")]
    return dict(zip(names, cells, strict=True))[column]


@pytest.fixture
def cell() -> Callable[[str, int, str], str]:
    """`cell(rendered, pid, column)` で表のセルを返す関数。"""
    return _cell

