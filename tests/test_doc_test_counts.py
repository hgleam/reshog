"""testing.md のテスト件数表が、pytest の実際の収集数と一致するか検証する。

件数表は手で書くので、テストを足すたびに古くなる。しかも古くても何も壊れないため、
誰も気づかない(実例: test_cli_smoke.py が表では 7 件・実際は 17 件、test_cpu.py は行ごと無かった)。
**正本＝pytest の収集結果**として照合する。

照合するもの:
  - tests/ の test_*.py が全部、表に 1 行ずつある(漏れ)
  - 表の行が全部、実在するファイルを指している(幽霊)
  - 各行の件数 = そのファイルの収集数
  - 本文の「合計 N」= 全ファイルの収集数の和
"""

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "specification" / "develop" / "testing.md"

# | `test_x.py` | 12 | ... |
_ROW = re.compile(r"^\|\s*`(test_[\w]+\.py)`\s*\|\s*(\d+)\s*\|", re.MULTILINE)
_TOTAL = re.compile(r"合計\s*(\d+)")


def _collected() -> Counter[str]:
    """pytest の収集数をファイルごとに数える(parametrize 展開後)。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    counts: Counter[str] = Counter(
        Path(line.split("::", 1)[0]).name for line in result.stdout.splitlines() if "::" in line
    )
    # 母集団が空なら収集そのものが壊れている。0 件どうしで「一致」させない。
    assert counts, f"pytest の収集結果が空です:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    return counts


def test_table_matches_collected_counts() -> None:
    text = DOC.read_text(encoding="utf-8")
    rows = {name: int(n) for name, n in _ROW.findall(text)}
    collected = _collected()
    files = {p.name for p in (REPO / "tests").glob("test_*.py")}

    missing = sorted(files - rows.keys())
    ghosts = sorted(rows.keys() - files)
    wrong = sorted(
        f"{name}: 表 {rows[name]} / 実際 {collected[name]}"
        for name in rows.keys() & files
        if rows[name] != collected[name]
    )
    assert not missing, f"testing.md の件数表に行がありません: {missing}"
    assert not ghosts, f"testing.md の件数表に存在しないファイルがあります: {ghosts}"
    assert not wrong, "testing.md の件数が実際の収集数と違います:\n" + "\n".join(wrong)

    total = _TOTAL.search(text)
    assert total, "testing.md に「合計 N」がありません"
    assert int(total.group(1)) == sum(collected.values()), (
        f"testing.md の合計 {total.group(1)} / 実際 {sum(collected.values())}"
    )
