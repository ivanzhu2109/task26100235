"""规模与性能验收：500 行 × 每行 100 万件 × 20 轮优惠。"""

from __future__ import annotations

import random
import time
import tracemalloc

from promo_settlement import OrderLine, Promotion, settle

LINES = 500
QTY = 1_000_000
ROUNDS = 20
SETTLE_BUDGET_S = 3.0
QUERY_BUDGET_S = 1.0
MEMORY_BUDGET_BYTES = 128 * 1024 * 1024
QUERIES = 1000


def _inputs():
    rng = random.Random(35)
    lines = [OrderLine(i + 1, rng.randint(1, 10_000), QTY) for i in range(LINES)]
    promos = []
    for r in range(ROUNDS):
        subset = set(rng.sample(range(1, LINES + 1), rng.randint(50, LINES)))
        threshold = rng.randint(0, 10**8)
        if r % 2 == 0:
            promos.append(Promotion.fixed(subset, threshold, rng.randint(1, 10**7)))
        else:
            promos.append(Promotion.rate(subset, threshold, rng.randint(1, 10000)))
    return lines, promos


def test_large_scale_settle_and_query():
    lines, promos = _inputs()

    tracemalloc.start()
    start = time.perf_counter()
    snap = settle(lines, promos)
    settle_s = time.perf_counter() - start
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert settle_s < SETTLE_BUDGET_S, f"结算耗时 {settle_s:.2f}s 超限"
    assert peak < MEMORY_BUDGET_BYTES, f"峰值内存 {peak / 2**20:.1f} MiB 超限"

    # 1000 次单区间查询：覆盖单件、整行与行内任意区间。
    rng = random.Random(99)
    intervals = []
    for _ in range(QUERIES):
        line_no = rng.randint(1, LINES)
        kind = rng.random()
        if kind < 0.34:
            pos = rng.randint(1, QTY)
            intervals.append((line_no, [(pos, pos)]))
        elif kind < 0.67:
            intervals.append((line_no, [(1, QTY)]))
        else:
            a = rng.randint(1, QTY)
            b = rng.randint(a, QTY)
            intervals.append((line_no, [(a, b)]))
    start = time.perf_counter()
    results = [snap.query(no, iv) for no, iv in intervals]
    query_s = time.perf_counter() - start
    assert query_s < QUERY_BUDGET_S, f"查询耗时 {query_s:.2f}s 超限"
    assert all(res.final_paid >= 0 for res in results)

    # 全部件的分区报价之和等于整单应付。
    partition_total = 0
    chunk = 100_000
    for line_no in range(1, LINES + 1):
        batches = [(s, min(s + chunk - 1, QTY)) for s in range(1, QTY + 1, chunk)]
        partition_total += snap.refund_quote(line_no, batches)
    assert partition_total == snap.total_payable

    print(
        f"\n结算 {settle_s:.2f}s / 峰值内存 {peak / 2**20:.1f} MiB / "
        f"{QUERIES} 次查询 {query_s:.3f}s"
    )
