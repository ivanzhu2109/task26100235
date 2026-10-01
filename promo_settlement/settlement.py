"""结算引擎：逐轮执行优惠并生成快照。

核心不变量：同一行内逐件实付是关于件序号的非降阶梯函数，段数不超过
已执行轮次 + 1。每轮把总减免按"逐件理论减免 = 总减免 × 单件实付 / 适用金额"
分摊：整数分部分直接归属，剩余分数按 (小数部分降序, 行号升序, 件序号升序)
逐件补 1 分。由于每行每轮至多新增一个分段点，500 行 × 20 轮的规模下
内存与时间都与件数无关。
"""

from __future__ import annotations

from .snapshot import SettlementSnapshot, _LineData
from .types import OrderLine, Promotion


class _LineState:
    __slots__ = ("line_no", "quantity", "segments", "rounds")

    def __init__(self, line_no: int, quantity: int, unit_price: int) -> None:
        self.line_no = line_no
        self.quantity = quantity
        # 当前逐件实付阶梯函数：[(截止件序号, 单件实付)]，实付随件序号非降。
        self.segments: list[tuple[int, int]] = [(quantity, unit_price)]
        # 每轮逐件减免阶梯函数；空元组表示该行本轮减免全为零。
        self.rounds: list[tuple[tuple[int, int], ...]] = []


def _append_seg(segs: list[tuple[int, int]], end: int, value: int) -> None:
    """按升序追加分段，相邻同值合并。"""
    if segs and segs[-1][1] == value:
        segs[-1] = (end, value)
    else:
        segs.append((end, value))


def _line_total(state: _LineState) -> int:
    total = 0
    seg_start = 1
    for seg_end, paid in state.segments:
        total += paid * (seg_end - seg_start + 1)
        seg_start = seg_end + 1
    return total


def _run_round(states: list[_LineState], promo: Promotion) -> None:
    applicable = [st for st in states if st.line_no in promo.line_nos]
    app_amount = sum(_line_total(st) for st in applicable)

    total = 0
    if app_amount > 0 and app_amount >= promo.threshold:
        if promo.fixed_amount is not None:
            total = min(promo.fixed_amount, app_amount)
        else:
            total = app_amount * promo.rate_bp // 10000

    if total == 0:
        for st in states:
            st.rounds.append(())
        return

    # 逐段理论减免的整数分部分与小数部分（rem/app_amount）。
    share: dict[tuple[int, int], int] = {}
    groups: list[tuple[int, int, int, int, int]] = []  # (行号, 段起, 段止, 整数分, 余数)
    distributed = 0
    for st in applicable:
        seg_start = 1
        for seg_end, paid in st.segments:
            if paid > 0:
                quotient, rem = divmod(total * paid, app_amount)
                share[(st.line_no, seg_start)] = quotient
                groups.append((st.line_no, seg_start, seg_end, quotient, rem))
                distributed += quotient * (seg_end - seg_start + 1)
            seg_start = seg_end + 1

    # 剩余分数按 (小数部分降序, 行号升序, 件序号升序) 逐件补 1 分。
    bumps: dict[tuple[int, int], int] = {}
    remainder = total - distributed
    if remainder > 0:
        eligible = [g for g in groups if g[4] > 0]
        eligible.sort(key=lambda g: (-g[4], g[0], g[1]))
        for line_no, seg_start, seg_end, _q, _rem in eligible:
            if remainder == 0:
                break
            take = min(remainder, seg_end - seg_start + 1)
            bumps[(line_no, seg_start)] = take
            remainder -= take
        assert remainder == 0, "余数补给未能分完，分摊不变量被破坏"

    applicable_nos = promo.line_nos
    for st in states:
        if st.line_no not in applicable_nos:
            st.rounds.append(())
            continue
        new_paid: list[tuple[int, int]] = []
        disc: list[tuple[int, int]] = []
        seg_start = 1
        for seg_end, paid in st.segments:
            quotient = share.get((st.line_no, seg_start), 0)
            take = bumps.get((st.line_no, seg_start), 0)
            bump_end = seg_start + take - 1
            if take > 0:
                _append_seg(disc, bump_end, quotient + 1)
                _append_seg(new_paid, bump_end, paid - quotient - 1)
            if bump_end < seg_end:
                _append_seg(disc, seg_end, quotient)
                _append_seg(new_paid, seg_end, paid - quotient)
            seg_start = seg_end + 1
        assert all(paid >= 0 for _end, paid in new_paid), "单件实付不得为负"
        st.segments = new_paid
        st.rounds.append(tuple(disc))


def settle(
    lines: list[OrderLine] | tuple[OrderLine, ...],
    promotions: list[Promotion] | tuple[Promotion, ...],
) -> SettlementSnapshot:
    """对订单行按给定顺序逐轮执行优惠，返回只读结算快照。

    结果与输入行的排列顺序无关；快照生成后与后续价格或促销配置变化无关。
    """
    lines = list(lines)
    promotions = list(promotions)
    if not lines:
        raise ValueError("订单行不能为空")
    seen: set[int] = set()
    for line in lines:
        if line.line_no in seen:
            raise ValueError(f"行号 {line.line_no} 重复")
        seen.add(line.line_no)
    known = {line.line_no for line in lines}
    for idx, promo in enumerate(promotions):
        unknown = promo.line_nos - known
        if unknown:
            raise ValueError(f"第 {idx + 1} 轮优惠引用了未知行号 {sorted(unknown)}")

    # 只提取标量，快照不引用输入对象；按行号排序保证结果与输入顺序无关。
    states = sorted(
        (_LineState(line.line_no, line.quantity, line.unit_price) for line in lines),
        key=lambda st: st.line_no,
    )
    for promo in promotions:
        _run_round(states, promo)

    data = {
        st.line_no: _LineData(st.quantity, tuple(st.segments), tuple(st.rounds))
        for st in states
    }
    return SettlementSnapshot._build(data, len(promotions))
