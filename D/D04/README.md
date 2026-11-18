# D04：成本对照 C 与线索覆盖 Q

入口：`python -m D.selection_batch --strategies C Q ...`，完整命令见 D/README.md。

- C：`(r - lambda*d) / c`
- Q：`(r - lambda*d + gamma*g) / c`

r/d 与 D03 一致；c = max(1, 加入候选后完整材料 Token 数 - 当前材料 Token 数)。
实际可行性始终由最终完整材料长度判断，而非单轮长度之和。
重叠消息及分词边界可能使新增成本为零或负，分母下限为 1 并保留真实增量供追溯。

问题线索仅由问题文本自动提取：英文小写单词、数字以及逐个汉字，去除 D01 固定停用词。
候选是否覆盖线索，只看完整原始用户与紧邻消息，不使用参考答案或证据。
g = 本轮新增覆盖线索数 / max(1, 问题线索总数)；
记录 question_clues、covered_clues 及每一步 new_clues、coverage_gain。

默认 lambda=0.5、gamma=0.5，未调优。通过 `--coverage-weight 0` 关闭奖励，
相同 lambda 下 Q 与 C 应有完全一致的选择顺序、分数和阅读文本；该性质有回归测试与真实五题检查。
C 的无效 coverage 参数规范为 0，不让无效参数改变其配置身份。

每轮重算所有未选候选的实际成本与分数，在预算内按最高正分数选择；
同分按 rank，停止规则与 D03 一致。没有宣称启发式选择有全局最优保证。
