"""结算快照：只读的逐件结算结果与区间查询。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# 行程压缩段：(end, value)，表示件序号 (prev_end, end] 的每件取值 value。
_Segments = Tuple[Tuple[int, int], ...]


@dataclass(frozen=True)
class LineQueryResult:
    """单行多区间查询结果。

    per_round_discounts: 每一轮的减免合计（分），按轮次顺序。
    final_paid: 最终实付合计（分）。
    """

    per_round_discounts: Tuple[int, ...]
    final_paid: int


class _LineSnapshot:
    """单行结算结果（行程压缩存储）。"""

    __slots__ = ("quantity", "segments", "discounts")

    def __init__(
        self,
        quantity: int,
        segments: _Segments,
        discounts: Tuple[Optional[_Segments], ...],
    ) -> None:
        self.quantity = quantity
        self.segments = segments
        self.discounts = discounts


class SettlementSnapshot:
    """一次结算的不可变快照。退款报价只读，不修改快照。"""

    def __init__(
        self,
        lines: Dict[int, _LineSnapshot],
        num_rounds: int,
        total_payable: int,
    ) -> None:
        self._lines = lines
        self._num_rounds = num_rounds
        self._total_payable = total_payable

    @property
    def total_payable(self) -> int:
        """整单结算应付（分）。整单退款报价必须等于该值。"""
        return self._total_payable

    @property
    def num_rounds(self) -> int:
        return self._num_rounds

    @property
    def line_ids(self) -> Tuple[int, ...]:
        return tuple(sorted(self._lines))

    def query(
        self, line_id: int, ranges: Sequence[Tuple[int, int]]
    ) -> LineQueryResult:
        """查询指定行的若干互不重叠闭区间的每轮减免合计与最终实付合计。"""
        line = self._get_line(line_id)
        normalized = _normalize_ranges(line.quantity, ranges)
        per_round = tuple(
            _range_sum(discounts, normalized) if discounts is not None else 0
            for discounts in line.discounts
        )
        return LineQueryResult(
            per_round_discounts=per_round,
            final_paid=_range_sum(line.segments, normalized),
        )

    def refund_quote(self, line_id: int, ranges: Sequence[Tuple[int, int]]) -> int:
        """退款报价：所选件在原快照中的最终实付合计（分）。不修改快照。"""
        line = self._get_line(line_id)
        normalized = _normalize_ranges(line.quantity, ranges)
        return _range_sum(line.segments, normalized)

    def _get_line(self, line_id: int) -> _LineSnapshot:
        try:
            return self._lines[line_id]
        except KeyError:
            raise KeyError(f"未知的行号: {line_id!r}") from None


def _normalize_ranges(
    quantity: int, ranges: Sequence[Tuple[int, int]]
) -> Tuple[Tuple[int, int], ...]:
    """校验并排序闭区间；要求互不重叠。"""
    normalized = []
    for item in ranges:
        start, end = int(item[0]), int(item[1])
        if start < 1 or end > quantity or start > end:
            raise ValueError(
                f"区间 [{start}, {end}] 超出该行的件序号范围 [1, {quantity}]"
            )
        normalized.append((start, end))
    normalized.sort()
    previous_end = 0
    for start, end in normalized:
        if start <= previous_end:
            raise ValueError("查询区间不得重叠")
        previous_end = end
    return tuple(normalized)


def _range_sum(segments: _Segments, ranges: Tuple[Tuple[int, int], ...]) -> int:
    """对行程压缩段求若干闭区间的取值合计。"""
    if not ranges:
        return 0
    total = 0
    seg_start = 1
    range_index = 0
    last = len(ranges) - 1
    for seg_end, value in segments:
        while range_index < last and ranges[range_index][1] < seg_start:
            range_index += 1
        if value:
            idx = range_index
            while idx <= last and ranges[idx][0] <= seg_end:
                lo = max(ranges[idx][0], seg_start)
                hi = min(ranges[idx][1], seg_end)
                if lo <= hi:
                    total += value * (hi - lo + 1)
                idx += 1
        seg_start = seg_end + 1
        if ranges[last][1] < seg_start:
            break
    return total
