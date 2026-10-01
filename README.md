# promo_settlement

B2B 订单促销结算与退款计价库（纯 Python，无第三方依赖）。订单结算快照保存在
进程内存中，由上层直接调用；结算结果与输入行顺序无关，且不受后续价格或
促销配置变化影响。

## 安装 / 引入

源码即库，把 `promo_settlement/` 目录放到项目可导入路径下即可：

```python
from promo_settlement import OrderLine, Promotion, settle
```

## 快速开始

```python
from promo_settlement import OrderLine, Promotion, settle

# 订单行：行号（唯一正整数）、整数分单价、件数
lines = [OrderLine(1, 1, 2), OrderLine(2, 1, 2)]

# 促销轮次，按给定顺序逐轮执行；fixed_amount 与 rate_bp 二选一
promotions = [
    Promotion.fixed({1, 2}, threshold=0, amount=2),   # 全部件减 2 分
    Promotion.rate({1, 2}, threshold=0, rate_bp=5000) # 再减剩余金额的 50%
]

snapshot = settle(lines, promotions)

# 区间查询：每轮减免合计 + 最终实付合计（闭区间，互不重叠，可多个）
res = snapshot.query(line_no=2, intervals=[(1, 1), (2, 2)])
res.round_discounts   # 每轮减免合计，如 (0, 1)
res.final_paid        # 最终实付合计，如 1
res.intervals         # 每个区间各自的 IntervalResult

# 退款报价：所选件在原快照中的最终实付，不修改快照
snapshot.refund_quote(2, [(2, 2)])   # 1
snapshot.total_payable               # 整单结算应付
```

## 规则要点

- 结算身份为 (行号, 件序号)，件序号从 1 开始；同一行各件初始单价相同。
- 每轮门槛按适用行在本轮开始时的剩余实付合计判断，相等即满足；
  未达门槛或合计为零时本轮减免为零。
- 固定减免最多扣完适用金额；比例减免 = 适用金额 × 万分比，向下取整到分。
- 总减免按逐件当前实付占比分摊：整数分部分直接归属，剩余分数按
  （小数部分降序、行号升序、件序号升序）逐件补 1 分；零实付件不参与分摊，
  任何件实付不为负。
- 退款报价只读快照，不重跑优惠、不重新检查门槛；同一批件任意拆分报价，
  合计相同；整单报价等于结算应付。

## 性能

同一行内逐件实付/减免是关于件序号的阶梯函数（段数 ≤ 轮次 + 1），库按段
压缩存储，因此耗时与内存只取决于行数与轮次，与件数无关。实测
500 行 × 每行 100 万件 × 20 轮：结算约 0.1 s、峰值内存约 1.2 MiB、
1000 次单区间查询约 4 ms（要求分别为 3 s / 128 MiB / 1 s）。

## 测试

```bash
python3 -m pytest tests/ -q
```

- `tests/test_settlement.py`：验收用例、门槛临界、适用行交叠、零实付件、
  批次划分不变性、快照隔离，以及 200 组随机订单与逐件暴力参考实现交叉验证。
- `tests/test_performance.py`：大宗订单规模下的耗时、内存与分区报价一致性。
