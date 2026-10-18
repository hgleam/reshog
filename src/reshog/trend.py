"""短命プロセスの記録(--record)と、出どころごとの増加(--trend)を扱う純粋関数群。

1 本ずつは軽い「繰り返し動くもの」(フック・statusline・プラグイン等)は、積み上がっても差分には
出ない。短命プロセスの表を 1 回 1 行で残し、直近と過去の平均を出どころ・中身の名前ごとに比べて、
増え始めたものを種類を問わず出す。
"""

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
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

    読めない行: JSON でない・UTF-8 でない・`at` がタイムゾーン付きの時刻でない・
    by_source / by_child が「名前 → 有限の数」の辞書でない。

    Returns:
        (読めた記録, 読めなかった行の数)。空行は数えない。ファイルが無ければ ([], 0)。
    """
    if not path.exists():
        return [], 0
    records: list[dict[str, object]] = []
    broken = 0
    for raw in path.read_bytes().splitlines():
        if not raw.strip():
            continue
        try:
            records.append(_parse_record(raw.decode("utf-8")))
        except (ValueError, KeyError, TypeError):  # UnicodeDecodeError は ValueError の子
            broken += 1
    return records, broken


def _parse_record(line: str) -> dict[str, object]:
    """1 行を記録として検める。合わなければ ValueError / KeyError / TypeError。"""
    rec = json.loads(line)
    if not isinstance(rec, dict):
        raise TypeError("記録が辞書でない")
    if datetime.fromisoformat(str(rec["at"])).tzinfo is None:
        raise ValueError("at にタイムゾーンが無い(比べる時刻と引き算できない)")
    for _, field in TREND_KINDS:
        counts = rec.get(field)
        if not isinstance(counts, dict) or not all(_is_rate(v) for v in counts.values()):
            raise ValueError(f"{field} が名前 → 有限の数の辞書でない")
    return rec


def _is_rate(value: object) -> bool:
    """毎秒の本数として使える値か(bool・nan・inf・文字列を弾く)。"""
    return (
        isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
    )


def rising(records: Iterable[Mapping[str, object]], now: datetime) -> Trend:
    """直近(TREND_RECENT)の平均が、過去(その前の TREND_BASELINE)の平均より増えたものを返す。

    下限(毎秒 TREND_MIN_PER_SECOND 本)以上で、過去の TREND_RATIO 倍を超えたものだけ。
    時刻が now より先の記録は比べず、future に数える。
    過去に無い名前は 0 から増えたとみなす。並びは増えた量の多い順。
    """
    recent: list[Mapping[str, object]] = []
    baseline: list[Mapping[str, object]] = []
    future = 0
    for rec in records:
        age = now - datetime.fromisoformat(str(rec["at"]))
        if age < timedelta(0):
            future += 1  # 時計のずれ等。直近に混ぜると直近の平均が実際と違う回で決まる
        elif age <= TREND_RECENT:
            recent.append(rec)
        elif age <= TREND_RECENT + TREND_BASELINE:
            baseline.append(rec)
    if not recent or not baseline:
        return Trend(recent=len(recent), baseline=len(baseline), rises=(), future=future)
    rises = [
        Rise(kind=kind, name=name, recent=round(r, 2), baseline=round(b, 2))
        for kind, field in TREND_KINDS
        for name, r, b in _compare(recent, baseline, field)
        if r >= TREND_MIN_PER_SECOND and r > TREND_RATIO * b
    ]
    rises.sort(key=lambda x: x.recent - x.baseline, reverse=True)
    return Trend(
        recent=len(recent), baseline=len(baseline), rises=tuple(rises), future=future
    )


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
