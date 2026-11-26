"""コードの「形」を測る（標準ライブラリのみ。Python と TypeScript/JavaScript）。

**なぜ要るか**: ファイルが伸びる・関数が太る・本数が増えるといった少しずつ育つ悪化は、どの差分も
「小さい変更」の顔で入るので、差分のレビューでは見つからない。累積を台帳に持ち、悪化した向きだけを
落とす（判定は tests/test_code_shape_ratchet.py。ここは測るだけ）。

測るもの（鍵は `パス` か `パス::関数名`）:

  - files       ファイルの実行行（空行・コメント・docstring を除く。
                説明を書くと悪化したことにならない）。テストのファイルはこれと、
                下の functions・complexity のうちテストケースでない関数（検査ロジックの補助）を測る
                （constants.TEST_TARGETS と、実装の置き場に併置したテスト）
  - functions   関数の中身の行数
  - complexity  関数の複雑度（分岐の数 + 1。入れ子の関数の中身は外側に数えない）
  - per_file    ファイルあたりの関数の本数（小さい関数を大量に積む形は、
                関数単位の指標では全部健全と出る）
  - dirs        ディレクトリ直下の実装ファイルの本数（鍵は `ディレクトリ`）
  - prefixes    同じディレクトリで名前の頭が同じファイルの本数（鍵は `ディレクトリ/頭*`。
                名前でディレクトリを代用した形）

TypeScript/JavaScript は js/shape.py が測る（構文木なしで括弧の対応を取る）。括弧の対応が取れない
ファイルは unreadable（読めなかった）に数え、黙って外さない
（測れないものは膨らんでも鳴らないため）。

構成はこのディレクトリの README.md。
写した先で直すのは constants.py の TARGETS・TEST_TARGETS・SKIP だけ。

使い方:
    python3 scripts/code_shape                                # いまの形の上位を出す
    python3 scripts/code_shape --update-baseline <パス…>
        # 直した入れ物の行だけ台帳を書き直す（差分に出る）
    python3 scripts/code_shape --update-baseline              # 台帳の作成・作り直し（全体）
    python3 scripts/code_shape --add-missing-kinds
        # 雛形の更新で増えた指標の行だけ足す（ある指標は動かさない）
"""

from __future__ import annotations

from .constants import (BASELINE, EXTENSIONS, KINDS, ROOT, SKIP, TARGETS, TEST_TARGETS,
                        TOP_LEVEL)
from .dir_shape import measure_dirs, name_head
from .js.shape import measure_js
from .py_shape import measure_python
from .scan import is_test, is_test_file, measure, targets, targets_of_tests

__all__ = ["BASELINE", "EXTENSIONS", "KINDS", "ROOT", "SKIP", "TARGETS", "TEST_TARGETS",
           "TOP_LEVEL",
           "is_test", "is_test_file", "measure", "measure_dirs", "measure_js", "measure_python",
           "name_head", "targets", "targets_of_tests"]
