"""PJ 別(--project)の行に Claude Code のセッションの状態と tmux の位置を添えるテスト。

「どのセッションを閉じてよいか」と「どこを開けば閉じられるか」に、`cpuhog --project` だけで答える。
材料は Claude Code 自身が PID ごとに書く `<設定フォルダ>/sessions/<PID>.json`
(2026-10-30 に実物を確認)。

- `status`: busy(作業中)/ idle(待機)。他の値(shell 等)は意味を確かめていないので訳さずに出す。
  `statusUpdatedAt` はその状態になった時刻(ミリ秒)
- `tmux`: `<セッション名>:@<ウィンドウID>.%<ペインID>`。ID は人が打つ番号ではないので、
  `tmux list-panes` で `<セッション名>:<ウィンドウ番号>.<ペイン番号>` に直す
- 設定フォルダはセッションごとに違いうる(`CLAUDE_CONFIG_DIR`)。そのプロセスの環境変数から読む

会話ログ(jsonl)の更新時刻で推定しない: 同じ作業場所のセッションが同じログの置き場を共有し、
再開したセッションは別の ID のログに書くので、他のセッションの時刻を拾う(2026-10-30 に誤った)。
"""

import io
import json
from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console

from reshog import claude, collect, report
from reshog.models import ClaudeSession, Process, ProcessGroup, SystemCpu, SystemMemory
from reshog.parse import parse_claude_session, parse_env_value, parse_tmux_panes
from reshog.render import build_project_json, render_project_table

# 実物(~/claude-private/.claude/sessions/96868.json)から、使わない項目を落とした形
SESSION = {
    "pid": 96868,
    "sessionId": "a7d37697-e687-4146-8ce6-6243684560fb",
    "cwd": "/Users/me/develop/monetization-lab",
    "kind": "interactive",
    "tmux": "プライベート1:@51.%111",
    "status": "idle",
    "statusUpdatedAt": 1793370460648,
}
PANES = "%111\tプライベート1:10.1\n%180\t業託techknight:3.1\n"


def _since(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000).replace(microsecond=0)


class TestIsClaude:
    @pytest.mark.parametrize(
        "command",
        [
            "/Users/me/.local/bin/claude --dangerously-skip-permissions",
            "claude --resume 60335642-38b6-4b74-8fb5-1b2f906ab431",
            "claude",
        ],
    )
    def test_claude_code(self, command: str) -> None:
        assert claude.is_claude(command)

    @pytest.mark.parametrize(
        "command",
        [
            "/usr/bin/python claude.py",
            "/Users/me/.local/bin/claude-code-helper",
            "node /opt/claude/server.js",
            "",
        ],
    )
    def test_not_claude_code(self, command: str) -> None:
        assert not claude.is_claude(command)


class TestSessionFile:
    def test_config_dir_from_the_environment(self, tmp_path: Path) -> None:
        got = claude.session_file("/Users/me/claude-techknight/.claude", tmp_path, 87386)
        assert got == Path("/Users/me/claude-techknight/.claude/sessions/87386.json")

    def test_default_config_dir(self, tmp_path: Path) -> None:
        """CLAUDE_CONFIG_DIR を付けずに起動したセッションは ~/.claude に書く。"""
        want = tmp_path / ".claude" / "sessions" / "1.json"
        assert claude.session_file(None, tmp_path, 1) == want


class TestParseEnvValue:
    def test_value_per_pid(self) -> None:
        out = (
            "96868 /Users/me/.local/bin/claude --x PATH=/bin CLAUDE_CONFIG_DIR=/a/.claude TERM=x\n"
            "87386 claude --resume X CLAUDE_CONFIG_DIR=/b/.claude\n"
            "1 claude\n"
        )
        want = {96868: "/a/.claude", 87386: "/b/.claude"}
        assert parse_env_value(out, "CLAUDE_CONFIG_DIR") == want

    def test_name_must_match_whole(self) -> None:
        """MY_CLAUDE_CONFIG_DIR を CLAUDE_CONFIG_DIR と読まない。"""
        out = "5 claude MY_CLAUDE_CONFIG_DIR=/wrong\n"
        assert parse_env_value(out, "CLAUDE_CONFIG_DIR") == {}


class TestParseTmuxPanes:
    def test_pane_id_to_location(self) -> None:
        assert parse_tmux_panes(PANES) == {
            "%111": "プライベート1:10.1",
            "%180": "業託techknight:3.1",
        }

    def test_no_tmux(self) -> None:
        assert parse_tmux_panes("") == {}


