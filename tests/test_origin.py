"""「どのプロジェクトから動いているか」(PJ 列)のテスト。

材料は 2 つ。作業ディレクトリ(lsof)と launchd のジョブ名(launchctl list)。
どちらも外部コマンドなので collect をモックし、判定は origin の純粋関数で見る。
"""

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from reshog import collect, origin, report
from reshog.models import Origin, Process, SystemCpu, SystemMemory
from reshog.parse import parse_launchctl_list, parse_lsof_cwd
from reshog.render import build_json, render_table

# `lsof -a -d cwd -p <pids> -Fpn` の実出力の形(p 行 → f 行 → n 行の繰り返し)。
# 読めない PID(root のプロセス等)は何も出ない。
LSOF_SAMPLE = """\
p20193
fcwd
n/Users/me/develop/private/tokyo-calendar
p2299
fcwd
n/
p99856
fcwd
n/Users/me/develop/private/tokyo-calendar/.claude/worktrees/pushblk
p4539
fcwd
n/Users/me/dir with space
"""

# `launchctl list` の実出力の形(PID / 直近の終了コード / ラベル。止まっているものは "-")。
LAUNCHCTL_SAMPLE = """\
PID\tStatus\tLabel
20193\t0\tcom.tokyocal.llama-server
-\t0\tcom.apple.AMPDevicesAgent
2299\t0\tapplication.com.docker.docker.1234.5678
"""


class TestParseLsofCwd:
    def test_maps_pid_to_cwd(self) -> None:
        cwds = parse_lsof_cwd(LSOF_SAMPLE)
        assert cwds[20193] == "/Users/me/develop/private/tokyo-calendar"
        assert cwds[2299] == "/"

    def test_keeps_spaces_in_path(self) -> None:
        assert parse_lsof_cwd(LSOF_SAMPLE)[4539] == "/Users/me/dir with space"

    def test_empty_output(self) -> None:
        assert parse_lsof_cwd("") == {}


class TestParseLaunchctlList:
    def test_maps_running_pid_to_label(self) -> None:
        labels = parse_launchctl_list(LAUNCHCTL_SAMPLE)
        assert labels[20193] == "com.tokyocal.llama-server"

    def test_skips_stopped_jobs_and_header(self) -> None:
        labels = parse_launchctl_list(LAUNCHCTL_SAMPLE)
        assert set(labels) == {20193, 2299}


def _make_repo(root: Path) -> Path:
    (root / ".git").mkdir(parents=True)
    return root


class TestRepoRoot:
    def test_finds_repo_from_subdirectory(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "tokyo-calendar")
        sub = repo / "src" / "tokyocal"
        sub.mkdir(parents=True)
        assert origin.repo_root(str(sub)) == repo

    def test_worktree_resolves_to_main_repo(self, tmp_path: Path) -> None:
        """worktree の .git はファイル。gitdir を辿って元のリポ名を出す(置き場所に依存しない)。"""
        repo = _make_repo(tmp_path / "tokyo-calendar")
        wt = tmp_path / "elsewhere" / "pushblk"
        wt.mkdir(parents=True)
        (repo / ".git" / "worktrees" / "pushblk").mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {repo}/.git/worktrees/pushblk\n")
        assert origin.repo_root(str(wt)) == repo

    def test_submodule_is_its_own_project(self, tmp_path: Path) -> None:
        """submodule の .git もファイルだが worktrees を指さない。そのディレクトリ自身を返す。"""
        parent = _make_repo(tmp_path / "parent")
        sub = parent / "vendor" / "lib"
        sub.mkdir(parents=True)
        (sub / ".git").write_text("gitdir: ../../.git/modules/lib\n")
        assert origin.repo_root(str(sub)) == sub

    def test_outside_any_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert origin.repo_root(str(plain)) is None

    def test_missing_directory(self, tmp_path: Path) -> None:
        assert origin.repo_root(str(tmp_path / "gone")) is None


class TestResolve:
    def test_git_repo_wins(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "tokyo-calendar")
        got = origin.resolve(str(repo), "com.tokyocal.llama-server")
        assert got == Origin(kind="git", name="tokyo-calendar")

    def test_falls_back_to_launchd_label(self) -> None:
        got = origin.resolve("/", "com.tokyocal.llama-server")
        assert got == Origin(kind="launchd", name="com.tokyocal.llama-server")

    def test_gui_app_label_is_not_an_origin(self) -> None:
        """application.* は GUI アプリの自動ラベル(乱数付き)。COMMAND 列と同じことしか言わない。"""
        assert origin.resolve("/", "application.com.docker.docker.1234.5678") is None

    def test_nothing_known(self) -> None:
        assert origin.resolve("/", None) is None
        assert origin.resolve(None, None) is None


