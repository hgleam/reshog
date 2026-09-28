"""実エントリを subprocess で叩くスモークテスト。

内部関数を直接呼ぶテストは、利用者が実際に叩く経路の壊れを見逃す。typer / click の版
非互換・引数パース崩れ・起動時クラッシュは、`memhog --help` を実行して初めて出る
（実例: typer 0.12.5 + click 8.4 の `make_metavar` 非互換で --help が TypeError になった）。

外部コマンド(top/ps)を叩かない経路（--help / --version / 併用制約のエラー）だけを対象に
するので、macOS 以外の CI でも動く。
"""

import os
import re
import subprocess
import sys

import pytest

CLI = [sys.executable, "-m", "reshog.cli"]
# cpuhog は console script なので、同じ入口を import して直接叩く
# （インストール済みの実行ファイルに依存すると、未インストールの環境で落ちる）。
CPU_CLI = [sys.executable, "-c", "from reshog.cli import cpu_app; cpu_app()"]
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _run(*args: str, cli: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    """非 TTY でも折り返し・色でテキスト検査が壊れないように整えて実行する。"""
    env = {**os.environ, "COLUMNS": "220", "NO_COLOR": "1", "TERM": "dumb"}
    result = subprocess.run(
        [*(cli or CLI), *args], capture_output=True, text=True, timeout=60, env=env
    )
    result.stdout = _ANSI.sub("", result.stdout)
    result.stderr = _ANSI.sub("", result.stderr)
    return result


class TestEntryPoint:
    def test_help_exits_zero(self) -> None:
        result = _run("--help")
        assert result.returncode == 0, result.stderr[-500:]

    def test_help_lists_every_option(self) -> None:
        out = _run("--help").stdout
        for option in (
            "--count",
            "--sort",
            "--grep",
            "--json",
            "--group",
            "--project",
            "--app",
            "--watch",
            "--kill",
        ):
            assert option in out, f"{option} が --help に出ていない"

    def test_version_exits_zero(self) -> None:
        result = _run("--version")
        assert result.returncode == 0, result.stderr[-500:]
        assert "memhog" in result.stdout


class TestOptionGuards:
    """併用制約は外部コマンドを叩く前に落ちるので、CI(Linux)でも実行経路を検証できる。"""

    def test_group_with_kill_is_rejected(self) -> None:
        result = _run("--group", "--kill")
        assert result.returncode == 1
        assert "併用できません" in result.stdout

    def test_group_with_app_is_rejected(self) -> None:
        result = _run("--group", "--app", "x")
        assert result.returncode == 1
        assert "併用できません" in result.stdout

    @pytest.mark.parametrize("other", [["--group"], ["--app", "x"], ["--kill"]])
    def test_project_with_other_views_is_rejected(self, other: list[str]) -> None:
        result = _run("--project", *other)
        assert result.returncode == 1
        assert "併用できません" in result.stdout

    def test_watch_with_json_is_rejected(self) -> None:
        result = _run("--watch", "1", "--json")
        assert result.returncode == 1
        assert "併用できません" in result.stdout

    def test_unknown_option_is_rejected(self) -> None:
        assert _run("--no-such-option").returncode != 0


class TestSortOption:
    """外部コマンドを叩かずに検査できる範囲（不正値の拒否）だけを見る。"""

    def test_rejects_unknown_sort_key(self) -> None:
        result = _run("--sort", "disk")
        assert result.returncode != 0
        assert "mem" in result.stdout + result.stderr

    def test_help_documents_both_keys(self) -> None:
        out = _run("--help").stdout
        assert "mem" in out and "cpu" in out


class TestCpuhogCommand:
    """cpuhog は memhog と同じ CLI で、既定の並び順だけが違う。

    実装を 1 つのファクトリから作っているので「同じであること」は構造的に保証されるが、
    **違う部分が本当に違うか**と、**同じであるべき部分が同じか**は機械で見ておく。
    片方にだけオプションを足す変更が入っても、何も壊れずヘルプの差として残るだけなので
    自分では気づけない。
    """

    def test_default_sort_is_cpu(self) -> None:
        out = _run("--help", cli=CPU_CLI).stdout
        assert "[default: cpu]" in out, out

    def test_memhog_default_sort_is_mem(self) -> None:
        out = _run("--help").stdout
        assert "[default: mem]" in out, out

    def test_version_names_itself(self) -> None:
        assert _run("--version", cli=CPU_CLI).stdout.strip().startswith("cpuhog ")
        assert _run("--version").stdout.strip().startswith("memhog ")

    def test_help_body_differs(self) -> None:
        """入口が 2 つあっても中身の説明が同じなら、利用者は違いを判断できない。"""
        mem = _run("--help").stdout
        cpu = _run("--help", cli=CPU_CLI).stdout
        assert "実メモリ" in mem
        assert "CPU を食っている" in cpu
        assert mem != cpu

    def test_help_points_at_the_other_command(self) -> None:
        assert "cpuhog" in _run("--help").stdout
        assert "memhog" in _run("--help", cli=CPU_CLI).stdout

    def test_option_sets_are_identical(self) -> None:
        """--sort の既定以外は同じオプション一式であること。"""
        pattern = re.compile(r"--[a-z][a-z-]*")

        def options(out: str) -> set[str]:
            return set(pattern.findall(out))

        assert options(_run("--help").stdout) == options(_run("--help", cli=CPU_CLI).stdout)

    def test_rejects_unknown_sort_key(self) -> None:
        result = _run("--sort", "disk", cli=CPU_CLI)
        assert result.returncode != 0


class TestEntryPointsAreDeclared:
    """pyproject の console script が両方あること(宣言し忘れるとコマンドが生えない)。"""

    def test_pyproject_declares_both(self) -> None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as fh:
            content = fh.read()
        assert 'memhog = "reshog.cli:app"' in content
        assert 'cpuhog = "reshog.cli:cpu_app"' in content

