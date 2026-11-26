#!/usr/bin/env python3
"""【雛形】CLAUDE.md が育っていないかを見る（バイト数の予算。超えたら落ちる）。

CLAUDE.md は毎セッション全文が読み込まれる。1 回の追記は小さくても、足し続けると
読み込みの床が上がる。差分レビューでは 1 回分しか見えないので、累積の大きさを予算と突き合わせる。

コピー後に直すのは、まず BUDGET_BYTES（導入時の `wc -c CLAUDE.md` が数 KB 以上なら 1 割ほど上。
数百 B の雛形のままなら切りのよい値のまま）。rules の定数は下で説明する（既定で通るなら触らない）。
予算内は自由。超える変更は落ちる。直し方は 2 つ。
  1. 手順・事例・表を docs/ かスキルへ移す（既定）。CLAUDE.md には毎回効く規則だけ残す
  2. どうしても毎回読ませる規則なら、同じ差分で BUDGET_BYTES を上げ、理由を PR に書く
減らしたら BUDGET_BYTES も下げる（余白が次の肥大を許すので）。単位はバイト（日本語は 1 文字 3B）。
`.claude/rules/**/*.md`（サブディレクトリ・隠しファイル・大文字の .MD 込み）も毎ターン読まれるので
同じ検査に含める（1 回の Edit は小さく、書き込み時の門には写らず、少しずつ育つため）。
ファイルごとの台帳 RULE_BUDGETS、台帳に無いファイル（新規）の上限 NEW_RULE_BYTES、
全体の合計の上限 RULES_TOTAL_BYTES（1 本ずつは小さくても本数で育つため）で見る。
  - 台帳に無いファイルは NEW_RULE_BYTES まで。超えるなら詳細を docs/ かスキルへ移す
  - 導入時に NEW_RULE_BYTES を超えている既存ファイルは、実測値を RULE_BUDGETS へ書く
    （キーは .claude/rules/ からの相対パス。以後その値を超えて増えると落ちる）。
    直して減らしたら台帳の行も下げる。消す・改名したファイルの行は残すと落ちる（台帳の掃除）
  - 導入時の rules の合計が RULES_TOTAL_BYTES を超えているなら、実測の 1 割ほど上へ上げる
測るのは CLAUDE.md と rules 自身だけ。`@AGENTS.md` などで取り込んだ先は数えないので、取り込み先が
実体のリポは、その文書にも同じ予算の検査を足す（未検査）。
何を CLAUDE.md に書き、何を README に書くかは init スキルの
「README と CLAUDE.md の書き分け」。

標準ライブラリのみ。実行: python3 tests/test_claude_md_budget.py -> 末尾に ALL_PASS
"""
import glob
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BUDGET_BYTES = 4000  # 既定は雛形向けの切りのよい値。大きい CLAUDE.md は実測に合わせて直す
NEW_RULE_BYTES = 3000  # .claude/rules/ の台帳に無いファイルの上限
RULES_TOTAL_BYTES = 12000  # .claude/rules/ 全体の合計の上限（既定は雛形向け。実測に合わせて直す）
RULE_BUDGETS = {}  # 例: {"big-rule.md": 6565}（導入時に上限を超えていた既存ファイルの実測値）


def over_budget(size, budget):
    """予算を超えたバイト数（超えていなければ 0）。"""
    return max(0, size - budget)


def rule_limit(name, budgets, new_bytes):
    """rules のファイルの上限。台帳にあればその値、無ければ新規用の上限。"""
    return budgets.get(name, new_bytes)


def rule_files(repo, unreadable=None):
    """.claude/rules/ 以下の .md を、サブディレクトリ込みで {相対パス: 絶対パス} にする。

    隠しファイル・隠しディレクトリ・大文字の拡張子（.MD）も数える（読み込まれるか分からない
    ものを数え落とすより、多めに測る方が安全）。通常のファイルだけを対象にする
    （壊れたリンクや、名前が .md のディレクトリは読み込まれないので外す）。
    ディレクトリのシンボリックリンクも辿る（同じ実体は 1 回だけ数え、循環もそこで止まる）。
    歩く順は名前順に固定する（同じ実体への別名が複数あっても、どの名前で数えるかが揺れない）。
    読めないディレクトリは黙って飛ばさず、unreadable（リスト）に溜める。
    """
    unreadable = [] if unreadable is None else unreadable
    base = os.path.join(repo, ".claude", "rules")
    found = {}
    seen = set()
    if not os.path.isdir(base):
        return found  # rules が無いリポは数えるものが無い（読めないのとは別）
    for here, dirs, names in os.walk(base, followlinks=True, onerror=unreadable.append):
        dirs.sort()
        real = os.path.realpath(here)
        if real in seen:
            dirs[:] = []
            continue
        seen.add(real)
        for name in names:
            path = os.path.join(here, name)
            if name.lower().endswith(".md") and os.path.isfile(path):
                found[os.path.relpath(path, base).replace(os.sep, "/")] = path
    return dict(sorted(found.items()))


