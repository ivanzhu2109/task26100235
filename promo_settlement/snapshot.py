"""结算快照：保存每行每轮减免与最终实付的紧凑结构，支持区间查询与退款报价。

存储说明：同一行内，逐件实付（以及每轮逐件减免）是关于件序号的阶梯函数，
段数不超过轮次 + 1，因此每行每轮只保存若干 (截止件序号, 分值) 段，
百万件行也只占几十字节。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntervalResult:
    """单个闭区间 [start, end] 的查询结果。"""

    start: int
    end: int
    round_discounts: tuple[int, ...]  # 每轮减免合计（分），按轮次顺序
    final_paid: int  # 最终实付合计（分）


@dataclass(frozen=True)
class LineQueryResult:
    """一行内多个互不重叠区间的查询结果。"""

    line_no: int
    intervals: tuple[IntervalResult, ...]

    @property
    def round_discounts(self) -> tuple[int, ...]:
        """所有区间合并后的每轮减免合计。"""
        if not self.intervals:
            return ()
        width = len(self.intervals[0].round_discounts)
        totals = [0] * width
        for interval in self.intervals:
            for idx, value in enumerate(interval.round_discounts):
                totals[idx] += value
        return tuple(totals)

    @property
    def final_paid(self) -> int:
        """所有区间合并后的最终实付合计。"""
        return sum(interval.final_paid for interval in self.intervals)


@dataclass(frozen=True)
class _LineData:
    """单行结算数据（包内使用）。

    final_segments: (截止件序号, 单件最终实付) 按件序号升序。
    round_segments: 每轮 (截止件序号, 单件本轮减免) 按件序号升序。
    """

    quantity: int
    final_segments: tuple[tuple[int, int], ...]
    round_segments: tuple[tuple[tuple[int, int], ...], ...]


def _range_sum(segments: tuple[tuple[int, int], ...], start: int, end: int) -> int:
    """阶梯函数在闭区间 [start, end] 上的合计。"""
    total = 0
    seg_start = 1
    for seg_end, value in segments:
        if seg_end < start:
            seg_start = seg_end + 1
            continue
        if seg_start > end:
            break
        overlap = min(end, seg_end) - max(start, seg_start) + 1
        if overlap > 0:
            total += value * overlap
        if seg_end >= end:
            break
        seg_start = seg_end + 1
    return total


def _check_intervals(quantity: int, intervals: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """校验区间合法性：界内、start<=end、互不重叠。返回按起点排序的区间。"""
    if not intervals:
        raise ValueError("intervals 不能为空")
    normalized = []
    for interval in intervals:
        start, end = interval
        if not (1 <= start <= end <= quantity):
            raise ValueError(f"区间 ({start}, {end}) 超出 1..{quantity} 或起止颠倒")
        normalized.append((start, end))
    normalized.sort()
    for prev, curr in zip(normalized, normalized[1:]):
        if curr[0] <= prev[1]:
            raise ValueError(f"区间 {prev} 与 {curr} 重叠")
    return tuple(normalized)


class SettlementSnapshot:
    """订单结算快照（进程内存，只读）。结算完成后与后续价格/促销配置无关。"""

    def __init__(self, lines: dict[int, _LineData], round_count: int) -> None:
        self._lines = dict(lines)
        self._round_count = round_count
        self._total_payable = sum(
            _range_sum(data.final_segments, 1, data.quantity) for data in self._lines.values()
        )

    @classmethod
    def _build(cls, lines: dict[int, "_LineData"], round_count: int) -> "SettlementSnapshot":
        return cls(lines, round_count)

    @property
    def line_nos(self) -> tuple[int, ...]:
        return tuple(sorted(self._lines))

    @property
    def round_count(self) -> int:
        return self._round_count

    @property
    def total_payable(self) -> int:
        """整单结算应付（分）。"""
        return self._total_payable

    def line_quantity(self, line_no: int) -> int:
        return self._line(line_no).quantity

    def query(self, line_no: int, intervals: list[tuple[int, int]]) -> LineQueryResult:
        """查询指定行的若干互不重叠闭区间：每轮减免合计与最终实付合计。"""
        data = self._line(line_no)
        checked = _check_intervals(data.quantity, intervals)
        results = []
        for start, end in checked:
            per_round = tuple(
                _range_sum(round_segs, start, end) for round_segs in data.round_segments
            )
            final_paid = _range_sum(data.final_segments, start, end)
            results.append(IntervalResult(start, end, per_round, final_paid))
        return LineQueryResult(line_no, tuple(results))

    def refund_quote(self, line_no: int, intervals: list[tuple[int, int]]) -> int:
        """退款报价：所选件在快照中的最终实付合计（分）。不修改快照。"""
        data = self._line(line_no)
        checked = _check_intervals(data.quantity, intervals)
        return sum(_range_sum(data.final_segments, start, end) for start, end in checked)

    def _line(self, line_no: int) -> _LineData:
        try:
            return self._lines[line_no]
        except KeyError:
            raise KeyError(f"未知行号 {line_no}") from None
