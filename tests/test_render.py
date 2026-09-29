"""render モジュールの単体テスト。"""

import io
import shlex

import pytest
from rich.console import Console

from reshog.models import Process, ProcessGroup, SystemCpu, SystemMemory
from reshog.render import format_mb, render_group_table, render_table


class TestFormatMb:
    @pytest.mark.parametrize(
        ("mb", "expected"),
        [
            (32768, "32.0G"),
            (1536, "1.5G"),
            (1024, "1.0G"),
            (745, "745M"),
            (0, "0M"),
        ],
    )
    def test_format(self, mb: float, expected: str) -> None:
        assert format_mb(mb) == expected


_SYSTEM = SystemMemory(phys="63G used", swap="total = 1M", free_percentage="37%")
_CPU = SystemCpu(load_average="1.00, 2.00, 3.00", usage="10% user, 20% sys, 70% idle")


def _render(fn, *args) -> str:
    """幅を固定した Console へ描画して、素のテキストを取り出す。"""
    buffer = io.StringIO()
    console = Console(file=buffer, width=200, no_color=True, highlight=False)
    fn(console, *args)
    return buffer.getvalue()


class TestUntrustedTextIsNotInterpreted:
    """コマンド文字列・アプリ名は他プロセス由来。rich のマークアップとして解釈させない。"""

    HOSTILE = "/usr/bin/evil [bold red]INJECTED[/bold red] --flag"

    def test_process_footer_escapes_markup(self) -> None:
        proc = Process(pid=42, mem_mb=100, rss_mb=50, cpu=0.0, command=self.HOSTILE)
        out = _render(render_table, [proc], _SYSTEM, _CPU)
        assert "[bold red]INJECTED[/bold red]" in out

    def test_group_footer_escapes_markup(self) -> None:
        proc = Process(pid=42, mem_mb=100, rss_mb=50, cpu=0.0, command=self.HOSTILE)
        group = ProcessGroup(label="[red]evil[/red]", members=(proc,))
        out = _render(render_group_table, [group], _SYSTEM, _CPU)
        assert "[red]evil[/red]" in out
        assert "[bold red]INJECTED[/bold red]" in out


class TestSuggestedCommandIsShellSafe:
    """フッタの提案コマンドはそのまま貼られる。アプリ名は shlex でクォートする。"""

    def test_label_with_quote_and_semicolon_is_quoted(self) -> None:
        proc = Process(pid=42, mem_mb=100, rss_mb=50, cpu=0.0, command="/bin/x")
        group = ProcessGroup(label="ev'il; touch /tmp/pwned", members=(proc,))
        label = "ev'il; touch /tmp/pwned"
        out = _render(render_group_table, [group], _SYSTEM, _CPU)
        assert f"memhog --app {shlex.quote(label)}" in out
        # クォート漏れ（アプリ名をそのまま ' で囲んだだけ）は不可。
        assert f"memhog --app '{label}'" not in out


class TestCpuIsVisible:
    """CPU の情報が実際に画面へ出ていること（値を持っていても出さなければ意味がない）。"""

    PROC = Process(pid=42, mem_mb=100, rss_mb=100, cpu=250.0, command="/bin/hog")

    def test_system_cpu_section_is_shown(self) -> None:
        out = _render(render_table, [self.PROC], _SYSTEM, _CPU)
        assert "システムCPU" in out
        assert "1.00, 2.00, 3.00" in out
        assert "10% user, 20% sys, 70% idle" in out

    def test_process_cpu_value_is_shown(self) -> None:
        out = _render(render_table, [self.PROC], _SYSTEM, _CPU)
        assert "250" in out

    def test_cpu_order_changes_the_title(self) -> None:
        mem_title = _render(render_table, [self.PROC], _SYSTEM, _CPU)
        cpu_title = _render(render_table, [self.PROC], _SYSTEM, _CPU, "cpu")
        assert "実メモリ上位" in mem_title
        assert "CPU 上位" in cpu_title

    def test_group_table_always_shows_cpu_total(self) -> None:
        """メモリ順で見ているときも合計CPU は出す（埋もれている消費に気づけるように）。"""
        g = ProcessGroup(
            label="swarm",
            members=tuple(
                Process(pid=i, mem_mb=1, rss_mb=1, cpu=5.0, command="/bin/swarm")
                for i in range(1, 21)
            ),
        )
        out = _render(render_group_table, [g], _SYSTEM, _CPU)
        assert "合計CPU" in out
        assert "100" in out


class TestSuggestedCommandMatchesTheView:
    """提案するのは「いま見ている並び順を再現するコマンド」。

    CPU 順で見ているのに memhog を勧めると、開き直した画面の並びが変わる。
    表示は成立し、テストも通り、実行しても動く（並びが違うだけ）ので、
    指摘されるまで気づけない類のずれ。
    """

    PROC = Process(pid=42, mem_mb=100, rss_mb=100, cpu=250.0, command="/bin/hog")
    GROUP = ProcessGroup(
        label="swarm",
        members=(Process(pid=42, mem_mb=100, rss_mb=100, cpu=250.0, command="/bin/hog"),),
    )

    def test_process_footer_follows_the_sort(self) -> None:
        mem = _render(render_table, [self.PROC], _SYSTEM, _CPU)
        cpu = _render(render_table, [self.PROC], _SYSTEM, _CPU, "cpu")
        assert "memhog --kill" in mem and "cpuhog --kill" not in mem
        assert "cpuhog --kill" in cpu and "memhog --kill" not in cpu

    def test_group_footer_follows_the_sort(self) -> None:
        mem = _render(render_group_table, [self.GROUP], _SYSTEM, _CPU)
        cpu = _render(render_group_table, [self.GROUP], _SYSTEM, _CPU, None, "cpu")
        assert "memhog --app" in mem and "cpuhog --app" not in mem
        assert "cpuhog --app" in cpu and "memhog --app" not in cpu


class TestCommandTableIsTheSingleSource:
    """並び順↔コマンド名の対応が、entry point と食い違っていないこと。"""

    def test_matches_pyproject_entry_points(self) -> None:
        import os

        from reshog.constants import COMMAND_BY_SORT

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as fh:
            content = fh.read()
        for command in COMMAND_BY_SORT.values():
            assert f'{command} = "reshog.cli:' in content, command

    def test_sort_keys_are_the_accepted_values(self) -> None:
        from reshog.constants import COMMAND_BY_SORT

        assert set(COMMAND_BY_SORT) == {"mem", "cpu"}

