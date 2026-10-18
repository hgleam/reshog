"""reshog の定数(しきい値・コマンド名・説明文)の唯一の置き場。

実装のファイルに定数を置かない。置き場が散ると、同じ値を 2 か所に書いて片方だけ直る。
各定数の直前のコメントは、その値にした経緯(元の置き場から一緒に移した)。
"""

import re

# --- 判定のしきい値・コマンド名(models.py) ---

# GPU/Metal 常駐(ps に出ない)判定のしきい値
HIDDEN_GPU_MIN_MB = 2000
HIDDEN_GPU_RSS_RATIO = 4

# 並び順と、それを既定にするコマンド名の対応。
#
# **この 3 箇所の唯一の正本**にする: pyproject の entry point / cli の app 生成 /
# render が出す「次に打つコマンド」の提案文。3 箇所に別々に書くと、コマンドを増やしたとき
# 提案文だけ古いまま残る(何も壊れないので指摘されるまで気づけない)。
COMMAND_BY_SORT: dict[str, str] = {"mem": "memhog", "cpu": "cpuhog"}


# --- 外部コマンドの取り方(collect.py) ---

# top は 1 サンプル目の %CPU を必ず 0.0 で返す(前回サンプルとの差分が無いため)。
# 2 サンプル取り、2 つ目だけを解析する。実測で +1.3 秒かかるが、表示している
# %CPU が常に嘘という状態のほうが害が大きい。
TOP_SAMPLES = 2


# --- 出力の解釈(parse.py) ---

MEM_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)([GMKB]?)$")

UNIT_TO_MB: dict[str, float] = {
    "G": 1024.0,
    "M": 1.0,
    "K": 1.0 / 1024,
    "B": 1.0 / (1024 * 1024),
    "": 1.0,
}


# --- アプリ名の決め方(group.py) ---

# argv[0] がこれらのときは「何を動かしているか」(スクリプト名)を表示名に採る。
INTERPRETERS = frozenset(
    {
        "node",
        "python",
        "python3",
        "Python",
        "ruby",
        "perl",
        "php",
        "deno",
        "bun",
        "java",
        "Rscript",
    }
)

# 親としてたどっても意味を持たない「器」。ここで止めるとシェルや端末に全部吸われる。
TRANSPARENT = frozenset(
    {
        "tmux",
        "tmux-server",
        "screen",
        "login",
        "sh",
        "bash",
        "zsh",
        "fish",
        "env",
        "xargs",
        "sshd",
        "launchd",
        "Terminal",
        "iTerm2",
        "Alacritty",
        "WezTerm",
        "kitty",
        "Ghostty",
    }
)


# --- PJ の決め方(origin.py) ---

# GUI アプリを起動したときに launchd が自動で付けるラベル(末尾に乱数が付く)。
# COMMAND 列と同じことしか言わないので、由来としては出さない。
GUI_APP_LABEL_PREFIX = "application."

# OS のエージェント。bootout はジョブを台帳から外すので、勧めると再ログインまで機能が欠ける。
# 止め方の案内(launchd_service)からは外し、kill を案内する(PJ 列の表示はそのまま)。
APPLE_LABEL_PREFIX = "com.apple."

# launchctl のドメイン(サービス名の先頭)。launchd_domain が返す形と対になる。
LAUNCHD_DOMAIN_RE = re.compile(r"^(system|gui/\d+)/")


# --- 全プロセス走査の幅(report.py) ---

# --group は「分散して埋もれているアプリ」を探すのが目的なので、全プロセスを走査する。
# 走査幅は ps の実プロセス数から決める(固定上限にすると、超えた分が黙って合計から落ちる)。
# 実測: このマシンで 1065 プロセス。上限 500 では合計の半分が消えていた。
GROUP_SAMPLE_MIN = 100

# ps を撮ってから top を撮るまでに増えたプロセスのぶんの余裕。
GROUP_SAMPLE_MARGIN = 50


# --- 短命プロセスの集計(report.build_churn / churn.py) ---

# 数える時間。top の 2 サンプルの間に生まれて終わるプロセスは一覧に出ないので、
# ps を繰り返し撮って新しく現れた PID を数える。cpuhog の実行がこの分だけ長くなる。
# 実測(2026-10-18): 9 本の claude セッションが動くマシンで 5 秒に 656 本。
# 3 秒(負荷が高いと ps が遅れて 4 秒)でも、1 位の起動元が数百本で抜けて見えた。
CHURN_SECONDS = 3.0

# ps を撮る間隔(秒)。これより短く生きて終わるものは数えられない(本数は下限になる)。
# ps 1 回はプロセス 1000 本で数十ミリ秒かかるので、実際の間隔はこれより少し長い。
CHURN_POLL_SECONDS = 0.1

# 表に出す起動元の数と、起動元ごとに並べる中身の名前の数。
CHURN_TOP_SOURCES = 8
CHURN_TOP_CHILDREN = 3

# 親がどのサンプルにも写らなかったもの(親も一瞬で終わった等)の束ね先。PID 0 は実在しない。
CHURN_UNKNOWN_PARENT = 0

# launchd の PID。親が先に終わった子はここへ付け替わる(起動元の表記で断る)。
LAUNCHD_PID = 1

# 親を辿る深さの上限(PID の再利用で親子が輪になっても止まるように)。
CHURN_MAX_DEPTH = 64


# --- 表示(render.py) ---

MAX_CMD = 96

# この値以上を食っているものは赤で強調する(プロセス単位・アプリ単位で共通)。
ALERT_MB = 8000

# CPU も同様。100% = 1 コアを丸ごと占有している状態。
ALERT_CPU = 100.0


# --- --help の説明文(cli.py) ---

