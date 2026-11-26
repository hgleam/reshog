"""台帳の書き直し。名指しした入れ物（ファイル・ディレクトリ）の行だけを、いまの測定で置き換える。"""

from __future__ import annotations

import os
import posixpath
from pathlib import Path

from .constants import DIR_KINDS
from .scan import is_test_file


def as_keys(args: list[str], root: Path, cwd: Path) -> list[str]:
    """打たれたパス（./ 付き・絶対パス・今いる場所からの相対）を、
    台帳の鍵の形（リポジトリ直下からの相対・/ 区切り）に直す。

    リポジトリの外・リポジトリ直下そのもの（全体は引数なしで書き直す）は ValueError。
    """
    keys = []
    for arg in args:
        # 別名のディレクトリ（macOS の /tmp → /private/tmp）は実体に直してから照らす
        # （root は実体のパス）。
        # 末尾の名前は直さない: ファイルの別名（src/alias.ts -> a.ts）は、測った鍵も別名のまま
        # （scan は名前で鍵を作る）
        # .. は字面で畳まず OS と同じ順で解く（別名の後ろの .. は別名の先から 1 つ上がる）。
        # 末尾が . / .. なら全体を解く
        full = os.path.join(str(cwd), arg).rstrip("/") or "/"
        parent, name = os.path.split(full)
        real = (os.path.realpath(full) if name in (".", "..")
                else os.path.join(os.path.realpath(parent), name))
        rel = os.path.relpath(real, os.path.realpath(str(root)))
        if rel == "." or rel == ".." or rel.startswith(".." + os.sep):
            raise ValueError(
                f"リポジトリの外か、リポジトリ直下そのもの: {arg}（全体を書き直すなら引数なしで）"
            )
        keys.append(Path(rel).as_posix())
    return keys


def _named(key: str, paths: list[str], kind: str = "") -> bool:
    """鍵（`パス` か `パス::関数名`）が、名指ししたファイルそのものか、
    名指ししたディレクトリの下にあるか。

    ディレクトリの指標（鍵が `ディレクトリ` か `ディレクトリ/頭*`）は、
    名指ししたファイルの親ディレクトリの行も含む
    （ファイルを足した・消した・束ねたとき、そのファイルの名指しで親の本数も書き直す。
    下げ忘れの余白を残さない）。テストのファイルの名指しは親の行を照らさない
    （テストは粒度に数えないので、照らすと別の変更が積んだ親の増加を黙って台帳へ入れるだけになる）。
    """
    file = key.split("::", 1)[0]
    if kind in DIR_KINDS:
        file = file if kind == "dirs" else posixpath.dirname(file)
        if any(posixpath.splitext(p)[1] and not is_test_file(Path(p))
               and file == posixpath.dirname(p) for p in paths):
            return True
    return any(file == p or file.startswith(p.rstrip("/") + "/") for p in paths)


def add_missing_kinds(
    base: dict[str, dict[str, int]], now: dict[str, dict[str, int]]
) -> tuple[dict, list[str]]:
    """台帳に無い指標（雛形の更新で増えたもの）の行だけを、いまの測定で足す。
    ある指標の行は動かさない。"""
    missing = sorted(set(now) - set(base))
    return base | {kind: now[kind] for kind in missing}, missing


def rebase(base: dict[str, dict[str, int]], now: dict[str, dict[str, int]],
           paths: list[str]) -> dict[str, dict[str, int]]:
    """base のうち名指しした入れ物の行を消し、now の同じ入れ物の行を足す
    （消えたファイルの行は消えたまま）。

    名指ししていない行は動かさない。全体を書き直すと、別の変更が積んだ増加まで台帳へ黙って入るため。
    測った木にも台帳にも無いパスは打ち間違いとして ValueError
    （何も書き直さずに通すと、直したつもりで残る）。
    """
    # 打ち間違いの判定は親ディレクトリへ広げない（広げると、無いファイルも親の行に当たって通る）
    unknown = [p for p in paths
               if not any(_named(k, [p]) for d in (base, now) for kind in d for k in d[kind])]
    if unknown:
        raise ValueError(
            f"測った木にも台帳にも無いパス（リポジトリ直下からの相対に直して照らした）: {unknown}"
        )
    kinds = set(base) | set(now)
    return {kind: {k: v for k, v in base.get(kind, {}).items() if not _named(k, paths, kind)}
            | {k: v for k, v in now.get(kind, {}).items() if _named(k, paths, kind)}
            for kind in sorted(kinds)}