def unreadable_detail(errors):
    """読めないディレクトリの一覧を、失敗の説明文にする（無ければ空）。"""
    if not errors:
        return ""
    names = ", ".join(str(e.filename) for e in errors)
    return "（%s。権限を直すか、数えない理由を決める）" % names


def stale_ledger(budgets, names):
    """台帳にあるのに実在しないファイル名（消した・改名した行の残り）。"""
    return sorted(set(budgets) - set(names))


def test_claude_md_within_budget():
    """pytest からも走る（素の pytest だけの CI でも予算を見る）。"""
    assert main() == 0


def check_checker_itself(check):
    """検査器自身の回帰（空振りしない）。"""
    check("予算ちょうどは通る", over_budget(100, 100) == 0)
    check("予算を 1B 超えたら検出する", over_budget(101, 100) == 1)
    check("予算より小さければ通る", over_budget(50, 100) == 0)
    check("台帳に無い rules は新規用の上限", rule_limit("x.md", {}, 7) == 7)
    check("台帳にある rules は台帳の値", rule_limit("x.md", {"x.md": 9}, 7) == 9)
    stale = stale_ledger({"a.md": 1, "b.md": 2}, ["a.md"])
    check("実在しない台帳の行を見つける", stale == ["b.md"])


def check_claude_md(check):
    """CLAUDE.md が予算内か（無ければ飛ばす）。"""
    path = os.path.join(REPO, "CLAUDE.md")
    if not os.path.isfile(path):
        print("SKIP CLAUDE.md が無い（置いたら予算を測る）")
        return
    size = os.path.getsize(path)  # 中身は読まない（読めないファイルでも測れる）
    over = over_budget(size, BUDGET_BYTES)
    check(
        "CLAUDE.md が予算内",
        over == 0,
        "（%dB / 予算 %dB。超過 %dB。手順・事例・表は移す）" % (size, BUDGET_BYTES, over),
    )


def check_rules(check):
    """.claude/rules/ の 1 ファイルずつ・合計・台帳の掃除。"""
    unreadable = []
    found = rule_files(REPO, unreadable)
    check(
        ".claude/rules/ に読めないディレクトリが無い",
        unreadable == [],
        unreadable_detail(unreadable),
    )
    if not found and not unreadable:
        print("SKIP .claude/rules/ に .md が無い（置いたら 1 ファイルずつ予算を測る）")
    total = 0
    for name, rule in found.items():
        size = os.path.getsize(rule)  # 中身は読まない（読めないファイルでも測れる）
        total += size
        limit = rule_limit(name, RULE_BUDGETS, NEW_RULE_BYTES)
        over = over_budget(size, limit)
        check(
            ".claude/rules/%s が予算内" % name,
            over == 0,
            "（%dB / 上限 %dB。超過 %dB。手順・事例・表は docs/ かスキルへ移す。"
            "要るなら RULE_BUDGETS を同じ差分で上げ、理由を PR に書く）" % (size, limit, over),
        )
    if found:
        over = over_budget(total, RULES_TOTAL_BYTES)
        check(
            ".claude/rules/ の合計が予算内",
            over == 0,
            "（%dB / 上限 %dB。超過 %dB。本数が増えた分も docs/ かスキルへ移す）"
            % (total, RULES_TOTAL_BYTES, over),
        )
    stale = stale_ledger(RULE_BUDGETS, found)
    check(
        "RULE_BUDGETS に実在しないファイルが無い",
        stale == [],
        "（%s。消した・改名したなら台帳の行も消す）" % ", ".join(stale) if stale else "",
    )


def main():
    results = []

    def check(name, cond, detail=""):
        results.append(bool(cond))
        print(("PASS " if cond else "FAIL ") + name + (" " + detail if detail else ""))

    check_checker_itself(check)
    check_claude_md(check)
    check_rules(check)
    ok = all(results)
    print("\nALL_PASS" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
