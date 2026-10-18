"""短命プロセスの記録(--record)と、出どころごとの増加(--trend)のテスト。

1 本ずつは軽い「繰り返し動くもの」(フック・statusline・プラグイン等)は、積み上がっても差分では
見えない。2026-10-18 は負荷平均が 39〜90 になって初めて、フックの pyenv の shim が原因と分かった。
日ごとに数えて残し、前より増えた出どころを出せば、種類を問わず増え始めに気づける。
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reshog import trend
from reshog.constants import CHURN_UNKNOWN_PARENT, LAUNCHD_PID
from reshog.models import Churn, ChurnSource, Origin

_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _churn(seconds: float = 2.0, *sources: ChurnSource) -> Churn:
    return Churn(seconds=seconds, sources=tuple(sources))


def _claude(*children: str, repo: str = "smart-front") -> ChurnSource:
    return ChurnSource(
        pid=100,
        command="/u/.local/bin/claude --resume",
        origin=Origin(kind="git", name=repo),
        children=children,
    )


def _record(
    at: datetime, by_source: dict[str, float], by_child: dict[str, float] | None = None
) -> dict[str, object]:
    return {
        "at": at.isoformat(),
        "seconds": 3.0,
        "load": [1.0, 1.0, 1.0],
        "per_second": sum(by_source.values()),
        "by_source": by_source,
        "by_child": by_child or {},
    }


class TestRecordOf:
    def test_counts_are_per_second_by_source_and_by_child(self) -> None:
        found = _churn(2.0, _claude("bash", "bash", "pyenv-exec", "Python"))
        rec = trend.record_of(found, _NOW, (39.8, 43.3, 43.5))
        assert rec["by_source"] == {"smart-front:claude": 2.0}
        assert rec["by_child"] == {"bash": 1.0, "pyenv-exec": 0.5, "Python": 0.5}
        assert rec["at"] == "2026-10-18T12:00:00+00:00"
        assert rec["load"] == [39.8, 43.3, 43.5]
        assert rec["per_second"] == 2.0

    def test_source_without_origin_and_unknown_parent_keep_their_own_labels(self) -> None:
        found = _churn(
            1.0,
            ChurnSource(
                pid=7,
                command="bash /u/.tmux/plugins/tmux-resurrect/scripts/save.sh quiet",
                origin=None,
                children=("ps", "sed"),
            ),
            ChurnSource(pid=CHURN_UNKNOWN_PARENT, command="", origin=None, children=("x",)),
            ChurnSource(pid=LAUNCHD_PID, command="/sbin/launchd", origin=None, children=("y",)),
        )
        keys = set(trend.record_of(found, _NOW, (1.0, 1.0, 1.0))["by_source"])
        # 起動元の名前は短命プロセスの表(churn.source_label)と同じ。
        # シェルで動くスクリプトは今は bash と出る
        assert keys == {"bash", "(親不明)", "launchd(親が先に終わったものを含む)"}

    def test_the_record_is_one_json_line(self) -> None:
        line = trend.to_line(trend.record_of(_churn(1.0, _claude("bash")), _NOW, (1.0, 2.0, 3.0)))
        assert "\n" not in line
        assert json.loads(line)["by_child"] == {"bash": 1.0}


class TestRising:
    def test_a_source_that_grew_past_the_ratio_and_floor_is_reported(self) -> None:
        records = [
            _record(_NOW - timedelta(days=3), {"smart-front:claude": 4.0, "save.sh": 2.0}),
            _record(_NOW - timedelta(days=2), {"smart-front:claude": 6.0, "save.sh": 2.0}),
            _record(_NOW - timedelta(hours=2), {"smart-front:claude": 20.0, "save.sh": 2.1}),
        ]
        result = trend.rising(records, _NOW)
        assert (result.recent, result.baseline) == (1, 2)
        assert [(r.kind, r.name, r.recent, r.baseline) for r in result.rises] == [
            ("source", "smart-front:claude", 20.0, 5.0)
        ]

    def test_a_new_child_name_counts_from_zero(self) -> None:
        records = [
            _record(_NOW - timedelta(days=2), {"a": 1.0}, {"bash": 1.0}),
            _record(_NOW - timedelta(hours=1), {"a": 1.0}, {"bash": 1.0, "pyenv-exec": 3.0}),
        ]
        rises = trend.rising(records, _NOW).rises
        assert [(r.kind, r.name, r.baseline) for r in rises] == [("child", "pyenv-exec", 0.0)]

    def test_small_rates_are_not_reported_even_if_they_doubled(self) -> None:
        """毎秒 1 本に満たないものは、倍になっても知らせない(鳴りすぎると読まれない)。"""
        records = [
            _record(_NOW - timedelta(days=2), {"a": 0.2}),
            _record(_NOW - timedelta(hours=1), {"a": 0.8}),
        ]
        assert trend.rising(records, _NOW).rises == ()

    def test_not_enough_records_is_told_apart_from_no_rise(self) -> None:
        """直近か過去のどちらかが 0 件なら比べられない。「増えていない」と言わない。"""
        only_recent = [_record(_NOW - timedelta(hours=1), {"a": 50.0})]
        result = trend.rising(only_recent, _NOW)
        assert (result.recent, result.baseline, result.comparable) == (1, 0, False)

    def test_records_older_than_the_window_are_ignored(self) -> None:
        records = [
            _record(_NOW - timedelta(days=30), {"a": 100.0}),
            _record(_NOW - timedelta(days=2), {"a": 2.0}),
            _record(_NOW - timedelta(hours=1), {"a": 10.0}),
        ]
        result = trend.rising(records, _NOW)
        assert result.baseline == 1
        assert [r.baseline for r in result.rises] == [2.0]


    def test_window_edges_are_inclusive(self) -> None:
        """ちょうど 1 日前は直近、ちょうど 8 日前は過去、それより古いものは比べない。"""
        records = [
            _record(_NOW - timedelta(days=8, seconds=1), {"a": 100.0}),
            _record(_NOW - timedelta(days=8), {"a": 2.0}),
            _record(_NOW - timedelta(days=1), {"a": 10.0}),
        ]
        result = trend.rising(records, _NOW)
        assert (result.recent, result.baseline) == (1, 1)
        assert [(r.recent, r.baseline) for r in result.rises] == [(10.0, 2.0)]

    def test_records_from_the_future_are_counted_not_compared(self) -> None:
        """時計のずれで今より先の時刻が付いた記録は、直近に混ぜず future に数える。"""
        records = [
            _record(_NOW - timedelta(days=2), {"a": 2.0}),
            _record(_NOW + timedelta(hours=1), {"a": 100.0}),
            _record(_NOW - timedelta(hours=1), {"a": 2.0}),
        ]
        result = trend.rising(records, _NOW)
        assert (result.recent, result.baseline, result.future) == (1, 1, 1)
        assert result.rises == ()

    def test_names_only_in_the_past_are_not_reported(self) -> None:
        """減った・消えたものは「増えた」に出さない。"""
        records = [
            _record(_NOW - timedelta(days=2), {"a": 1.0, "gone": 50.0}),
            _record(_NOW - timedelta(hours=1), {"a": 1.0}),
        ]
        assert trend.rising(records, _NOW).rises == ()

class TestReadRecords:
    def test_broken_lines_are_counted_not_dropped(self, tmp_path: Path) -> None:
        """読めない行は黙って捨てず、件数を返す(読めなかったと何も無いを分ける)。"""
        path = tmp_path / "churn.jsonl"
        good = trend.to_line(trend.record_of(_churn(1.0, _claude("bash")), _NOW, (1.0, 1.0, 1.0)))
        path.write_text(f'{good}\nnot json\n{{"at": "x"}}\n\n', encoding="utf-8")
        records, broken = trend.read_records(path)
        assert (len(records), broken) == (1, 2)

    @pytest.mark.parametrize(
        "line",
        [
            '{"at": "2026-10-18T12:00:00", "by_source": {}, "by_child": {}}',
            '{"at": "2026-10-18T12:00:00+00:00", "by_source": {"a": "5"}, "by_child": {}}',
            '{"at": "2026-10-18T12:00:00+00:00", "by_source": {"a": null}, "by_child": {}}',
            '{"at": "2026-10-18T12:00:00+00:00", "by_source": {"a": NaN}, "by_child": {}}',
            '{"at": "2026-10-18T12:00:00+00:00", "by_source": {}, "by_child": {"b": true}}',
            '{"at": "2026-10-18T12:00:00+00:00", "by_source": {"a": -3}, "by_child": {}}',
            '{"at": "2026-10-18T12:00:00+00:00", "by_source": {"a": 1'
            + "0" * 400
            + '}, "by_child": {}}',
            "[" * 100_000,
            "[1, 2]",
        ],
        ids=["no-tz", "str", "null", "nan", "bool", "negative", "huge-int", "deep", "not-dict"],
    )
    def test_records_that_would_break_the_comparison_are_counted_as_broken(
        self, tmp_path: Path, line: str
    ) -> None:
        """--trend の引き算・足し算で落ちる・黙って消える行は、読む時点で弾いて数える。"""
        path = tmp_path / "churn.jsonl"
        good = trend.to_line(_record(_NOW, {"a": 1.0}))
        path.write_text(f"{line}\n{good}\n", encoding="utf-8")
        records, broken = trend.read_records(path)
        assert (len(records), broken) == (1, 1)
        trend.rising(records, _NOW)  # 残った記録で比べても落ちない

    def test_a_line_that_is_not_utf8_is_counted_and_the_rest_are_read(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "churn.jsonl"
        good = trend.to_line(_record(_NOW, {"a": 1.0})).encode("utf-8")
        path.write_bytes(b"\xff\xfe\n" + good + b"\n")
        records, broken = trend.read_records(path)
        assert (len(records), broken) == (1, 1)

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert trend.read_records(tmp_path / "none.jsonl") == ([], 0)


@pytest.mark.parametrize(
    "env, want", [({}, None), ({"RESHOG_CHURN_LOG": "/x/y.jsonl"}, Path("/x/y.jsonl"))]
)
def test_log_path_follows_the_environment(env: dict[str, str], want: Path | None) -> None:
    path = trend.log_path(env)
    assert path == (want or Path.home() / ".local" / "state" / "reshog" / "churn.jsonl")


class TestCli:
    """cpuhog --record / --trend の入口。数える処理(build_churn)と負荷平均は差し替える。"""

    def _run(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *args: str) -> tuple[int, str]:
        from typer.testing import CliRunner

        from reshog import cli, collect, report

        monkeypatch.setenv("RESHOG_CHURN_LOG", str(tmp_path / "churn.jsonl"))
        monkeypatch.setattr(report, "build_churn", lambda *a: _churn(2.0, _claude("bash", "bash")))
        monkeypatch.setattr(collect, "load_average", lambda: (3.0, 2.0, 1.0))
        result = CliRunner().invoke(cli.cpu_app, list(args))
        return result.exit_code, result.output

    def test_record_appends_one_line_per_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        for _ in range(2):
            code, out = self._run(monkeypatch, tmp_path, "--record")
            assert code == 0, out
        records, broken = trend.read_records(tmp_path / "churn.jsonl")
        assert (len(records), broken) == (2, 0)
        assert records[0]["by_source"] == {"smart-front:claude": 1.0}
        assert records[0]["load"] == [3.0, 2.0, 1.0]
        assert str(tmp_path / "churn.jsonl") in out

    def test_record_does_not_write_when_ps_could_not_be_read(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """数えられなかった回を「0 本」として残さない。

        残すと過去の平均が下がり、次の回が増えたように見える。
        """
        from typer.testing import CliRunner

        from reshog import cli, report

        monkeypatch.setenv("RESHOG_CHURN_LOG", str(tmp_path / "churn.jsonl"))
        monkeypatch.setattr(report, "build_churn", lambda *a: None)
        result = CliRunner().invoke(cli.cpu_app, ["--record"])
        assert result.exit_code == 1
        assert not (tmp_path / "churn.jsonl").exists()

    def test_trend_lists_what_grew(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        log = tmp_path / "churn.jsonl"
        log.write_text(
            "\n".join(
                trend.to_line(r)
                for r in (
                    _record(now - timedelta(days=2), {"save.sh": 2.0}, {"bash": 2.0}),
                    _record(
                        now - timedelta(hours=1), {"save.sh": 2.0, "x:claude": 30.0}, {"bash": 2.0}
                    ),
                )
            )
            + "\n",
            encoding="utf-8",
        )
        code, out = self._run(monkeypatch, tmp_path, "--trend")
        assert code == 0, out
        assert "x:claude" in out and "save.sh" not in out

    def test_trend_says_it_cannot_compare_yet(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """記録が足りないときは「増えていない」と言わず、比べられないと言う。"""
        code, out = self._run(monkeypatch, tmp_path, "--trend")
        assert code == 0, out
        assert "比べられません" in out
        assert "増えたものはありません" not in out

    @pytest.mark.parametrize(
        "args",
        [
            ["--record", "--trend"],
            ["--record", "--watch", "2"],
            ["--trend", "--json"],
            ["--record", "--kill"],
            ["--record", "--grep", "claude"],
            ["--trend", "-n", "5"],
            ["--record", "-n", "15"],  # 既定値と同じ数でも、明示したら拒否する
            ["--record", "--force"],
            ["--trend", "-y"],
        ],
    )
    def test_record_and_trend_do_not_mix_with_other_views(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str]
    ) -> None:
        code, out = self._run(monkeypatch, tmp_path, *args)
        assert code == 1
        assert "併用できません" in out

    def test_record_says_where_it_could_not_write(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """置き場に書けなければ、素の例外ではなく案内を出して code 1 で終える。"""
        from typer.testing import CliRunner

        from reshog import cli, collect, report

        blocker = tmp_path / "file"  # ファイルなので、その下に置き場を作れない
        blocker.write_text("", encoding="utf-8")
        monkeypatch.setenv("RESHOG_CHURN_LOG", str(blocker / "churn.jsonl"))
        monkeypatch.setattr(report, "build_churn", lambda *a: _churn(2.0, _claude("bash")))
        monkeypatch.setattr(collect, "load_average", lambda: (1.0, 1.0, 1.0))
        result = CliRunner().invoke(cli.cpu_app, ["--record"])
        assert result.exit_code == 1
        assert "記録へ書けませんでした" in result.output
        assert "RESHOG_CHURN_LOG" in result.output

    def test_record_after_a_cut_off_line_starts_on_a_new_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """前の回が途中で切れていても、この回の記録はつながらず読める。"""
        (tmp_path / "churn.jsonl").write_text('{"at": "2026-10-', encoding="utf-8")
        code, out = self._run(monkeypatch, tmp_path, "--record")
        assert code == 0, out
        records, broken = trend.read_records(tmp_path / "churn.jsonl")
        assert (len(records), broken) == (1, 1)
