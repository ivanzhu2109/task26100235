"""结算引擎：逐轮执行促销并生成快照。"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .models import OrderLine, PromotionRound
from .snapshot import SettlementSnapshot, _LineSnapshot

# 段用 [end, value] 列表表示，便于就地合并；件序号为 (prev_end, end]。


class _LineState:
    """结算过程中单行的可变状态（行程压缩）。"""

    __slots__ = ("line_id", "quantity", "segments", "discounts")

    def __init__(self, line_id: int, unit_price: int, quantity: int) -> None:
        self.line_id = line_id
        self.quantity = quantity
        self.segments: List[List[int]] = [[quantity, unit_price]]
        self.discounts: List[Optional[Tuple[Tuple[int, int], ...]]] = []

    def total(self) -> int:
        total = 0
        start = 1
        for end, value in self.segments:
            total += value * (end - start + 1)
            start = end + 1
        return total

    def apply_round(
        self, bases: Sequence[int], plus_one: Dict[int, int]
    ) -> None:
        """按每段基础减免 base 与补 1 分的件数 k 更新逐件实付。"""
        new_segments: List[List[int]] = []
        discount_segments: List[List[int]] = []
        start = 1
        for idx, (end, value) in enumerate(self.segments):
            base = bases[idx]
            extra = plus_one.get(idx, 0)
            count = end - start + 1
            if extra <= 0:
                pieces = ((end, value - base),)
            elif extra >= count:
                pieces = ((end, value - base - 1),)
            else:
                pieces = (
                    (start + extra - 1, value - base - 1),
                    (end, value - base),
                )
            for piece_end, piece_value in pieces:
                _push(new_segments, piece_end, piece_value)
                _push(discount_segments, piece_end, value - piece_value)
            start = end + 1
        self.segments = new_segments
        self.discounts.append(tuple((end, value) for end, value in discount_segments))


def _push(segments: List[List[int]], end: int, value: int) -> None:
    if segments and segments[-1][1] == value:
        segments[-1][0] = end
    else:
        segments.append([end, value])


def settle(
    lines: Sequence[OrderLine], rounds: Sequence[PromotionRound]
) -> SettlementSnapshot:
    """执行全部促销轮次，返回不可变结算快照。"""
    states: Dict[int, _LineState] = {}
    for line in lines:
        if line.line_id in states:
            raise ValueError(f"行号重复: {line.line_id}")
        states[line.line_id] = _LineState(line.line_id, line.unit_price, line.quantity)

    for promotion in rounds:
        _apply_round(states, promotion)

    snapshot_lines = {
        line_id: _LineSnapshot(
            quantity=state.quantity,
            segments=tuple((end, value) for end, value in state.segments),
            discounts=tuple(state.discounts),
        )
        for line_id, state in states.items()
    }
    total_payable = sum(state.total() for state in states.values())
    return SettlementSnapshot(snapshot_lines, len(rounds), total_payable)


def _apply_round(states: Dict[int, _LineState], promotion: PromotionRound) -> None:
    applicable_ids = set()
    applicable: List[_LineState] = []
    for line_id in sorted(promotion.line_ids):
        state = states.get(line_id)
        if state is None:
            raise ValueError(f"促销引用了未知行号: {line_id}")
        applicable_ids.add(line_id)
        applicable.append(state)

    # 每轮都要为全部行留下记录（不适用的行为 None），保持逐轮下标对齐。
    for line_id, state in states.items():
        if line_id not in applicable_ids:
            state.discounts.append(None)

    applicable_total = sum(state.total() for state in applicable)
    if applicable_total == 0 or applicable_total < promotion.threshold:
        for state in applicable:
            state.discounts.append(None)
        return

    if promotion.fixed_amount is not None:
        discount = min(promotion.fixed_amount, applicable_total)
    else:
        discount = applicable_total * promotion.basis_points // 10000
    if discount == 0:
        for state in applicable:
            state.discounts.append(None)
        return

    # 每件理论减免 = 当前实付 * discount / applicable_total。
    # 同值件理论减免相同；补 1 分按 (小数部分降序, 行号, 件序号) 全局排序取前缀，
    # 因此每轮至多只有一段被部分拆分，段数保持 O(行数 + 轮数)。
    per_line_bases: Dict[int, List[int]] = {}
    groups: List[Tuple[int, int, int, int, int]] = []
    base_sum = 0
    for state in applicable:
        bases = [0] * len(state.segments)
        start = 1
        for idx, (end, value) in enumerate(state.segments):
            count = end - start + 1
            if value > 0:
                product = value * discount
                base = product // applicable_total
                fraction = product % applicable_total
                bases[idx] = base
                base_sum += base * count
                if fraction:
                    groups.append((-fraction, state.line_id, start, idx, count))
            start = end + 1
        per_line_bases[state.line_id] = bases

    remainder = discount - base_sum
    plus_one: Dict[int, Dict[int, int]] = {}
    if remainder:
        groups.sort()
        for _neg_fraction, line_id, _start, idx, count in groups:
            if remainder == 0:
                break
            extra = count if count < remainder else remainder
            plus_one.setdefault(line_id, {})[idx] = extra
            remainder -= extra

    for state in applicable:
        state.apply_round(per_line_bases[state.line_id], plus_one.get(state.line_id, {}))
