"""コードの形を測るコマンド（`python3 scripts/code_shape`。
`--update-baseline` で台帳を書き直す）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ディレクトリを実行すると sys.path[0] がこのディレクトリになり、相対 import が使えない。
# scripts/ を足して絶対名で読む。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from code_shape.constants import BASELINE, KINDS, ROOT  # noqa: E402
from code_shape.ledger import add_missing_kinds, as_keys, rebase  # noqa: E402
from code_shape.scan import measure  # noqa: E402


def _load_baseline() -> dict | None:
    """いまの台帳。無い・読めない・JSON が壊れている（JSONDecodeError は ValueError）なら
    理由を出して None。"""
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # 無い・読めない・壊れている
        print(f"台帳を読めない（{e}）。先に引数なしの --update-baseline で作る", file=sys.stderr)
        return None


def _write_baseline(data: dict) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _add_missing(shape: dict) -> int:
    """雛形の更新で測るものが増えたとき、無い指標の行だけ足す（ある指標の行は動かさない）。"""
    base = _load_baseline()
    if base is None:
        return 1
    base, missing = add_missing_kinds(base, shape)
    _write_baseline(base)
    print(f"{BASELINE.relative_to(ROOT)} に足した指標: {'、'.join(missing) or 'なし'}")
    return 0


def _update(shape: dict, paths: list[str]) -> int:
    """直した入れ物の行だけ（日常の更新）。paths が空なら台帳の作成・作り直し（全体）。"""
    if paths:
        base = _load_baseline()
        if base is None:
            return 1
        try:
            paths = as_keys(paths, ROOT, Path.cwd())
            shape = rebase(base, shape, paths)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
    _write_baseline(shape)
    print(f"{BASELINE.relative_to(ROOT)} を更新しました（{'、'.join(paths) if paths else '全体'}）")
    return 0


def _show(shape: dict) -> int:
    for kind in KINDS:
        print(f"\n## {kind}（{len(shape[kind])} 件）")
        for name, n in sorted(shape[kind].items(), key=lambda kv: -kv[1])[:10]:
            print(f"{n:6}  {name}")
    print(f"\n## 読めなかったファイル（測っていない。{len(shape['unreadable'])} 件）")
    for name in sorted(shape["unreadable"]):
        print(f"        {name}")
    return 0


def main() -> int:
    shape = measure()
    if "--add-missing-kinds" in sys.argv:
        return _add_missing(shape)
    if "--update-baseline" in sys.argv:
        return _update(shape, sys.argv[sys.argv.index("--update-baseline") + 1:])
    return _show(shape)


if __name__ == "__main__":
    raise SystemExit(main())
