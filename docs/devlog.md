# 取り組みログ（devlog）

仕様書は「結果」を、この devlog は「過程（壁打ちで何をどう練り直したか・変えた判断・理由）」を残す。

## 書き方
- 1作業アーク＝1見出し（`## YYYY-MM-DD〜 タイトル`）。新しいものを上に足す。
- 各アークに: 背景・壁打ち / 設計のブラッシュアップ（当初案→変更→理由）/ 実装(PR) / 決定・未決。
- 仕様書と重複させない（現状は spec へリンク）。秘匿情報・個人パスは書かない。

## 2026-11-26 init の欠け 9 成分を一度に入れた（形のラチェット・層の検査・文書整合の残り）

`init_conformance.py` が 15 成分のうち 9 成分の欠けを示した。仕様書・CI・仕様鮮度の門・文書整合の 4 本は先に入っていたが、
docs の入口（devlog・decisions・playbooks）・CLAUDE.md・形のラチェットと台帳・層の検査・文書整合の残り 4 本が無かった。
一部だけでなく同じ PR で全部入れた。コードの挙動は変えていない。

- **層の置き方**: 当初案は `src/reshog/` を層のディレクトリに束ねる。やめた理由は、16 本の平置きの import は 45 本・
  循環なしで、束ねるとテストの `from reshog import …` と monkeypatch の対象まで動くため。束ねるのは設計判断で init の範囲を超える。
  1 ファイル 1 層として今の import の向きを `tests/test_src_layers.py` の表へ写し、以後の悪化だけ止める形にした。
- **直した 1 点（挙動は同じ）**: `cli.py` が `from . import __version__` でパッケージの入口を読んでいて、層の検査に落ちた。
  版の文字列を `constants.VERSION` に移し、`__init__.py` は `__version__ = VERSION` で再エクスポート、`cli.py` は `constants` から読む。
  `reshog.__version__` と `--version` の出力は変わらない。
- **台帳は導入時の値で作った**: 予算を超えているのは 7 件（`render.py` の 493 行（実行行。docstring・コメント・空行を除く）、`_build_app` 102 行・`render_table` 77 行・
  `_render_totals` 61 行、`_kill_process` と `render_table` の複雑度 16、`src/reshog` の直下 17 本）。検査は弱めず、増やせない借金として記録した。
- **定数・型の混在**: 型の置き場は `types.py` でなく `models.py` として既にある（`test_structure.py` もそう呼ぶ）。改名は全 import に及ぶので、
  定数・型の黙認の表（`tests/test_definitions_live_apart.py`）に理由つきで載せた（直したら行を消さないと落ちる）。
- **罠 1（個人パスの検査）**: 実機の出力を模したテストの値が、ホームディレクトリ配下の形（ユーザー名だけ架空）で、
  個人ディレクトリパスの検査に 27 行当たった。検査側の除外でなく、先頭の 1 部品を同じ長さの別名（`/Share/`）に置き換えた
  （80 桁の折り返しを見るテストがあり、長さを変えると意味が変わるため）。
- **罠 2（全テストを流す pre-commit）**: 雛形の pre-commit は `uv run pytest` を呼ぶが、このリポの dev 依存は Poetry の group にあり、
  uv は読まない。そのままだと pytest が別の環境で動いて `reshog` を import できずコミットが止まる。pytest だけ `uv run --with pytest pytest` に
  して流した。依存を uv 管理へ移すかは別の判断（Poetry の CI に及ぶ）で、この PR では動かしていない。
- **検査の段の増加**: pre-commit が、前は文書整合の 4 本だけを回していたのを、全テストを glob で回す形に変えた（段が増える）。
  名指しだと、置いたのに流されないテストが静かに生まれるため、雛形の形に揃えた。CI は前から全テストを流している。
- **ruff**: 雛形の写し（`scripts/code_shape/`・`test_claude_md_budget.py`）は書式の指摘が出る。雛形の更新は丸ごと上書きするので、
  写しを直さず `per-file-ignores` で除いた。
- **未決**: README・仕様書が `git config core.hooksPath .githooks` を案内している。init の手順は hooksPath を使わない
  （全体の門 3 本が黙って止まるため）。この PR では直していない。
