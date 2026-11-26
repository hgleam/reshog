# reshog プロジェクトルール

macOS の実メモリ・CPU を食っているプロセスを特定して出す診断 CLI（`memhog` / `cpuhog`）。仕様書は `docs/specification/`（入口は `docs/README.md`）。

- 依存は Poetry の group（`pyproject.toml`）。テストは `PYTHONPATH=src` を付けて pytest を流す（本体クローンの `.venv` は本体の `src` を指す）。全件でなく触った範囲だけ流してよい。
- 他プロセス由来の文字列（コマンド名・パス）は、rich のマークアップとシェルのどちらにも解釈させない（`render.py` の escape・shlex クォート。`tests/test_render.py` が固定）。
- `src/reshog/` は 1 ファイル 1 層の平置き。読む向きは `tests/test_src_layers.py`、副作用を持てるファイルは `tests/test_layer_side_effects.py`、定数・型は実装に足さない（`tests/test_definitions_live_apart.py`）。
- 予算を超えたコード（ファイル・関数）は台帳 `docs/metrics/code-shape.json` に記録済みで、増やせない。直したら `python3 scripts/code_shape --update-baseline <直したファイル>` で台帳を下げる。
- コードを変えたら、同じコミットで `docs/specification/` の該当トピックも直す（`.claude/rules/specification-update.md`）。
