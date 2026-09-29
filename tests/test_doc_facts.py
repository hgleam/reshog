"""【雛形】文書の数値・既定値がコードの実値と一致するか検証する（正本＝コード）。

**コピー後に FACTS を書く**（空のままだと FAIL する）。他は触らなくてよい。

コード側の定数を変えて文書が古いままでも、通常のテストは緑のまま通る。
更新間隔・件数・上限値・既定のモデル名などは実装から照合できるので機械化する。

FACTS の各エントリ:
  label       … 失敗時の表示名
  source      … (ファイル, 正規表現) 実値を1つ捕獲するグループを持たせる
  count       … 正本が個数のとき: (モジュールパス, 属性名) を import して len()
  doc_pattern … 文書側で値を拾う正規表現（捕獲グループ1つ）
                同じ行に単位語やキー名を含めると精度が上がる

標準ライブラリのみ。実行: python3 tests/test_doc_facts.py -> 末尾に ALL_PASS
"""
import glob
import importlib.util
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# 過去の記述（当時の値）を保存する場所は照合しない。
SKIP_DOCS = {"docs/devlog.md"}

# GPU 常駐の判定しきい値は memory-detection.md が定数表で説明している。閾値を変えたのに
# 文書が古いと「なぜこの警告が出た/出ない」の説明が食い違うため、実装を正本に照合する。
FACTS: list[dict] = [
    {
        "label": "表示件数の既定（--count）",
        "source": ("src/reshog/cli.py", r"count: int = typer\.Option\((\d+),"),
        "doc_pattern": r"既定\s*(\d+)\s*件",
    },
    {
        "label": "GPU 常駐判定の下限（HIDDEN_GPU_MIN_MB）",
        "source": ("src/reshog/constants.py", r"HIDDEN_GPU_MIN_MB = (\d+)"),
        "doc_pattern": r"`HIDDEN_GPU_MIN_MB`\s*\|\s*`(\d+)`",
    },
    {
        "label": "GPU 常駐判定の倍率（HIDDEN_GPU_RSS_RATIO）",
        "source": ("src/reshog/constants.py", r"HIDDEN_GPU_RSS_RATIO = (\d+)"),
        "doc_pattern": r"`HIDDEN_GPU_RSS_RATIO`\s*\|\s*`(\d+)`",
    },
    {
        "label": "--group の走査幅の下限（GROUP_SAMPLE_MIN）",
        "source": ("src/reshog/constants.py", r"GROUP_SAMPLE_MIN = (\d+)"),
        "doc_pattern": r"`GROUP_SAMPLE_MIN = (\d+)`",
    },
    {
        "label": "コマンド表示の最大長（MAX_CMD）",
        "source": ("src/reshog/constants.py", r"MAX_CMD = (\d+)"),
        "doc_pattern": r"`MAX_CMD = (\d+)`",
    },
]
# ---------------------------------------------------------------------------


def read(rel: str) -> str:
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def markdown_files() -> list[str]:
    out = []
    for pattern in ("README.md", "docs/**/*.md"):
        for path in glob.glob(os.path.join(REPO, pattern), recursive=True):
            rel = os.path.relpath(path, REPO)
            if rel not in SKIP_DOCS:
                out.append(rel)
    return sorted(set(out))


def load_attr(rel: str, attr: str):
    """データモジュールから属性を読む（件数を正本にする FACTS 用）。"""
    spec = importlib.util.spec_from_file_location(
        "_facts_src", os.path.join(REPO, rel)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, attr)


def truth(fact: dict) -> str | None:
    """その事実の正本の値。取れなければ None。"""
    if "count" in fact:
        rel, attr = fact["count"]
        return str(len(load_attr(rel, attr)))
    rel, pattern = fact["source"]
    m = re.search(pattern, read(rel))
    return m.group(1) if m else None


docs = {rel: read(rel) for rel in markdown_files()}

# 件数の閾値で落とすと最小構成のプロジェクトで雛形が最初から赤くなる（dedup で踏んだ）。
checks = [("照合対象の Markdown を発見できている", len(docs) >= 1)]
if not FACTS:
    checks.append(("FACTS が定義されている", False))

for fact in FACTS:
    want = truth(fact)
    label = fact["label"]
    if want is None:
        checks.append((f"{label}: 正本を読めている", False))
        continue
    bad = []
    for rel, body in docs.items():
        for line in body.splitlines():
            for got in re.findall(fact["doc_pattern"], line):
                if got != want:
                    bad.append(f"{rel}: {got}")
    checks.append((f"{label} が実値 {want} と一致"
                   f"（不一致: {sorted(set(bad)) or 'なし'}）", not bad))


def failures() -> list[str]:
    """満たされていない検査項目のラベル。"""
    return [label for label, res in checks if not res]


def test_doc_facts() -> None:
    """pytest から収集されたときも同じ検査を行う。

    トップレベルで raise SystemExit すると pytest が INTERNALERROR になり
    既存のテスト実行ごと壊れる（実測）。レポート出力は __main__ 側に置く。
    """
    assert not failures(), "\n".join(failures())


if __name__ == "__main__":
    ok = True
    for label, res in checks:
        print(("PASS " if res else "FAIL ") + label)
        ok = ok and bool(res)
    print()
    print("ALL_PASS" if ok else "HAS_FAILURE")
    raise SystemExit(0 if ok else 1)
