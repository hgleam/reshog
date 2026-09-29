"""reshog のドメインモデル。"""

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
        launchd_job: 面倒を見ている launchd のジョブ名。ジョブでなければ None。
            KeepAlive のジョブは kill しても起動し直されるので、止め方の案内が変わる。
    """

    pid: int
    mem_mb: int
    rss_mb: int
    cpu: float
    command: str
    origin: Origin | None = None
    started_at: datetime | None = None
    launchd_job: str | None = None

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
