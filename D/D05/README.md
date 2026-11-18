# D05：相关性加权的设施选址式集合覆盖 FL

入口：`python -m D.selection_batch --strategies FL ...`，完整命令见 D/README.md。

## 目标与步骤

候选集合 V，已选集合 S，r_j 为候选 j 的归一化相关性，
s_ij 为原始完整轮次的非负 TF-IDF 余弦相似度。空集合覆盖为 0：

F(S) = sum_{j in V} r_j * max_{i in S} s_ij

候选 i 的边际收益：

delta_F(i|S) = sum_j r_j * max(0, s_ij - max_{k in S} s_kj)

每轮在完整历史 Token 预算内按 delta_F / max(1, 实际新增 Token) 最大者选择，
同分按原始 rank。无可行候选、最大收益不大于 0 或候选耗尽时停止。
steps 保存 facility_gain、成本、比值、选择顺序；验证器用直接计算 F(S+i)-F(S) 复核边际收益。

## 来源与适配范围

参考 [PACMS v1, Section 3.1](https://arxiv.org/html/2606.20047v1#S3.SS1)，
采用相关性加权设施选址目标，属于本项目对照，不声称逐字复现其完整系统。

| 条件 | PACMS v1 | 本项目 D05 |
| --- | --- | --- |
| 相关性 | query/candidate embedding 非负余弦 | B 检索分数的候选内 min-max（全相等为 1） |
| 候选相似度 | embedding 非负余弦 | 原始完整轮次 TF-IDF 非负余弦 |
| 成本 | 目标约束使用候选 Token 加和 | 实际排序去重后的历史增量，分母下限 1 |
| 实现 | CELF lazy greedy | 每步重新评估全部可行候选 |
| 候选与必选集合 | 混合上下文池及 mandatory 集合 | B 交付的最多 100 条原始轮次，无必选集合 |

因此不把论文针对其设定的近似保证或准确率结论移用于本实现。
当前 greedy 规则不保证对非加性 Token 约束全局最优。
lambda/gamma 对 FL 不生效，在配置中均规范为 0。
与其余办法使用同一候选、完整原文、阅读分词器、2048 历史预算与序列化。
