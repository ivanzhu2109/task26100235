"""业务规则测试：逐件暴力参考实现 + 随机对拍 + 门槛与批次不变性。"""

import random

import pytest

from promo_settlement import OrderLine, PromotionRound, settle


def brute_force(lines, rounds):
    """逐件模拟的参考实现。返回 (每轮逐件减免, 最终逐件实付)。"""
    values = {}  # (line_id, index) -> 当前实付
    for line in lines:
        for index in range(1, line.quantity + 1):
            values[(line.line_id, index)] = line.unit_price
    all_discounts = []
    for promotion in rounds:
        keys = [
            (line_id, index)
            for (line_id, index) in values
            if line_id in promotion.line_ids
        ]
        total = sum(values[key] for key in keys)
        discounts = {key: 0 for key in values}
        if total and total >= promotion.threshold:
            if promotion.fixed_amount is not None:
                discount = min(promotion.fixed_amount, total)
            else:
                discount = total * promotion.basis_points // 10000
            if discount:
                bases, fractions = {}, {}
                for key in keys:
                    product = values[key] * discount
                    bases[key] = product // total
                    fractions[key] = product % total
                remainder = discount - sum(bases[key] * 1 for key in keys)
                order = sorted(
                    (key for key in keys if fractions[key]),
                    key=lambda key: (-fractions[key], key[0], key[1]),
                )
                for key in order[:remainder]:
                    bases[key] += 1
                for key in keys:
                    assert bases[key] <= values[key]
                    discounts[key] = bases[key]
                    values[key] -= bases[key]
        all_discounts.append(discounts)
    return all_discounts, values


def random_case(rng):
    num_lines = rng.randint(1, 6)
    line_ids = rng.sample(range(1, 30), num_lines)
    lines = [
        OrderLine(line_id, rng.randint(0, 50), rng.randint(1, 10))
        for line_id in line_ids
    ]
    rounds = []
    for _ in range(rng.randint(1, 6)):
        subset = [lid for lid in line_ids if rng.random() < 0.7]
        threshold = rng.randint(0, 200)
        if rng.random() < 0.5:
            rounds.append(PromotionRound.fixed(subset, rng.randint(0, 100), threshold))
        else:
            rounds.append(PromotionRound.percent(subset, rng.randint(0, 10000), threshold))
    return lines, rounds


def ranges_covering(quantity, rng, pieces):
    """把 [1, quantity] 随机切成 pieces 段闭区间。"""
    cuts = sorted(rng.sample(range(1, quantity), min(pieces - 1, quantity - 1)))
    points = [1] + [c + 1 for c in cuts] + [quantity + 1]
    return [(points[i], points[i + 1] - 1) for i in range(len(points) - 1)]


@pytest.mark.parametrize("seed", range(300))
def test_matches_brute_force(seed):
    rng = random.Random(seed)
    lines, rounds = random_case(rng)
    rng.shuffle(lines)
    snapshot = settle(lines, rounds)
    all_discounts, values = brute_force(lines, rounds)

    assert snapshot.total_payable == sum(values.values())
    for line in lines:
        # 整行查询
        result = snapshot.query(line.line_id, [(1, line.quantity)])
        assert result.final_paid == sum(
            values[(line.line_id, i)] for i in range(1, line.quantity + 1)
        )
        for round_index, expected in enumerate(result.per_round_discounts):
            assert expected == sum(
                all_discounts[round_index][(line.line_id, i)]
                for i in range(1, line.quantity + 1)
            )
        # 逐件查询（单件即起止相同的区间）
        for index in range(1, line.quantity + 1):
            single = snapshot.query(line.line_id, [(index, index)])
            assert single.final_paid == values[(line.line_id, index)]
            assert single.per_round_discounts == tuple(
                all_discounts[r][(line.line_id, index)] for r in range(len(rounds))
            )
        # 随机多区间查询 + 批次划分不变性
        for pieces in (1, 2, 3):
            ranges = ranges_covering(line.quantity, rng, pieces)
            assert snapshot.refund_quote(line.line_id, ranges) == result.final_paid
            merged = snapshot.query(line.line_id, ranges)
            assert merged.per_round_discounts == result.per_round_discounts


def test_input_order_irrelevant():
    rng = random.Random(7)
    lines, rounds = random_case(rng)
    shuffled = list(lines)
    rng.shuffle(shuffled)
    a, b = settle(lines, rounds), settle(shuffled, rounds)
    assert a.total_payable == b.total_payable
    for line in lines:
        ra = a.query(line.line_id, [(1, line.quantity)])
        rb = b.query(line.line_id, [(1, line.quantity)])
        assert ra == rb


