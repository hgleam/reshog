"""すべてのテストが、いずれかのゲートから実際に走ることを固定する。

**なぜ要るか**: pre-commit にテストのファイル名を手書きで並べると、テストを足しても
リストに書かない限り実行されない。そして pytest は、収集する形（`def test_`・`async def test_`・
`class Test…`）を持たない script 形式
（読み込むと検査が走り、終了コードで返す形）を**収集しない**。この2つが重なると、
**どのゲートからも一度も実行されないテスト**が生まれる。

**誰も落ちないので気づけない。** ファイルは存在し、中身も正しく、走らせれば通る。
ただ一度も走っていないだけ。実際に1つのリポジトリで19本中5本がこの状態だった。

対策は2つで、両方が要る:

1. pre-commit の列挙を **glob** にする（書き忘れが構造的に起きない）
2. 走らせ方を**形式で振り分ける**。逆にすると静かに壊れる:
   - script 形式を pytest に渡す → 収集されず、何も検証されない
   - pytest 形式を `python3` で叩く → 関数が定義されるだけで**終了コード0**＝常に緑の空検査

pre-commit 側の実装（このテストが要求する形）:

```bash
pytest_targets=()
for t in tests/test_*.py; do
  [ -f "$t" ] || continue
  if grep -qE '^(async[[:space:]]+)?def test_|^class Test' "$t"; then
    pytest_targets+=("$t"); continue;
  fi
  if ! out=$(python3 "$t" 2>&1); then
    echo "⚠  $t が失敗:"; printf '%s\n' "$out" | tail -20; exit 1;
  fi
done
[ ${#pytest_targets[@]} -gt 0 ] && { uv run pytest -q "${pytest_targets[@]}" || exit 1; }
```

**コピー後に直す箇所**: `MAX_NAMED`
（順序の都合で名指しするテストの本数。既定 1＝秘匿情報の検査だけ）。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".githooks" / "pre-commit"  # Python リポ専用の雛形（husky の Node リポには入れない）
TESTS = sorted((ROOT / "tests").glob("test_*.py"))

# pytest が収集する形式。関数・async 関数・クラス（`class TestX`）のどれか。クラス形式を見落とすと
# pre-commit がそれを `python3` で叩き、終了コード 0 の空検査になる。
# 逆に script 形式（`__main__` で動く）に `class TestX` を混ぜると pytest 側に回り、
# script の検査は走らない。
PYTEST_STYLE = re.compile(r"^(?:async\s+)?def test_|^class Test", re.M)

# 「秘匿情報の検査を最初に見る」等、順序の都合で名指しするものだけ許す本数。
MAX_NAMED = 1


def _hook_text() -> str:
    return HOOK.read_text(encoding="utf-8")


def test_hook_enumerates_tests_by_glob() -> None:
    """列挙を glob に任せていること。手書きに戻したら落とす。"""
    assert re.search(r"for\s+\w+\s+in\s+tests/test_\*\.py", _hook_text()), (
        "pre-commit がテストを glob で列挙していない（手書きリストは書き忘れる）"
    )


def test_hook_has_no_handwritten_test_list() -> None:
    named = set(re.findall(r"tests/test_[a-z0-9_]+\.py", _hook_text()))
    assert len(named) <= MAX_NAMED, f"pre-commit にテスト名が手書きされている: {sorted(named)}"


def test_hook_dispatches_by_format() -> None:
    """形式で振り分けていること。片方に寄せると静かに空振りする。"""
    text = _hook_text()
    assert "def test_" in text, "pytest 形式か script 形式かを判定していない"
    assert "class Test" in text, "クラス形式（class TestX）を pytest 形式と判定していない"
    assert "pytest" in text, "pytest 形式のテストを走らせていない"
    # 自動実行も uv 経由に揃える（rules/python-dependency-management.md）ので
    # `uv run python` も認める
    assert re.search(r"\bpython3\b|\buv run python\b", text), "script 形式のテストを走らせていない"


def test_every_test_file_is_runnable_by_some_runner() -> None:
    """どのファイルも「pytest が拾える」か「単体実行で検査が走る」かのどちらかであること。"""
    inert = []
    for path in TESTS:
        text = path.read_text(encoding="utf-8")
        pytest_style = PYTEST_STYLE.search(text)
        # script 形式は `sys.exit(` が if の中にあることが多いので行頭に縛らない
        script_style = "__main__" in text or "sys.exit(" in text
        if not (pytest_style or script_style):
            inert.append(path.name)
    assert not inert, f"どのゲートからも実行されないテスト: {inert}"


def test_hook_grep_matches_pytest_style() -> None:
    """フックの grep 式が PYTEST_STYLE と同じものを拾うこと。

    片方だけ直すと、もう片方で空検査が残る。
    """
    found = re.search(r"grep -qE '([^']*def test_[^']*)'", _hook_text())
    assert found, "フックに、pytest 形式を判定する grep -qE '…def test_…' が見つからない"
    hook = re.compile(found.group(1).replace("[[:space:]]", r"\s"), re.M)
    samples = ["def test_a(): ...", "async def test_a(): ...", "class TestX:\n    pass",
               "def helper(): ...", "class Helper: ...", "    def test_a(self): ..."]
    for text in samples:
        assert bool(hook.search(text)) == bool(PYTEST_STYLE.search(text)), text


def test_runner_detection_positive_control() -> None:
    """陽性対照: 判定が関数・async・クラスの各形式を拾い、ただの関数を拾わない。"""
    assert PYTEST_STYLE.search("def test_a(): ...")
    assert PYTEST_STYLE.search("async def test_a(): ...")
    assert PYTEST_STYLE.search("class TestX:\n    def test_a(self): ...")
    assert not PYTEST_STYLE.search("def helper(): ...")
    assert not PYTEST_STYLE.search("class Helper: ...")


def test_there_are_tests_to_check() -> None:
    """対象が0件だと、この検査は常に緑になる（空振りの検出）。"""
    assert TESTS, "tests/test_*.py が1つも無い"
