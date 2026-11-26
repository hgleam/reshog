"""コードの形のラチェット（悪化した向きだけ落とす。標準ライブラリのみ）。
台帳は docs/metrics/code-shape.json。

- 予算内は自由に増やせる
- **すでに予算を超えているものは、1 も増やせない**
- **新しく予算を超えるものを作らない**
- 予算を超えている箇所の総数を増やさない
- 読めなかった（測れていない）ファイルを増やさない（測れないものは、どれだけ膨らんでも鳴らないため）

増やすなら `python3 scripts/code_shape --update-baseline <直したファイル…>` で、
その行だけ台帳を書き直す（差分に出て目に入る）。
ディレクトリの指標（dirs・prefixes）は、名指ししたファイルの親ディレクトリの行も書き直す
（束ねたら動かしたファイルを名指し）。
雛形の更新で指標が増えたら `--add-missing-kinds`（無い指標の行だけ足す）。
減らしたら同じコマンドで台帳を下げる（下げないと、次に増やしても気づけない余白が残る）。
引数なしの全体の書き直しは
台帳の作成・作り直しだけに使う（別の変更が積んだ増加まで黙って入るため）。
絶対値の合否にしないのは、普通の作業で鳴り続ける門は無視されるから。

コピー後に直すのは BUDGET（健全の目安）と MIN_FILES / MIN_FUNCTIONS（走査が空振りしていない目安）。
測り方は scripts/code_shape/（同じく init の雛形）。

実行: python3 tests/test_code_shape_ratchet.py   -> 末尾に ALL_PASS（pytest からも収集される）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))  # scripts/code_shape/（パッケージ）を import する
import code_shape as shape_mod  # noqa: E402

#: 健全の目安（code-complexity-audit スキルの目安）。
#: 導入したら `python3 scripts/code_shape` の分布を見て、
#: 90 パーセンタイルより少し上に置く。下げすぎると普通の作業で鳴り、無視される。
#: dirs（ディレクトリ直下の実装ファイル）は 15 本、
#: prefixes（名前の頭が同じ兄弟ファイル）は 2 本まで。
#: 3 本並んだら、名前でディレクトリを代用している（`receipt-*.ts` → `receipt/`）。
BUDGET = {"files": 300, "functions": 60, "complexity": 15, "per_file": 25, "dirs": 15,
          "prefixes": 2}
LABEL = {"files": "ファイルの実行行", "functions": "関数の中身の行数", "complexity": "関数の複雑度",
         "per_file": "ファイルあたりの関数の本数", "dirs": "ディレクトリ直下の実装ファイルの本数",
         "prefixes": "名前の頭が同じ兄弟ファイルの本数（ディレクトリに束ねる合図）"}
#: 走査の母集団の下限（導入時の件数の 8 割ほど）。これを割ったら、測る場所の指定が壊れている。
MIN_FILES = 23  # 実測 29 本の 8 割
MIN_FUNCTIONS = 170  # 実測 212 本の 8 割


def grew_while_over_budget(kind: str, now: dict, base: dict) -> list[str]:
    """すでに予算を超えているのに増えたもの（判定の正本。陽性対照もこれを呼ぶ）。"""
    budget = BUDGET[kind]
    return [f"{name}: {base[kind][name]} → {v}（予算 {budget}）" for name, v in now[kind].items()
            if name in base[kind] and base[kind][name] > budget and v > base[kind][name]]


def born_over_budget(kind: str, now: dict, base: dict) -> list[str]:
    """新しく予算を超えたもの（判定の正本）。"""
    budget = BUDGET[kind]
    return [f"{name}: {v}（予算 {budget}）" for name, v in now[kind].items()
            if v > budget and base[kind].get(name, 0) <= budget]


def over_count(d: dict) -> int:
    return sum(1 for kind, budget in BUDGET.items() for v in d.get(kind, {}).values() if v > budget)


def checks(now: dict, base: dict | None) -> list[tuple[str, bool]]:
    if base is None:
        return [(f"台帳がある（無い: {shape_mod.BASELINE}。"
                 "`python3 scripts/code_shape --update-baseline` で作る）",
                 False)]
    missing = [k for k in shape_mod.KINDS if k not in base]
    if missing:  # 雛形の更新で増えた指標。空として比べると、
        # いまある借金が全部「新しく超えた」に見える
        return [(f"台帳に指標がある（無い: {missing}。"
                 "`python3 scripts/code_shape --add-missing-kinds` で足す）", False)]
    unreadable = sorted(set(now.get("unreadable", {})) - set(base.get("unreadable", {})))
    base = {k: base.get(k, {}) for k in shape_mod.KINDS}
    impl = len(now["per_file"])  # 実装のファイル（files にはテストも入るので水増しを避ける）
    # 関数もテストの補助関数が入るので、実装のファイルの関数だけ数える
    funcs = sum(1 for k in now["functions"] if k.split("::", 1)[0] in now["per_file"])
    out = [(f"走査が空振りしていない（実装のファイル {impl}・関数 {funcs}）",
            impl >= MIN_FILES and funcs >= MIN_FUNCTIONS)]
    # 置き場が無いと、そこのテストを黙って測らない（空振りの下限は実装のファイルしか数えない）
    absent = [d for d in shape_mod.TEST_TARGETS if not (shape_mod.ROOT / d).is_dir()]
    out.append((f"テストの置き場が全部ある（無い: {absent or 'なし'}）", not absent))
    for kind in shape_mod.KINDS:
        worse, born = grew_while_over_budget(kind, now, base), born_over_budget(kind, now, base)
        out.append((f"{LABEL[kind]}: 予算超えのものが増えていない（{worse or 'なし'}）", not worse))
        out.append((f"{LABEL[kind]}: 新しく予算を超えたものが無い（{born or 'なし'}）", not born))
    before, after = over_count(base), over_count(now)
    out.append((f"予算超えの総数が増えていない（{before} → {after}）", after <= before))
    out.append((f"読めなかったファイルが増えていない（{unreadable or 'なし'}）", not unreadable))
    return out


def _load() -> tuple[dict, dict | None]:
    base_path = shape_mod.BASELINE
    base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else None
    return shape_mod.measure(), base


def failures() -> list[str]:
    now, base = _load()
    return [label for label, ok in checks(now, base) if not ok]


def test_the_ratchet_bites() -> None:
    """陽性対照: 判定の正本そのものが、増加・新規の超過を挙げ、
    予算内の増減と借金の返済は挙げない。"""
    for kind in shape_mod.KINDS:
        b = BUDGET[kind]
        base = {k: {} for k in shape_mod.KINDS}
        base[kind] = {"over": b + 5, "inside": b - 1}
        now = {k: {} for k in shape_mod.KINDS}
        now[kind] = {"over": b + 6, "inside": b + 1, "new": b + 1}
        assert [h.split(":")[0] for h in grew_while_over_budget(kind, now, base)] == ["over"]
        assert sorted(
            h.split(":")[0] for h in born_over_budget(kind, now, base)
        ) == ["inside", "new"]
        ok = {k: {} for k in shape_mod.KINDS}
        ok[kind] = {"over": b + 4, "inside": b}
        assert not grew_while_over_budget(kind, ok, base) and not born_over_budget(kind, ok, base)


def test_code_shape_ratchet() -> None:
    """pytest から収集されたときも同じ検査を行う（import 時には測らない）。"""
    assert not failures(), "\n".join(failures())


if __name__ == "__main__":
    now, base = _load()
    ok = True
    for label, res in checks(now, base):
        print(("PASS " if res else "FAIL ") + label)
        ok = ok and res
    print()
    print("ALL_PASS" if ok else "HAS_FAILURE")
    raise SystemExit(0 if ok else 1)
