"""reshog のドメインモデル。"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .constants import HIDDEN_GPU_MIN_MB, HIDDEN_GPU_RSS_RATIO

# 表示の種類。processes = 通常(プロセス別) / app = --app / group = --group / project = --project。
View = Literal["processes", "app", "group", "project"]


@dataclass(frozen=True)
class Origin:
    """プロセスがどのプロジェクトから動いているか。

    Attributes:
        kind: 判定の根拠。"git"(作業ディレクトリのリポ名) / "launchd"(常駐ジョブ名)。
        name: リポ名またはジョブ名。
    """

    kind: Literal["git", "launchd"]
    name: str


@dataclass(frozen=True)
class LlmState:
    """ローカル LLM サーバー(llama-server)の休止状態。

    Attributes:
        sleeping: 休止中(モデルをメモリから外している)なら True。
        since: その状態になった時刻(ログから)。分からなければ None。
    """

    sleeping: bool
    since: datetime | None


@dataclass(frozen=True)
class ClaudeSession:
    """Claude Code のセッションの状態(`<設定フォルダ>/sessions/<PID>.json` から)。

    Attributes:
        status: busy / idle / shell 等(Claude Code が書いた値のまま)。
        since: その状態になった時刻(ローカル時刻)。書かれていなければ None。
        tmux: 開けば閉じられる場所(`<セッション名>:<ウィンドウ番号>.<ペイン番号>`)。
            番号に直せなければ書かれていた値のまま。tmux の外なら None。
    """

    status: str
    since: datetime | None
    tmux: str | None


@dataclass(frozen=True)
class KnownProcess:
    """OS のプロセスの説明(何のためのものか・止めてよいか)。

    Attributes:
        purpose: 何のためのものか。
        advice: どうするか(止めてよいか・止めるならどうするか)。
        stoppable: 止めてよいか。False なら停止の案内を出さず、--kill で警告する。
    """

    purpose: str
    advice: str
    stoppable: bool


@dataclass(frozen=True)
class Process:
    """1 プロセスのメモリ実態。

    Attributes:
        pid: プロセス ID。
        mem_mb: 物理フットプリント(MB)。Activity モニタ「メモリ」列 = top の MEM 相当。
        rss_mb: ps の RSS(MB)。Metal/MPS(GPU 共有メモリ)を数えないため過小に出る。
        cpu: CPU 使用率(%)。
        command: フルコマンド文字列。
        origin: 由来のプロジェクト。判別できなければ None(GUI アプリ・root のプロセス等)。
        started_at: 開始時刻(ローカル時刻)。取れなければ None(直前に終了した等)。
        launchd_service: 面倒を見ている launchd のサービス名(`gui/<uid>/<ラベル>` 等)。
            ジョブでなければ None。KeepAlive のジョブは kill しても起動し直されるので、
            止め方の案内が変わる。
        llm_state: llama-server の休止状態。llama-server でない・問い合わせられなければ None。
        claude: Claude Code のセッションの状態。Claude Code でない・読めなければ None。
            --project のときだけ読む。
    """

    pid: int
    mem_mb: int
    rss_mb: int
    cpu: float
    command: str
    origin: Origin | None = None
    started_at: datetime | None = None
    launchd_service: str | None = None
    llm_state: LlmState | None = None
    claude: ClaudeSession | None = None

    @property
    def hidden_gpu(self) -> bool:
        """ps の RSS に現れない GPU/Metal 常駐メモリを抱えているか。

        物理フットプリントが十分大きく(>= HIDDEN_GPU_MIN_MB)、かつ ps RSS の
        HIDDEN_GPU_RSS_RATIO 倍を超える場合、「小さく見えるのに実は巨大」なプロセス
        (ComfyUI・llama-server 等の ML 系)とみなす。

        Returns:
            GPU/Metal 常駐と判定されれば True。
        """
        return (
            self.mem_mb >= HIDDEN_GPU_MIN_MB
            and self.mem_mb > self.rss_mb * HIDDEN_GPU_RSS_RATIO
        )


@dataclass(frozen=True)
class SystemMemory:
    """システム全体のメモリ状況。

    Attributes:
        phys: top の PhysMem 行(例 "63G used (...), 217M unused")。
        swap: sysctl vm.swapusage の値。
        free_percentage: memory_pressure の空き割合(例 "37%")。
    """

    phys: str | None
    swap: str | None
    free_percentage: str | None


@dataclass(frozen=True)
class SystemCpu:
    """システム全体の CPU 状況。

    Attributes:
        load_average: top の Load Avg(1 / 5 / 15 分平均)。
        usage: top の CPU usage 行(user / sys / idle の内訳)。
    """

    load_average: str | None
    usage: str | None


@dataclass(frozen=True)
class PsEntry:
    """ps の 1 行分(全プロセス走査用)。

    Attributes:
        pid: プロセス ID。
        ppid: 親プロセス ID。
        rss_mb: ps の RSS(MB)。
        command: フルコマンド文字列。
    """

    pid: int
    ppid: int
    rss_mb: int
    command: str


@dataclass(frozen=True)
class ChurnSource:
    """短命プロセスを生み続けている 1 つの起動元(数え始めから動いていた親)。

    Attributes:
        pid: 起動元の PID。親がどのサンプルにも写らなかったものは constants.CHURN_UNKNOWN_PARENT。
        command: 起動元のフルコマンド。親不明なら空文字。
        origin: 起動元の由来のプロジェクト。判別できなければ None。
        children: 生まれたプロセスの名前(生まれた順。重複を含む)。
    """

    pid: int
    command: str
    origin: Origin | None
    children: tuple[str, ...]

    @property
    def count(self) -> int:
        """生まれた本数。"""
        return len(self.children)

    def main_children(self, limit: int) -> str:
        """多い順に名前と本数を並べる(「bash×3, gh×2, ほか 1」)。

        並べなかった名前の本数は「ほか N」で足す(行の本数と中身の合計を合わせる)。

        Args:
            limit: 並べる名前の数。

        Returns:
            表示する文字列。
        """
        ranked = Counter(self.children).most_common()
        shown = [f"{name}×{n}" for name, n in ranked[:limit]]
        rest = sum(n for _, n in ranked[limit:])
        return ", ".join(shown + ([f"ほか {rest}"] if rest else []))


@dataclass(frozen=True)
class Churn:
    """数秒のあいだに新しく生まれたプロセスの集計。

    top の 2 サンプルの間に生まれて終わるプロセスは CPU の一覧に一度も出ない。
    負荷平均が高いのに一覧が静かなときの原因は、ここでしか見えない。

    Attributes:
        seconds: 実際に数えた時間(秒)。
        sources: 起動元ごとの内訳(本数の多い順)。
    """

    seconds: float
    sources: tuple[ChurnSource, ...]

    @property
    def total(self) -> int:
        """捉えた本数の合計(サンプルの間で生まれて終わったものは数えられないので下限)。"""
        return sum(s.count for s in self.sources)

    @property
    def per_second(self) -> float:
        """1 秒あたりの本数。"""
        return self.total / self.seconds if self.seconds > 0 else 0.0


@dataclass(frozen=True)
class ProcessGroup:
    """同じアプリ由来のプロセスをまとめたもの。

    Chromium 系のようにプロセスが 100 個以上に分散するアプリは、1 プロセスずつ見ると
    上位ランキングから消えてしまう。合算して初めて「実は一番食っている」が見える。

    合計・件数・最大単体は members から導出する(冗長な列を持たない)。

    Attributes:
        label: アプリ名(app_label で導出した表示名)。
        members: 所属プロセス(メモリ降順)。
    """

    label: str
    members: tuple[Process, ...]

    @property
    def total_mb(self) -> int:
        """グループ全体の物理フットプリント合計(MB)。"""
        return sum(p.mem_mb for p in self.members)

    @property
    def count(self) -> int:
        """所属プロセス数。"""
        return len(self.members)

    @property
    def total_cpu(self) -> float:
        """グループ全体の CPU 使用率合計(%)。

        1 プロセスずつ見ると数 % でも、同じアプリが何十個も動いていれば合計は跳ねる。
        メモリの合計と同じ理由で、分散して埋もれる消費はここでしか見えない。
        """
        return sum(p.cpu for p in self.members)

    @property
    def largest(self) -> Process:
        """最も食っている 1 プロセス。"""
        return self.members[0]

    @property
    def hidden_gpu(self) -> bool:
        """GPU/Metal 常駐と判定されたプロセスを 1 つでも含むか。"""
        return any(p.hidden_gpu for p in self.members)


@dataclass(frozen=True)
class Rise:
    """前より増えた出どころ(source)か中身の名前(child)。値は毎秒の本数の平均。"""

    kind: str
    name: str
    recent: float
    baseline: float


@dataclass(frozen=True)
class Trend:
    """比べた結果。直近か過去が 0 件なら比べられない(comparable=False。「増えていない」とは別)。"""

    recent: int
    baseline: int
    rises: tuple[Rise, ...]
    future: int = 0  # 時刻が今より先で比べなかった記録の数

    @property
    def comparable(self) -> bool:
        """直近と過去の両方に記録があるか。"""
        return self.recent > 0 and self.baseline > 0
