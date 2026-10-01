"""B2B 订单促销结算与退款计价库。

用法概览：
    from promo_settlement import OrderLine, PromotionRound, settle

    lines = [OrderLine(line_id=1, unit_price=100, quantity=5)]
    rounds = [PromotionRound.fixed({1}, amount=200, threshold=0)]
    snapshot = settle(lines, rounds)
    snapshot.query(1, [(1, 5)])
    snapshot.refund_quote(1, [(1, 2)])
"""

from .engine import settle
from .models import OrderLine, PromotionRound
from .snapshot import LineQueryResult, SettlementSnapshot

__all__ = [
    "OrderLine",
    "PromotionRound",
    "LineQueryResult",
    "SettlementSnapshot",
    "settle",
]

__version__ = "0.1.0"
