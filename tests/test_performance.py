"""规模与性能验收：500 行 x 每行 100 万件 x 连续 20 轮交叠促销。

要求：单次结算 < 3 秒；结算及查询峰值内存 < 128 MiB；
已结算快照上 1000 次单区间查询 < 1 秒；全部件分区报价之和 == 整单应付。
"""

import time
import tracemalloc

from promo_settlement import OrderLine, PromotionRound, settle

NUM_LINES = 500
QUANTITY = 1_000_000
NUM_ROUNDS = 20
QUERY_COUNT = 1000
SETTLE_TIME_LIMIT = 3.0
QUERY_TIME_LIMIT = 1.0
MEMORY_LIMIT = 128 * 1024 * 1024


def _inputs():
    lines = [
        OrderLine(
            line_id=index + 1,
            unit_price=10_000 + index * 7 % 5_000,
            quantity=QUANTITY,
        )
        for index in range(NUM_LINES)
    ]
    rounds = []
    for r in range(NUM_ROUNDS):
        # 适用行集合相互交叠的滑动窗口。
        start = (r * 97) % NUM_LINES
        line_ids = [(start + offset) % NUM_LINES + 1 for offset in range(250)]
        if r % 2 == 0:
            rounds.append(
                PromotionRound.fixed(line_ids, amount=1_000_000 + r * 13, threshold=500_000)
            )
        else:
            rounds.append(
                PromotionRound.percent(line_ids, basis_points=100 + r * 211 % 3000, threshold=1)
            )
    return lines, rounds


def test_large_order_performance():
    lines, rounds = _inputs()

    tracemalloc.start()
    started = time.perf_counter()
    snapshot = settle(lines, rounds)
    settle_elapsed = time.perf_counter() - started
    _, peak_after_settle = tracemalloc.get_traced_memory()

    assert settle_elapsed < SETTLE_TIME_LIMIT, f"结算耗时 {settle_elapsed:.2f}s"
    assert peak_after_settle < MEMORY_LIMIT, f"结算阶段峰值内存 {peak_after_settle}"

    # 1000 次单区间查询：覆盖单件、整行与行内任意区间。
    started = time.perf_counter()
    quoted = 0
    for index in range(QUERY_COUNT):
        line_id = index % NUM_LINES + 1
        kind = index % 3
        if kind == 0:
            item = index * 997 % QUANTITY + 1
            ranges = [(item, item)]
        elif kind == 1:
            ranges = [(1, QUANTITY)]
        else:
            lo = index * 991 % QUANTITY + 1
            hi = min(QUANTITY, lo + 999_983)
            ranges = [(lo, hi)]
        quoted += snapshot.refund_quote(line_id, ranges)
    query_elapsed = time.perf_counter() - started
    _, peak_after_queries = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert quoted > 0
    assert query_elapsed < QUERY_TIME_LIMIT, f"查询耗时 {query_elapsed:.2f}s"
    assert peak_after_queries < MEMORY_LIMIT, f"查询阶段峰值内存 {peak_after_queries}"

    # 全部件按分区报价，合计必须恰好等于整单应付。
    partition_total = 0
    chunk = 100_000
    for line_id in snapshot.line_ids:
        ranges = [
            (lo, min(lo + chunk - 1, QUANTITY))
            for lo in range(1, QUANTITY + 1, chunk)
        ]
        partition_total += snapshot.refund_quote(line_id, ranges)
    assert partition_total == snapshot.total_payable
