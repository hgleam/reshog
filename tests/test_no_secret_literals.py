"""追跡ファイルに資格情報・実 ID のリテラルが無いか検証する（標準ライブラリのみ）。

**ダミーであっても資格情報の「形」を模倣しない**。理由は漏洩ではなく、本物と見分けが
付かなくなること。検知フックやシークレットスキャナが毎回発火してトリアージが常態化し、
結果として**本物の混入を見落とす**（オオカミ少年化）。

プレースホルダは形を模倣せず `<クライアントシークレット>` のように書く。

なぜグローバル hook があるのにプロジェクト側にも要るか（2層にする理由）:
  グローバルの `credential-leak-guard.py precommit` は **AI の Bash 経由の `git commit`**
  だけを見る。人間の手動コミット・エディタからのコミット・CI・別ツールは通らない。
  この構造テストは CI でも走るので、経路に依らず止まる。

コピー後に直すのは **EXTRA_PATTERNS**（プロジェクト固有の実 ID があれば足す）と
**EXEMPT_FILES**（検体を持つテスト自身など）だけ。

**EXTRA_PATTERNS を足したら PROBES にも同じ名前で検体を足す**（検体の無い検出器は、
正規表現が壊れていても「何も検出しない＝合格」に見える）。足し忘れはこのテストが落とす。
検体はリテラルを置かずに分割連結で組み立てる（このファイル自体を汚さないため）。

実行: python3 tests/test_no_secret_literals.py   -> 末尾に ALL_PASS
"""

import os
import re
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# 自分自身は検体を持つので対象外（分割表記にしてあるが二重の保険）。
EXEMPT_FILES = {"tests/test_no_secret_literals.py"}

# バイナリ・ロックファイルは対象外（誤検知とノイズの温床）。
EXEMPT_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2")
EXEMPT_NAMES = {"package-lock.json", "uv.lock", "poetry.lock", "yarn.lock", "pnpm-lock.yaml"}

# サービス固有の接頭辞を持つ実在の資格情報。プレースホルダと形が違うので誤検知しにくい。
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Google OAuth クライアントシークレット", re.compile(r"GOCSPX-[A-Za-z0-9_-]{4,}")),
    ("Google OAuth アクセストークン", re.compile(r"\bya29\.[A-Za-z0-9._-]{10,}")),
    ("Google API キー", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("GitHub トークン", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}")),
    ("Slack トークン", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}")),
    ("OpenAI/Anthropic APIキー", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("AWS アクセスキー", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("秘密鍵(PEM)", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("個人ディレクトリパス", re.compile(r"/(?:Users|home)/[a-z][a-z0-9_-]*/")),
]

# プロジェクト固有の実 ID があればここに足す（例: 実測定ID・実プロパティID）。
#   ("GA4 測定ID（実値）", re.compile(r"G-(?!XXXXXXXXXX)[A-Z0-9]{10}")),
EXTRA_PATTERNS: list[tuple[str, re.Pattern[str]]] = []

# 検出器が空振りしていないことを確認する検体。実在しない値を分割して組み立てる
# （このファイル自体にリテラルを置かないため）。
PROBES: dict[str, str] = {
    "Google OAuth クライアントシークレット": "SECRET=" + "GOCSPX" + "-" + "d" * 8,
    "Google OAuth アクセストークン": "token=" + "ya29" + "." + "d" * 20,
    "Google API キー": "key=" + "AIza" + "D" * 32,
    "GitHub トークン": "gh" + "p" + "_" + "D" * 32,
    "Slack トークン": "xox" + "b" + "-" + "1" * 16,
    "OpenAI/Anthropic APIキー": "sk" + "-" + "D" * 24,
    "AWS アクセスキー": "AKIA" + "A" * 16,
    "秘密鍵(PEM)": "-----" + "BEGIN RSA PRIVATE KEY" + "-----",
    "個人ディレクトリパス": "/Users/someone/develop",
}

# 正当なプレースホルダ。これらを検出したら過検出。
SAFE_SAMPLES = [
    "CLIENT_SECRET=<クライアントシークレット>",
    'measurementId: "G-XXXXXXXXXX"',
    '"propertyId": "123456789"',
    "const key = process.env.API_KEY;",
    "~/develop/project",
]


def tracked() -> list[str]:
    """git が追跡しているテキストファイル（相対パス）。"""
    # `-z` で取る。既定の `git ls-files` は**非 ASCII のパスを引用符付きで
    # エスケープする**（8 進エスケープの文字列になり、頭に引用符が付く）ため、
    # 日本語名のファイルが 1 つあるだけで別のパスとして扱われ、検査が黙って
    # 対象を取り違える（実測）。NUL 区切りなら加工されない（空白名にも効く）。
    out = subprocess.run(
        ["git", "-C", REPO, "ls-files", "-z"], capture_output=True, text=True,
        check=False,
    ).stdout
    files = []
    for path in out.split("\0"):
        if not path or path in EXEMPT_FILES or os.path.basename(path) in EXEMPT_NAMES:
            continue
        if path.endswith(EXEMPT_SUFFIXES):
            continue
        files.append(path)
    return files


def read(rel: str) -> str:
    try:
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


files = tracked()
all_patterns = PATTERNS + EXTRA_PATTERNS

hits: dict[str, list[str]] = {}
for doc in files:
    body = read(doc)
    for num, line in enumerate(body.splitlines(), 1):
        for name, pattern in all_patterns:
            if pattern.search(line):
                hits.setdefault(name, []).append(f"{doc}:{num}")

# 検出器自体が機能しているか（正規表現が壊れて素通りしないか）。
# **EXTRA_PATTERNS も対象にする。** 雛形の PATTERNS だけを見ていると、プロジェクト側で
# 足した検出器は正規表現が壊れていても空振りのまま緑になる（何も検出しない＝合格に見える）。
blind = [name for name, pattern in all_patterns if not pattern.search(PROBES.get(name, ""))]
# 検体が無いものも「壊れていても分からない」ので同じ扱いにする。EXTRA を足したら PROBES も足す。
no_probe = [name for name, _ in all_patterns if name not in PROBES]
# 安全なプレースホルダを誤検出しないか。
false_positives = [
    f"{name} <- {sample}"
    for name, pattern in all_patterns
    for sample in SAFE_SAMPLES
    if pattern.search(sample)
]

checks = [
    ("検査対象ファイルを発見できている（0件ならパターンが空振り）", len(files) > 0),
    (f"検出器が検体を拾える（拾えないパターン: {sorted(blind) or 'なし'}）", not blind),
    (f"全パターンに検体がある（PROBES 未登録: {sorted(no_probe) or 'なし'}）", not no_probe),
    (f"安全なプレースホルダを誤検出しない（{sorted(false_positives) or 'なし'}）",
     not false_positives),
]
for name, _ in all_patterns:
    found = sorted(set(hits.get(name, [])))
    checks.append((f"{name} を含まない（{found or 'なし'}）", not found))


def failures() -> list[str]:
    """満たされていない検査項目のラベル。"""
    return [label for label, res in checks if not res]


def test_no_secret_literals() -> None:
    """pytest から収集されたときも同じ検査を行う。"""
    assert not failures(), "\n".join(failures())


if __name__ == "__main__":
    ok = True
    for label, res in checks:
        print(("PASS " if res else "FAIL ") + label)
        ok = ok and bool(res)
    print()
    print("ALL_PASS" if ok else "HAS_FAILURE")
    raise SystemExit(0 if ok else 1)
