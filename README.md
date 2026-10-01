# promo_settlement

B2B 订单促销结算与退款计价库。纯 Python、零依赖，由上层直接调用；
订单结算快照保存在进程内存中，不依赖任何外部服务。

## 功能

- 多轮促销按给定顺序逐轮执行，支持固定减免与整数万分比比例减免，
  每轮可指定适用行集合与最低消费门槛。
- 每轮总减免按单件当前实付占比分摊到件：先取整数分，余数按
  「小数部分降序、行号升序、件序号升序」逐件补 1 分。
- 结算身份由（行号, 件序号）唯一确定，与输入行的排列顺序无关。
- 结算后生成不可变快照：支持按行的件序号闭区间查询每轮减免合计与
  最终实付合计，支持退款报价；报价只读快照，不重跑优惠、不改结果。

## 快速开始

```python
from promo_settlement import OrderLine, PromotionRound, settle

lines = [
    OrderLine(line_id=1, unit_price=100, quantity=5),   # 5 件，每件 100 分
    OrderLine(line_id=2, unit_price=80, quantity=3),
]
rounds = [
    PromotionRound.fixed({1, 2}, amount=200, threshold=500),   # 满 500 减 200
    PromotionRound.percent({2}, basis_points=5000),            # 行 2 再减 50%
]

snapshot = settle(lines, rounds)

snapshot.total_payable                 # 整单结算应付（分）
snapshot.query(1, [(1, 5)])            # LineQueryResult(per_round_discounts, final_paid)
snapshot.query(2, [(1, 2), (3, 3)])    # 一次查询多个互不重叠的闭区间
snapshot.refund_quote(1, [(2, 2)])     # 单件退款报价 = 该件最终实付
```

## 规则要点

- 门槛按本轮开始时适用行的剩余实付合计判断，相等即满足；
  未达门槛或合计为零时本轮减免为零。
- 固定减免最多扣完适用金额；比例减免 = 适用金额 x 万分比，向下取整到分。
- 零实付件不参与分摊；任何件最终实付不会为负。
- 退款报价等于所选件在原快照中的最终实付，与退货批次划分无关；
  整单报价恰好等于结算应付。
- 快照生成后不受后续价格或促销配置变化影响。

## 性能

内部按行做行程压缩（run-length）存储：同值件共享一段，每轮至多新增一个
拆分点，因此内存与查询开销只随「行数 + 轮数」增长，与件数无关。
在 500 行 x 每行 100 万件 x 20 轮交叠促销的规模下（见
`tests/test_performance.py`）：单次结算约 0.1 秒（要求 3 秒），
峰值内存约 1.2 MiB（要求 128 MiB），1000 次单区间查询约 4 毫秒（要求 1 秒）。

## 运行测试

```bash
python3 -m pytest tests/ -q
```

## 目录结构

- `promo_settlement/models.py` — 输入模型 `OrderLine` / `PromotionRound` 与校验
- `promo_settlement/engine.py` — 逐轮结算引擎（行程压缩分摊）
- `promo_settlement/snapshot.py` — 不可变快照、区间查询与退款报价
- `tests/` — 验收用例、规则对拍（逐件暴力参考实现 + 随机对拍）、性能验收
