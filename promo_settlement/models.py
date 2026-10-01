"""输入模型：订单行与促销轮次定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional


@dataclass(frozen=True)
class OrderLine:
    """一条订单行。

    line_id: 唯一正整数行号。
    unit_price: 整数分单价（促销前），非负。
    quantity: 数量，正整数。件序号从 1 开始。
    """

    line_id: int
    unit_price: int
    quantity: int

    def __post_init__(self) -> None:
        if isinstance(self.line_id, bool) or not isinstance(self.line_id, int):
            raise TypeError("line_id 必须是整数")
        if self.line_id <= 0:
            raise ValueError("line_id 必须是正整数")
        if isinstance(self.unit_price, bool) or not isinstance(self.unit_price, int):
            raise TypeError("unit_price 必须是整数（分）")
        if self.unit_price < 0:
            raise ValueError("unit_price 不能为负")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity 必须是整数")
        if self.quantity <= 0:
            raise ValueError("quantity 必须是正整数")


@dataclass(frozen=True)
class PromotionRound:
    """一轮促销。

    line_ids: 适用行号集合。
    threshold: 最低消费门槛（分），按本轮开始时适用行剩余实付合计判断。
    fixed_amount: 固定减免额（分），与 basis_points 二选一。
    basis_points: 整数万分比减免比例，与 fixed_amount 二选一。
    """

    line_ids: FrozenSet[int]
    threshold: int = 0
    fixed_amount: Optional[int] = None
    basis_points: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_ids", frozenset(self.line_ids))
        for line_id in self.line_ids:
            if isinstance(line_id, bool) or not isinstance(line_id, int) or line_id <= 0:
                raise ValueError("line_ids 必须都是正整数")
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, int):
            raise TypeError("threshold 必须是整数（分）")
        if self.threshold < 0:
            raise ValueError("threshold 不能为负")
        has_fixed = self.fixed_amount is not None
        has_percent = self.basis_points is not None
        if has_fixed == has_percent:
            raise ValueError("fixed_amount 与 basis_points 必须且只能指定一个")
        if has_fixed:
            if isinstance(self.fixed_amount, bool) or not isinstance(self.fixed_amount, int):
                raise TypeError("fixed_amount 必须是整数（分）")
            if self.fixed_amount < 0:
                raise ValueError("fixed_amount 不能为负")
        if has_percent:
            if isinstance(self.basis_points, bool) or not isinstance(self.basis_points, int):
                raise TypeError("basis_points 必须是整数")
            if not 0 <= self.basis_points <= 10000:
                raise ValueError("basis_points 必须介于 0 和 10000 之间")

    @classmethod
    def fixed(
        cls, line_ids: Iterable[int], amount: int, threshold: int = 0
    ) -> "PromotionRound":
        """构造固定减免轮次。"""
        return cls(frozenset(line_ids), threshold, fixed_amount=amount)

    @classmethod
    def percent(
        cls, line_ids: Iterable[int], basis_points: int, threshold: int = 0
    ) -> "PromotionRound":
        """构造比例减免轮次。"""
        return cls(frozenset(line_ids), threshold, basis_points=basis_points)