_TOP = """\
PhysMem: 63G used (7613M wired, 32G compressor), 217M unused.

PID    MEM   %CPU
20193  4700M 0.0
2299   900M  0.0
"""


class TestBuildProcessesAttachesOrigin:
    @pytest.fixture(autouse=True)
    def _mock(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "tokyo-calendar")
        calls: list[list[int]] = []
        self.lsof_calls = calls

        def _cwd(pids: list[int]) -> str:
            calls.append(list(pids))
            return f"p20193\nfcwd\nn{repo}\np2299\nfcwd\nn/\n"

        monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": _TOP)
        monkeypatch.setattr(collect, "ps_command", lambda pid: f"/bin/cmd{pid}")
        monkeypatch.setattr(collect, "ps_rss_mb", lambda pid: 10)
        monkeypatch.setattr(collect, "process_cwds", _cwd)
        monkeypatch.setattr(collect, "launchd_jobs", lambda: LAUNCHCTL_SAMPLE)
        monkeypatch.setattr(collect, "process_elapsed", lambda pids: "")

    def test_each_process_gets_its_origin(self) -> None:
        procs, _ = report.build_processes(count=10)
        assert procs[0].origin == Origin(kind="git", name="tokyo-calendar")
        assert procs[1].origin is None

    def test_cwd_lookup_is_one_call_for_all_shown_processes(self) -> None:
        """件数ぶん lsof を叩くと表示件数に比例して遅くなる。表示分を 1 回で引く。"""
        report.build_processes(count=10)
        assert self.lsof_calls == [[20193, 2299]]

    def test_app_drilldown_also_gets_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            collect,
            "ps_snapshot",
            lambda: "20193 1 10240 /bin/cmd20193\n2299 1 10240 /bin/cmd2299\n",
        )
        procs, _ = report.build_app_processes("cmd20193", count=10)
        assert procs[0].origin == Origin(kind="git", name="tokyo-calendar")


class TestProcessCwdsCommand:
    def test_pids_are_passed_as_one_value_argument(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []
        monkeypatch.setattr(collect, "_run", lambda args: seen.append(args) or "")
        collect.process_cwds([20193, 2299])
        assert seen == [["lsof", "-a", "-d", "cwd", "-p", "20193,2299", "-Fpn"]]

    def test_no_pids_runs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """-p を空で渡すと lsof は全プロセスを列挙してしまう。"""
        seen: list[list[str]] = []
        monkeypatch.setattr(collect, "_run", lambda args: seen.append(args) or "")
        assert collect.process_cwds([]) == ""
        assert seen == []


_SYSTEM = SystemMemory(phys="63G used", swap=None, free_percentage=None)
_CPU = SystemCpu(load_average=None, usage=None)


def _proc(pid: int, found: Origin | None) -> Process:
    return Process(pid=pid, mem_mb=4700, rss_mb=10, cpu=0.0, command="/bin/x", origin=found)


class TestRender:
    def _text(self, processes: list[Process]) -> str:
        buffer = io.StringIO()
        console = Console(file=buffer, width=200, no_color=True, highlight=False)
        render_table(console, processes, _SYSTEM, _CPU)
        return buffer.getvalue()

    def test_table_has_project_column(self) -> None:
        out = self._text([_proc(1, Origin(kind="git", name="tokyo-calendar"))])
        assert "PJ" in out
        assert "tokyo-calendar" in out

    def test_launchd_origin_is_marked(self) -> None:
        """リポ名とジョブ名は別物。見分けがつくよう印を付ける。"""
        out = self._text([_proc(1, Origin(kind="launchd", name="com.tokyocal.llama-server"))])
        assert "launchd:com.tokyocal.llama-server" in out

    def test_unknown_origin_is_dash(self, cell) -> None:
        assert cell(self._text([_proc(4242, None)]), 4242, "PJ") == "-"

    def test_json_has_origin(self) -> None:
        payload = json.loads(
            build_json(
                [_proc(1, Origin(kind="git", name="tokyo-calendar")), _proc(2, None)],
                _SYSTEM,
                _CPU,
            )
        )
        assert payload["processes"][0]["origin"] == {"kind": "git", "name": "tokyo-calendar"}
        assert payload["processes"][1]["origin"] is None
