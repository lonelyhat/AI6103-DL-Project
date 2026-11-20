# 历史归档

本目录保存早期方案和退役交接文件。当前运行入口、测试和实验结果由[仓库首页](../README.md)及 [E 线说明](../E/README.md)索引。

| 归档内容 | 归档原因与当前入口 |
| --- | --- |
| [E01 早期报告](E/E01/REPORT_CN.md)及[验收补充](E/E01/ACCEPTANCE_UPDATE_20261117.md) | 早期报告记录准备阶段。作业完成依据及现行操作说明见 [E01](../E/E01/README_CN.md)。 |
| [E01 旧输入导入工具](E/E01/prepare_input.py) | 一次性从早期 Qwen 批次压缩包提取开发输入。现行验证直接使用已固定的 [input_dev.json](../E/E01/input_dev.json) 和 [input_manifest.json](../E/E01/input_manifest.json)。历史复跑需显式给出旧 ZIP 的 `--archive` 与新文件的 `--output`。 |
| [E02 历史 F 兼容补丁](E/E02/handoff/README.md) | 对应 36dd0a8 的临时交接。现行项目已具备兼容接口，入口见 [F 评分配置](../F/SCORING_CONFIG.md)。 |
| [E03 开发批次的输入副本](E/E03/dev5-k0-v1/dev5_k0_all_methods.jsonl) | 在 Git 中与开发批次归档的 [inputs.jsonl](../E/E03/results/dev5-k0-v1/inputs.jsonl) 字节一致。E03 使用后一份输入。 |
| [早期测试排班](planning/测试轮计划.md) | 第一、二轮的人员与顺序草案。现行事项与交付要求见[任务表](../任务表.md)和[同步任务表](../同步任务表.md)。 |