def test_threshold_boundary():
    # 行 1：10 件 × 10 分 = 100；行 2：10 件 × 5 分 = 50。
    lines = [OrderLine(1, 10, 10), OrderLine(2, 5, 10)]
    rounds = [
        # 第一轮减 50：行 1 每件 5 分，行 2 每件 2 分余 10 分按小数部分分配。
        PromotionRound.fixed({1, 2}, 50),
        # 第二轮门槛 100：剩余合计恰为 100，相等即满足。
        PromotionRound.fixed({1, 2}, 10, threshold=100),
        # 第三轮门槛 91：剩余合计 90，跌破门槛，本轮减免为零。
        PromotionRound.fixed({1, 2}, 10, threshold=91),
    ]
    snapshot = settle(lines, rounds)
    result1 = snapshot.query(1, [(1, 10)])
    result2 = snapshot.query(2, [(1, 10)])
    assert result1.per_round_discounts[2] == 0
    assert result2.per_round_discounts[2] == 0
    assert result1.per_round_discounts[0] + result2.per_round_discounts[0] == 50
    assert result1.per_round_discounts[1] + result2.per_round_discounts[1] == 10
    assert snapshot.total_payable == 150 - 50 - 10


def test_threshold_exactly_met_and_just_missed():
    lines = [OrderLine(1, 100, 3)]
    # 第一轮减 50%（150 分），剩余 150；第二轮门槛 150 恰好满足。
    met = settle(lines, [
        PromotionRound.percent({1}, 5000),
        PromotionRound.fixed({1}, 10, threshold=150),
    ])
    assert met.query(1, [(1, 3)]).per_round_discounts == (150, 10)
    # 门槛 151 则不满足。
    missed = settle(lines, [
        PromotionRound.percent({1}, 5000),
        PromotionRound.fixed({1}, 10, threshold=151),
    ])
    assert missed.query(1, [(1, 3)]).per_round_discounts == (150, 0)
    assert missed.total_payable == 150


def test_overlapping_applicable_sets():
    lines = [OrderLine(1, 100, 4), OrderLine(2, 100, 4), OrderLine(3, 100, 4)]
    rounds = [
        PromotionRound.fixed({1, 2}, 100),
        PromotionRound.percent({2, 3}, 2500),
        PromotionRound.fixed({1, 2, 3}, 30),
    ]
    snapshot = settle(lines, rounds)
    _, values = brute_force(lines, rounds)
    assert snapshot.total_payable == sum(values.values())
    for line in lines:
        assert snapshot.refund_quote(line.line_id, [(1, 4)]) == sum(
            values[(line.line_id, i)] for i in range(1, 5)
        )


def test_fixed_discount_capped_at_applicable_total():
    lines = [OrderLine(1, 10, 3)]
    snapshot = settle(lines, [PromotionRound.fixed({1}, 1000)])
    assert snapshot.total_payable == 0
    assert snapshot.query(1, [(1, 3)]).per_round_discounts == (30,)
    assert snapshot.refund_quote(1, [(1, 3)]) == 0


def test_zero_applicable_total_skips_round():
    lines = [OrderLine(1, 0, 5), OrderLine(2, 10, 5)]
    snapshot = settle(lines, [PromotionRound.fixed({1}, 100), PromotionRound.fixed({2}, 5)])
    assert snapshot.query(1, [(1, 5)]).per_round_discounts == (0, 0)
    assert snapshot.query(2, [(1, 5)]).per_round_discounts == (0, 5)
    assert snapshot.total_payable == 45


def test_snapshot_isolated_from_input_mutation():
    lines = [OrderLine(1, 10, 2)]
    rounds = [PromotionRound.fixed({1}, 5)]
    snapshot = settle(lines, rounds)
    lines.clear()
    rounds.clear()
    assert snapshot.total_payable == 15
    assert snapshot.refund_quote(1, [(1, 2)]) == 15


def test_validation_errors():
    snapshot = settle([OrderLine(1, 10, 2)], [])
    with pytest.raises(KeyError):
        snapshot.query(99, [(1, 1)])
    with pytest.raises(ValueError):
        snapshot.query(1, [(1, 3)])
    with pytest.raises(ValueError):
        snapshot.query(1, [(1, 1), (1, 2)])
    with pytest.raises(ValueError):
        settle([OrderLine(1, 1, 1), OrderLine(1, 1, 1)], [])
    with pytest.raises(ValueError):
        settle([OrderLine(1, 1, 1)], [PromotionRound.fixed({2}, 1)])
