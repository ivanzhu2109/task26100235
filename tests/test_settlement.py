"""结算规则测试：含逐件暴力参考实现交叉验证。"""

from __future__ import annotations

import random

import pytest

from promo_settlement import OrderLine, Promotion, settle


def brute_force(lines, promotions):
    """逐件模拟业务规则的参考实现。

    返回 (每行每轮逐件减免, 每行逐件最终实付)，键为行号，
    值为列表（索引 = 件序号 - 1）。
    """
    paid = {l.line_no: [l.unit_price] * l.quantity for l in lines}
    discounts = {l.line_no: [] for l in lines}
    for promo in promotions:
        app = sum(p for no in promo.line_nos for p in paid[no])
        total = 0
        if app > 0 and app >= promo.threshold:
            if promo.fixed_amount is not None:
                total = min(promo.fixed_amount, app)
            else:
                total = app * promo.rate_bp // 10000
        round_disc = {no: [0] * len(paid[no]) for no in paid}
        if total > 0:
            items = []  # (行号, 件序号, 整数分, 余数)
            distributed = 0
            for no in sorted(promo.line_nos):
                for idx, p in enumerate(paid[no]):
                    if p == 0:
                        continue
                    q, rem = divmod(total * p, app)
                    items.append((no, idx, q, rem))
                    distributed += q
            remainder = total - distributed
            bumps = {}
            eligible = sorted(
                (it for it in items if it[3] > 0), key=lambda it: (-it[3], it[0], it[1])
            )
            for no, idx, _q, _rem in eligible:
                if remainder == 0:
                    break
                bumps[(no, idx)] = 1
                remainder -= 1
            assert remainder == 0
            for no, idx, q, _rem in items:
                disc = q + bumps.get((no, idx), 0)
                round_disc[no][idx] = disc
                paid[no][idx] -= disc
                assert paid[no][idx] >= 0
        for no in paid:
            discounts[no].append(round_disc[no])
    return discounts, paid


def assert_matches_brute_force(lines, promotions):
    discounts, paid = brute_force(lines, promotions)
    snap = settle(lines, promotions)
    for line in lines:
        no, qty = line.line_no, line.quantity
        whole = snap.query(no, [(1, qty)])
        for r in range(len(promotions)):
            assert whole.round_discounts[r] == sum(discounts[no][r]), (no, r)
        assert whole.final_paid == sum(paid[no])
        # 逐件查询（单件区间）
        for idx in range(1, qty + 1):
            single = snap.query(no, [(idx, idx)])
            assert single.final_paid == paid[no][idx - 1], (no, idx)
            for r in range(len(promotions)):
                assert single.round_discounts[r] == discounts[no][r][idx - 1], (no, idx, r)
    assert snap.total_payable == sum(sum(p) for p in paid.values())
    return snap


class TestAcceptance:
    """验收用例：两行各2件、单价1分，先减2分再减剩余50%。"""

    promos = [Promotion.fixed({1, 2}, 0, 2), Promotion.rate({1, 2}, 0, 5000)]

    def test_final_paid_per_item(self):
        snap = settle([OrderLine(1, 1, 2), OrderLine(2, 1, 2)], self.promos)
        assert snap.query(1, [(1, 1)]).final_paid == 0
        assert snap.query(1, [(2, 2)]).final_paid == 0
        assert snap.query(2, [(1, 1)]).final_paid == 0
        assert snap.query(2, [(2, 2)]).final_paid == 1
        assert snap.total_payable == 1

    def test_input_order_irrelevant(self):
        snap = settle([OrderLine(2, 1, 2), OrderLine(1, 1, 2)], self.promos)
        assert snap.query(2, [(2, 2)]).final_paid == 1
        assert snap.total_payable == 1

    def test_refund_quotes_match(self):
        snap = settle([OrderLine(1, 1, 2), OrderLine(2, 1, 2)], self.promos)
        assert snap.refund_quote(1, [(1, 2)]) == 0
        assert snap.refund_quote(2, [(1, 1)]) == 0
        assert snap.refund_quote(2, [(2, 2)]) == 1
        assert snap.refund_quote(2, [(1, 2)]) == 1


class TestThreshold:
    def test_exact_threshold_met(self):
        # 第一轮减5分后行1剩余5分，第二轮门槛5分恰好满足。
        lines = [OrderLine(1, 10, 1)]
        promos = [Promotion.fixed({1}, 0, 5), Promotion.fixed({1}, 5, 2)]
        snap = settle(lines, promos)
        res = snap.query(1, [(1, 1)])
        assert res.round_discounts == (5, 2)
        assert res.final_paid == 3

    def test_threshold_just_missed(self):
        # 第一轮减6分后行1剩余4分，第二轮门槛5分不满足，减免为零。
        lines = [OrderLine(1, 10, 1)]
        promos = [Promotion.fixed({1}, 0, 6), Promotion.fixed({1}, 5, 2)]
        snap = settle(lines, promos)
        res = snap.query(1, [(1, 1)])
        assert res.round_discounts == (6, 0)
        assert res.final_paid == 4

    def test_zero_applicable_amount_blocks_round(self):
        # 第一轮扣完后适用金额为零，后续轮次减免为零。
        lines = [OrderLine(1, 10, 2)]
        promos = [Promotion.fixed({1}, 0, 100), Promotion.rate({1}, 0, 5000)]
        snap = settle(lines, promos)
        res = snap.query(1, [(1, 2)])
        assert res.round_discounts == (20, 0)
        assert res.final_paid == 0

    def test_fixed_capped_at_applicable(self):
        lines = [OrderLine(1, 3, 2)]
        snap = settle(lines, [Promotion.fixed({1}, 0, 100)])
        assert snap.query(1, [(1, 2)]).round_discounts == (6,)
        assert snap.total_payable == 0


