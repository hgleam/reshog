"""ディレクトリの粒度を測る（ファイルのパスだけを見る。言語を問わない）。scan.py から呼ばれる。

  - dirs      ディレクトリ直下の実装ファイルの本数
              （平置きが育つと、どれが同じ関心事か名前でしか分からなくなる）
  - prefixes  同じディレクトリで名前の頭が同じファイルの本数
              （`receipt-match.ts` `receipt-parse.ts` …）。
              名前でディレクトリを代用している形で、`receipt/` にすべき合図。

関数・ファイルの指標がどれも予算内でも、置き場の粒度はずれる
（🔬 2026-09-25・2026-10-17。分割を終えたあと
利用者に「粒度は揃っている？」と聞かれるまで、どの指標も鳴らなかった）。
"""

from __future__ import annotations

from pathlib import PurePosixPath

from .constants import NAME_SEPARATORS


def name_head(filename: str) -> tuple[str, bool]:
    """(名前の頭, 区切りがあったか)。
    拡張子と `.test` などの重ねた拡張子は外し、最初の `-` か `_` までを頭とする。"""
    stem = filename.split(".", 1)[0].strip("".join(NAME_SEPARATORS))
    cut = min((i for i in (stem.find(s) for s in NAME_SEPARATORS) if i > 0), default=-1)
    return (stem[:cut], True) if cut > 0 else (stem, False)


def prefix_groups(names: list[str], dirname: str) -> dict[str, int]:
    """{頭: 本数}。2 本以上・区切りのある名前を 1 本以上含む束だけ（`a.ts` と `a-b.ts` は同じ束）。

    頭がディレクトリ名と同じもの（`menu/menu-a.ts`）は名前の繰り返しで、
    ディレクトリの代用ではないので外す。
    入口の名前（`index.ts`・`__init__.py`）は 1 ディレクトリに 1 本で区切りも無いので、
    束の条件を満たさない。
    """
    groups: dict[str, list[bool]] = {}
    for name in names:
        head, split = name_head(name)
        if head and head != dirname:
            groups.setdefault(head, []).append(split)
    return {head: len(splits) for head, splits in groups.items()
            if len(splits) >= 2 and any(splits)}


def measure_dirs(paths: list[str]) -> dict[str, dict[str, int]]:
    """{"dirs": {ディレクトリ: 本数}, "prefixes": {"ディレクトリ/頭*": 本数}}。
    paths はリポジトリ直下からの相対。"""
    by_dir: dict[str, list[str]] = {}
    for p in paths:
        path = PurePosixPath(p)
        by_dir.setdefault(path.parent.as_posix(), []).append(path.name)
    prefixes = {f"{d}/{head}*": n for d, names in by_dir.items()
                for head, n in prefix_groups(names, PurePosixPath(d).name).items()}
    return {"dirs": {d: len(names) for d, names in by_dir.items()}, "prefixes": prefixes}
