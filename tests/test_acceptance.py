"""验收用例：两行各 2 件、单价 1 分，先减 2 分再减剩余 50%。"""

from promo_settlement import OrderLine, PromotionRound, settle


def _rounds():
    return [
        PromotionRound.fixed({1, 2}, amount=2),
        PromotionRound.percent({1, 2}, basis_points=5000),
    ]


def _check(snapshot):
    assert snapshot.total_payable == 1
    # 只有行号较大那行的第二件实付 1 分，其余均为 0。
    assert snapshot.refund_quote(1, [(1, 1)]) == 0
    assert snapshot.refund_quote(1, [(2, 2)]) == 0
    assert snapshot.refund_quote(2, [(1, 1)]) == 0
    assert snapshot.refund_quote(2, [(2, 2)]) == 1
    # 每轮减免归属固定：第一轮 2 分全归行 1，第二轮 1 分归行 2 第一件。
    assert snapshot.query(1, [(1, 2)]).per_round_discounts == (2, 0)
    assert snapshot.query(2, [(1, 2)]).per_round_discounts == (0, 1)
    assert snapshot.query(2, [(1, 1)]).per_round_discounts == (0, 1)
    assert snapshot.query(2, [(2, 2)]).per_round_discounts == (0, 0)


def test_acceptance():
    _check(settle([OrderLine(1, 1, 2), OrderLine(2, 1, 2)], _rounds()))


def test_acceptance_input_order_irrelevant():
    _check(settle([OrderLine(2, 1, 2), OrderLine(1, 1, 2)], _rounds()))