class TestOverlappingAndRules:
    def test_overlapping_line_sets(self):
        lines = [OrderLine(1, 100, 3), OrderLine(2, 50, 4), OrderLine(3, 20, 5)]
        promos = [
            Promotion.fixed({1, 2}, 0, 70),
            Promotion.rate({2, 3}, 10, 2500),
            Promotion.fixed({1, 2, 3}, 0, 13),
        ]
        assert_matches_brute_force(lines, promos)

    def test_rate_round_uses_post_discount_amounts(self):
        # 第二轮比例减免必须基于第一轮分摊后的逐件实付。
        lines = [OrderLine(1, 100, 2), OrderLine(2, 100, 2)]
        promos = [Promotion.rate({1}, 0, 5000), Promotion.rate({1, 2}, 0, 5000)]
        assert_matches_brute_force(lines, promos)

    def test_zero_paid_items_get_no_discount(self):
        lines = [OrderLine(1, 0, 3), OrderLine(2, 10, 3)]
        promos = [Promotion.fixed({1, 2}, 0, 7)]
        snap = settle(lines, promos)
        assert snap.query(1, [(1, 3)]).round_discounts == (0,)
        assert_matches_brute_force(lines, promos)

    def test_randomized_cross_check(self):
        rng = random.Random(20261001)
        for _ in range(200):
            n_lines = rng.randint(1, 5)
            lines = [
                OrderLine(i + 1, rng.randint(0, 500), rng.randint(1, 12))
                for i in range(n_lines)
            ]
            promos = []
            for _ in range(rng.randint(1, 6)):
                subset = set(rng.sample(range(1, n_lines + 1), rng.randint(1, n_lines)))
                if rng.random() < 0.5:
                    promos.append(
                        Promotion.fixed(subset, rng.randint(0, 200), rng.randint(0, 300))
                    )
                else:
                    promos.append(
                        Promotion.rate(subset, rng.randint(0, 200), rng.randint(0, 10000))
                    )
            assert_matches_brute_force(lines, promos)


class TestRefundAndSnapshot:
    def test_batch_split_invariant(self):
        rng = random.Random(7)
        lines = [OrderLine(1, 97, 100), OrderLine(2, 33, 40)]
        promos = [Promotion.fixed({1, 2}, 0, 500), Promotion.rate({1}, 0, 3333)]
        snap = settle(lines, promos)
        whole = snap.refund_quote(1, [(1, 100)])
        singletons = sum(snap.refund_quote(1, [(i, i)]) for i in range(1, 101))
        assert whole == singletons
        # 随机划分批次
        points = sorted(rng.sample(range(1, 100), 9))
        batches, prev = [], 1
        for p in points + [100]:
            batches.append((prev, p))
            prev = p + 1
        assert sum(snap.refund_quote(1, [b]) for b in batches) == whole
        assert snap.refund_quote(1, batches) == whole

    def test_full_order_quote_equals_payable(self):
        lines = [OrderLine(1, 55, 30), OrderLine(2, 71, 25)]
        promos = [Promotion.fixed({1, 2}, 0, 321), Promotion.rate({2}, 0, 1234)]
        snap = settle(lines, promos)
        total = sum(
            snap.refund_quote(l.line_no, [(1, l.quantity)]) for l in lines
        )
        assert total == snap.total_payable

    def test_quote_does_not_modify_snapshot(self):
        lines = [OrderLine(1, 10, 5)]
        snap = settle(lines, [Promotion.fixed({1}, 0, 7)])
        before = snap.query(1, [(1, 5)])
        snap.refund_quote(1, [(1, 3)])
        snap.refund_quote(1, [(4, 5)])
        after = snap.query(1, [(1, 5)])
        assert before == after

    def test_snapshot_isolated_from_later_settles(self):
        lines = [OrderLine(1, 10, 5)]
        snap1 = settle(lines, [Promotion.fixed({1}, 0, 7)])
        settle(lines, [Promotion.fixed({1}, 0, 50), Promotion.rate({1}, 0, 9000)])
        assert snap1.query(1, [(1, 5)]).round_discounts == (7,)
        assert snap1.total_payable == 43

    def test_multi_interval_query(self):
        lines = [OrderLine(1, 10, 10)]
        snap = settle(lines, [Promotion.fixed({1}, 0, 15)])
        res = snap.query(1, [(1, 2), (5, 5), (8, 10)])
        parts = [snap.query(1, [iv]) for iv in [(1, 2), (5, 5), (8, 10)]]
        assert res.final_paid == sum(p.final_paid for p in parts)
        assert res.round_discounts[0] == sum(p.round_discounts[0] for p in parts)
        with pytest.raises(ValueError):
            snap.query(1, [(1, 3), (3, 5)])
