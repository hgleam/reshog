"""短命プロセスの記録(--record)と、出どころごとの増加(--trend)を扱う純粋関数群。

1 本ずつは軽い「繰り返し動くもの」(フック・statusline・プラグイン等)は、積み上がっても差分には
出ない。短命プロセスの表を 1 回 1 行で残し、直近と過去の平均を出どころ・中身の名前ごとに比べて、
増え始めたものを種類を問わず出す。
"""

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path

from . import churn, origin
from .constants import (
    CHURN_LOG_DEFAULT,
    CHURN_LOG_ENV,
    TREND_BASELINE,
    TREND_KINDS,
    TREND_MIN_PER_SECOND,
    TREND_RATIO,
    TREND_RECENT,
)
from .models import Churn, ChurnSource, Rise, Trend


def source_key(source: ChurnSource) -> str:
    """記録の出どころの名前。PJ が分かれば `PJ:起動元`、分からなければ起動元だけ。"""
    label = churn.source_label(source)
    return f"{origin.label(source.origin)}:{label}" if source.origin else label


def record_of(found: Churn, at: datetime, load: tuple[float, float, float]) -> dict[str, object]:
    """1 回分の記録(毎秒の本数に直す。数えた秒数が回ごとに違っても比べられるように)。

    Args:
        found: 短命プロセスの集計。
        at: 数えた時刻(タイムゾーン付き)。
        load: 負荷平均(1・5・15 分)。

    Returns:
        JSON にできる辞書。
    """
    by_source: Counter[str] = Counter()
    by_child: Counter[str] = Counter()
    for source in found.sources:
        by_source[source_key(source)] += source.count
        by_child.update(source.children)
    per = 1 / found.seconds if found.seconds > 0 else 0.0
    return {
        "at": at.isoformat(timespec="seconds"),
        "seconds": round(found.seconds, 2),
        "load": list(load),
        "per_second": round(found.per_second, 1),
        "by_source": {k: round(v * per, 2) for k, v in by_source.most_common()},
        "by_child": {k: round(v * per, 2) for k, v in by_child.most_common()},
    }


def to_line(record: Mapping[str, object]) -> str:
    """記録を 1 行の JSON にする。"""
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def read_records(path: Path) -> tuple[list[dict[str, object]], int]:
    """記録を読む。読めない行は捨てずに数える(読めなかったと何も無いを分ける)。

    Returns:
        (読めた記録, 読めなかった行の数)。空行は数えない。ファイルが無ければ ([], 0)。
    """
    if not path.exists():
        return [], 0
    records: list[dict[str, object]] = []
    broken = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            datetime.fromisoformat(str(rec["at"]))
            if not isinstance(rec.get("by_source"), dict) or not isinstance(
                rec.get("by_child"), dict
            ):
                raise ValueError("by_source / by_child が無い")
        except (ValueError, KeyError, TypeError):
            broken += 1
            continue
        records.append(rec)
    return records, broken


def rising(records: Iterable[Mapping[str, object]], now: datetime) -> Trend:
    """直近(TREND_RECENT)の平均が、過去(その前の TREND_BASELINE)の平均より増えたものを返す。

    下限(毎秒 TREND_MIN_PER_SECOND 本)以上で、過去の TREND_RATIO 倍を超えたものだけ。
    過去に無い名前は 0 から増えたとみなす。並びは増えた量の多い順。
    """
    recent: list[Mapping[str, object]] = []
    baseline: list[Mapping[str, object]] = []
    for rec in records:
        age = now - datetime.fromisoformat(str(rec["at"]))
        if age <= TREND_RECENT:
            recent.append(rec)
        elif age <= TREND_RECENT + TREND_BASELINE:
            baseline.append(rec)
    if not recent or not baseline:
        return Trend(recent=len(recent), baseline=len(baseline), rises=())
    rises = [
        Rise(kind=kind, name=name, recent=round(r, 2), baseline=round(b, 2))
        for kind, field in TREND_KINDS
        for name, r, b in _compare(recent, baseline, field)
        if r >= TREND_MIN_PER_SECOND and r > TREND_RATIO * b
    ]
    rises.sort(key=lambda x: x.recent - x.baseline, reverse=True)
    return Trend(recent=len(recent), baseline=len(baseline), rises=tuple(rises))


def _compare(
    recent: list[Mapping[str, object]], baseline: list[Mapping[str, object]], field: str
) -> list[tuple[str, float, float]]:
    """名前ごとに (名前, 直近の平均, 過去の平均)。記録に無い名前はその回 0 本とみなす。"""

    def mean(group: list[Mapping[str, object]]) -> dict[str, float]:
        total: Counter[str] = Counter()
        for rec in group:
            total.update(dict(rec[field]))  # type: ignore[call-overload]
        return {k: v / len(group) for k, v in total.items()}

    r, b = mean(recent), mean(baseline)
    return [(name, r[name], b.get(name, 0.0)) for name in r]


def log_path(env: Mapping[str, str]) -> Path:
    """記録の置き場。環境変数 CHURN_LOG_ENV があればそれ。"""
    given = env.get(CHURN_LOG_ENV)
    return Path(given) if given else Path.home().joinpath(*CHURN_LOG_DEFAULT)
