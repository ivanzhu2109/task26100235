"""输入类型定义：订单行与促销轮次。"""

from __future__ import annotations

from dataclasses import dataclass


def _require_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须是整数，得到 {value!r}")
    return value


@dataclass(frozen=True)
class OrderLine:
    """促销前单价已确定的订单行。

    line_no: 唯一正整数行号。
    unit_price: 整数分单价（非负）。
    quantity: 件数（正整数），件序号从 1 开始。
    """

    line_no: int
    unit_price: int
    quantity: int

    def __post_init__(self) -> None:
        _require_int("line_no", self.line_no)
        _require_int("unit_price", self.unit_price)
        _require_int("quantity", self.quantity)
        if self.line_no <= 0:
            raise ValueError(f"line_no 必须是正整数，得到 {self.line_no}")
        if self.unit_price < 0:
            raise ValueError(f"unit_price 不能为负，得到 {self.unit_price}")
        if self.quantity <= 0:
            raise ValueError(f"quantity 必须是正整数，得到 {self.quantity}")


@dataclass(frozen=True)
class Promotion:
    """一轮优惠。

    line_nos: 适用行号集合。
    threshold: 最低消费门槛（分），按适用行本轮开始时剩余实付合计判断。
    fixed_amount: 固定减免额（分），与 rate_bp 二选一。
    rate_bp: 整数万分比减免比例（0..10000），与 fixed_amount 二选一。
    """

    line_nos: frozenset[int]
    threshold: int = 0
    fixed_amount: int | None = None
    rate_bp: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_nos", frozenset(self.line_nos))
        if not self.line_nos:
            raise ValueError("line_nos 不能为空")
        for line_no in self.line_nos:
            _require_int("line_nos 元素", line_no)
            if line_no <= 0:
                raise ValueError(f"line_nos 元素必须是正整数，得到 {line_no}")
        _require_int("threshold", self.threshold)
        if self.threshold < 0:
            raise ValueError(f"threshold 不能为负，得到 {self.threshold}")
        if (self.fixed_amount is None) == (self.rate_bp is None):
            raise ValueError("fixed_amount 与 rate_bp 必须且只能指定一个")
        if self.fixed_amount is not None:
            _require_int("fixed_amount", self.fixed_amount)
            if self.fixed_amount < 0:
                raise ValueError(f"fixed_amount 不能为负，得到 {self.fixed_amount}")
        if self.rate_bp is not None:
            _require_int("rate_bp", self.rate_bp)
            if not 0 <= self.rate_bp <= 10000:
                raise ValueError(f"rate_bp 必须在 0..10000 之间，得到 {self.rate_bp}")

    @classmethod
    def fixed(cls, line_nos, threshold: int, amount: int) -> "Promotion":
        """构造固定减免轮次。"""
        return cls(frozenset(line_nos), threshold=threshold, fixed_amount=amount)

    @classmethod
    def rate(cls, line_nos, threshold: int, rate_bp: int) -> "Promotion":
        """构造比例减免轮次。"""
        return cls(frozenset(line_nos), threshold=threshold, rate_bp=rate_bp)