# 各コマンドの説明。--sort の既定以外は同じ CLI なので、違いが分かるように書き分ける。
MEM_HELP = """macOS の実メモリ(物理フットプリント)を食っているプロセスを特定して提示する。

ps の RSS は Metal/MPS(GPU 共有メモリ)を数えないため、ComfyUI 等の ML 系は小さく見える。
top の物理フットプリントでランクし、その乖離を「⚠ GPU/Metal常駐」印で炙り出す。

CPU 順で見るなら cpuhog(または --sort cpu)。"""

CPU_HELP = """macOS の CPU を食っているプロセスを特定して提示する。

1 プロセスずつ見ると数 % でも、同じものが何十個も動いていれば合計は跳ねる。
--group はヘルパープロセスを親子関係で合算するので、分散して埋もれる消費が見える。

sys が user を大きく上回るときは、個々のプロセスの計算ではなくカーネル側の処理
(プロセス生成の嵐・I/O・ページング)を疑う。

末尾では約 3 秒、新しく生まれたプロセスを数え、それを生んでいる起動元ごとに出す。
数秒で終わるプロセスは一覧に出ないので、負荷平均が高いのに一覧が静かなときの原因はここに出る。

実メモリ順で見るなら memhog(または --sort mem)。"""


# --- OS のプロセスの説明(known.py) ---

# 上位に出る macOS のプロセスに「何のためのものか・止めてよいか」を添える。
# キーは実行ファイル名(パスの最後)。値は (何のためのものか, どうするか, 止めてよいか)。
# 名前だけでは何か分からず、案内どおり kill すると画面が落ちる(WindowServer)ため
# (2026-09-29 に「これは何？」と聞かれた)。表に出るもの(非 root でコマンドが読めるもの)に限る。
SPOTLIGHT_NOTE = (
    "Spotlight の索引づくり",
    (
        "止めても害は無いが、すぐ起動し直す(mds は root で動くので止めるには管理者権限も要る)。"
        "索引が終わるのを待つか、Spotlight の設定で重いフォルダを外す"
    ),
    True,
)
# OS のプロセスが置かれる場所。ここ以外にある同名のファイル(/tmp/mds 等)は別物として扱う。
KNOWN_PROCESS_DIRS = ("/System/", "/sbin/")
KNOWN_PROCESSES: dict[str, tuple[str, str, bool]] = {
    "WindowServer": (
        "macOS の画面描画",
        (
            "止めない。ウィンドウ・メニューバー・Dock をすべて描いているので、"
            "止めると画面が落ちてログアウトと同じになる(止めるには管理者権限も要る)"
        ),
        False,
    ),
    "launchd": (
        "macOS の全プロセスの親",
        "止められない。OS そのものが止まる",
        False,
    ),
    "mds": SPOTLIGHT_NOTE,
    "mds_stores": SPOTLIGHT_NOTE,
    "mdworker_shared": SPOTLIGHT_NOTE,
    "com.apple.Virtualization.VirtualMachine": (
        "仮想マシン(Docker Desktop 等)",
        "止めるなら起動元のアプリ(Docker Desktop 等)を終了する。強制終了すると中の作業が失われうる",
        True,
    ),
    # 2026-10-12 に 1 位に出た(CPU 36〜80%・5 時間で 70 分)。syspolicyd が署名の無い
    # 実行ファイルを 1 分に約 280 件検査に回していた。WezTerm をデベロッパツールに登録して
    # 再起動すると 0〜24 件に減った。
    "XprotectService": (
        "macOS のマルウェア検査(Gatekeeper の XProtect)",
        (
            "止めない。kill してもすぐ起動し直す。重いのは、署名の無い実行ファイル"
            "(ビルド成果物・venv・フック等)が実行のたびに検査されるため。"
            "減らすには、端末アプリをシステム設定 → プライバシーとセキュリティ →"
            " デベロッパツールに登録し、端末アプリ(と tmux サーバ)を起動し直す"
            "(launchd から起動される常駐には効かない)。"
            "効いたかは `log show --last 1m --predicate 'process == \"syspolicyd\"'"
            " | grep -c 'Putting executable into provenance'` の件数(1 分あたり)が"
            "数十件以下かで見る"
        ),
        False,
    ),
}


# --- llama-server の休止状態(llama.py) ---

# `--sleep-idle-seconds` の休止は同じプロセスのままモデルを外すだけで、「起動」列は変わらない。
# 状態は /props の is_sleeping(読むだけで起こさない。2026-09-29 に実測)、時刻はログから取る。
LLAMA_EXECUTABLE = "llama-server"
LLAMA_DEFAULT_PORT = 8080
# 問い合わせてよいホスト(自分のマシン)。0.0.0.0 等の待ち受け指定は 127.0.0.1 へ問い合わせる。
LLAMA_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "0.0.0.0"})
# IPv6 の自分のマシン。::1 だけで待ち受けていることがあるので [::1] へ問い合わせる。
LLAMA_LOCAL_HOSTS_V6 = frozenset({"::1", "[::1]", "::", "[::]"})
LLAMA_PROPS_TIMEOUT_SECONDS = 1.0
# ログは起動を重ねて数十 MB になる。末尾だけ読む(今回の起動の最後の休止の出入りが入る幅)。
LLAMA_LOG_TAIL_BYTES = 2 * 1024 * 1024
# 行頭の時刻(起動からの 分.秒.ミリ秒.マイクロ秒)と、休止の出入りの行。
LLAMA_LOG_TIME_RE = re.compile(r"^(\d+)\.(\d{2})\.(\d{3})\.(\d{3}) ")
LLAMA_SLEEP_ENTER = "server is entering sleeping state"
LLAMA_SLEEP_EXIT = "server is exiting sleeping state"