class TestParseSession:
    def test_status_since_and_location(self) -> None:
        got = parse_claude_session(json.dumps(SESSION), 96868, parse_tmux_panes(PANES))
        assert got == ClaudeSession(
            status="idle", since=_since(1793370460648), tmux="プライベート1:10.1"
        )

    def test_unknown_pane_keeps_the_raw_value(self) -> None:
        """tmux が無い・ペインが消えていても、書かれていた値は残す(ID でも切り替えられる)。"""
        got = parse_claude_session(json.dumps(SESSION), 96868, {})
        assert got is not None
        assert got.tmux == "プライベート1:@51.%111"

    def test_pane_of_another_session_is_not_used(self) -> None:
        """ペイン ID だけ同じで別のセッション名なら番号に直さない(別の tmux サーバーの同じ番号)。"""
        got = parse_claude_session(json.dumps(SESSION), 96868, {"%111": "corvus:2.1"})
        assert got is not None
        assert got.tmux == "プライベート1:@51.%111"

    def test_outside_tmux(self) -> None:
        body = {k: v for k, v in SESSION.items() if k != "tmux"}
        got = parse_claude_session(json.dumps(body), 96868, {})
        assert got is not None
        assert got.tmux is None

    def test_other_pid_is_not_this_session(self) -> None:
        """PID が使い回されて古いファイルが残っていても、別のプロセスの状態を出さない。"""
        assert parse_claude_session(json.dumps(SESSION), 1234, {}) is None

    def test_missing_time(self) -> None:
        body = {k: v for k, v in SESSION.items() if k != "statusUpdatedAt"}
        got = parse_claude_session(json.dumps(body), 96868, {})
        assert got is not None
        assert got.since is None

    @pytest.mark.parametrize("text", ["", "not json", "[]", '{"pid": 96868}', '{"pid": "96868"}'])
    def test_unreadable(self, text: str) -> None:
        assert parse_claude_session(text, 96868, {}) is None


_TOP = "PID MEM %CPU\n200 1000M 30.0\n201 300M 1.0\n300 500M 0.0\n"
_PS = (
    "200 1 1024 /Users/me/.local/bin/claude --dangerously-skip-permissions\n"
    "201 200 1024 npm exec @playwright/mcp@latest\n"
    "300 1 1024 /usr/bin/python worker.py\n"
)


class TestBuildProjects:
    @pytest.fixture(autouse=True)
    def _mock(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> dict[str, list[str]]:
        repo = tmp_path / "monetization-lab"
        (repo / ".git").mkdir(parents=True)
        config = tmp_path / "config"
        (config / "sessions").mkdir(parents=True)
        (config / "sessions" / "200.json").write_text(
            json.dumps({**SESSION, "pid": 200}), encoding="utf-8"
        )
        calls: dict[str, list[str]] = {"env": [], "tmux": []}

        def _envs(pids: list[int]) -> str:
            calls["env"].append(",".join(map(str, sorted(pids))))
            return f"200 claude --x CLAUDE_CONFIG_DIR={config}\n"

        def _panes() -> str:
            calls["tmux"].append("x")
            return PANES

        monkeypatch.setattr(collect, "ps_snapshot", lambda: _PS)
        monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": _TOP)
        monkeypatch.setattr(
            collect,
            "process_cwds",
            lambda pids: "".join(f"p{p}\nfcwd\nn{repo}\n" for p in pids),
        )
        monkeypatch.setattr(collect, "launchd_jobs", lambda: "PID\tStatus\tLabel\n")
        monkeypatch.setattr(collect, "process_envs", _envs)
        monkeypatch.setattr(collect, "tmux_panes", _panes)
        return calls

    def test_session_is_attached_to_the_claude_process(self) -> None:
        projects, _, _ = report.build_projects(count=10)
        by_pid = {p.pid: p.claude for p in projects[0].members}
        assert by_pid[200] == ClaudeSession(
            status="idle", since=_since(1793370460648), tmux="プライベート1:10.1"
        )
        assert by_pid[201] is None  # 子の MCP サーバーは Claude Code ではない
        assert by_pid[300] is None

    def test_env_and_tmux_are_read_once(self, _mock: dict[str, list[str]]) -> None:
        """セッションの数によらず ps と tmux は 1 回ずつ。

        PID ごとに叩くと本数に比例して遅くなる。
        """
        report.build_projects(count=10)
        assert _mock == {"env": ["200"], "tmux": ["x"]}

    def test_no_claude_no_extra_commands(
        self, monkeypatch: pytest.MonkeyPatch, _mock: dict[str, list[str]]
    ) -> None:
        only_worker = "PID MEM %CPU\n300 5M 0\n"
        monkeypatch.setattr(collect, "top_sample", lambda count, order="mem": only_worker)
        report.build_projects(count=10)
        assert _mock == {"env": [], "tmux": []}


_SYSTEM = SystemMemory(phys=None, swap=None, free_percentage=None)
_CPU = SystemCpu(load_average=None, usage=None)
_NOW = datetime(2026, 10, 30, 23, 30)


def _project(*sessions: ClaudeSession | None) -> ProcessGroup:
    members = tuple(
        Process(pid=200 + i, mem_mb=100, rss_mb=100, cpu=1.0, command="claude", claude=s)
        for i, s in enumerate(sessions)
    )
    return ProcessGroup(label="monetization-lab", members=members)


def _text(*projects: ProcessGroup) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=220, no_color=True, highlight=False)
    render_project_table(console, list(projects), None, _SYSTEM, _CPU, now=_NOW)
    return buffer.getvalue()


class TestRender:
    def test_status_minutes_and_location(self, cell) -> None:
        idle = ClaudeSession(
            status="idle", since=datetime(2026, 10, 30, 22, 35), tmux="プライベート1:10.1"
        )
        out = _text(_project(idle))
        assert cell(out, 200, "Claude(状態・経過・tmux)") == "待機 55分 プライベート1:10.1"

    def test_each_session_on_its_own_line(self) -> None:
        """同じ PJ に 2 本あれば、1 本ずつ別の行に出す(1 本ずつ閉じるかを決めるため)。"""
        busy = ClaudeSession(status="busy", since=datetime(2026, 10, 30, 23, 29), tmux="a:1.1")
        idle = ClaudeSession(status="idle", since=datetime(2026, 10, 30, 21, 30), tmux="b:2.1")
        out = _text(_project(busy, idle))
        assert "待機 2時間0分 b:2.1" in out
        assert "作業中 1分 a:1.1" in out
        assert out.index("待機 2時間0分") < out.index("作業中 1分")  # 長く止まっているものが先

    def test_idle_before_long_busy(self) -> None:
        """待機を先に出す(閉じてよい候補が上。長く作業中のものを上に出さない)。"""
        busy = ClaudeSession(status="busy", since=datetime(2026, 10, 30, 20, 30), tmux="a:1.1")
        idle = ClaudeSession(status="idle", since=datetime(2026, 10, 30, 21, 30), tmux="b:2.1")
        out = _text(_project(busy, idle))
        assert out.index("待機 2時間0分") < out.index("作業中 3時間0分")

    def test_brackets_are_shown_as_written(self) -> None:
        """tmux のセッション名の [ ] を rich の書式として読まない(消える・表ごと落ちる)。"""
        odd = ClaudeSession(status="idle", since=None, tmux="[bold]x:1.1")
        assert "待機 ? [bold]x:1.1" in _text(_project(odd))

    def test_narrow_terminal_folds_instead_of_cutting(self) -> None:
        """80 桁の端末でも経過の分数を省略記号で切らない(実機で「作業中 5 …」と出た)。"""
        idle = ClaudeSession(
            status="shell", since=datetime(2026, 10, 30, 22, 35), tmux="業託techknight:3.1"
        )
        buffer = io.StringIO()
        console = Console(file=buffer, width=80, no_color=True, highlight=False)
        project = ProcessGroup(
            label="smart-front-with-a-long-name",
            members=(
                Process(pid=200, mem_mb=100, rss_mb=100, cpu=1.0, command="claude", claude=idle),
            ),
        )
        render_project_table(console, [project], None, _SYSTEM, _CPU, now=_NOW)
        cells = "".join(
            line.rstrip("│ ").rsplit("│", 1)[-1].strip()
            for line in buffer.getvalue().splitlines()
            if line.startswith("│")
        )
        assert "shell 55分 業託techknight:3.1".replace(" ", "") in cells.replace(" ", "")
        assert "…" not in cells

    def test_unknown_status_and_time(self) -> None:
        odd = ClaudeSession(status="paused", since=None, tmux=None)
        assert "paused ? tmux外" in _text(_project(odd))

    def test_no_column_without_sessions(self) -> None:
        """Claude Code が 1 本も無ければ列を出さない(空の列で幅を取らない)。"""
        assert "Claude(" not in _text(_project(None))

    def test_json(self) -> None:
        idle = ClaudeSession(status="idle", since=datetime(2026, 10, 30, 22, 35), tmux="x:1.1")
        payload = json.loads(build_project_json([_project(idle, None)], None, _SYSTEM, _CPU))
        assert payload["projects"][0]["claude_sessions"] == [
            {"pid": 200, "status": "idle", "since": "2026-10-30T22:35:00", "tmux": "x:1.1"}
        ]
