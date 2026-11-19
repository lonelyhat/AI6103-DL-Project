# D08 正式首批交接

[D08_g02-v1_batch-01.zip](D08_g02-v1_batch-01.zip) 是按 [G02 冻结配置](../../../G/G02/plan.json)生成的首批正式阅读材料。题单版本为 `a03-v2`。10 题各有 K0/K1 × R/MMR/C/Q/FL，共 100 个设置，历史正文最长龙度为 2047 Token。

| 解包文件 | 用途 |
| --- | --- |
| `selections.jsonl` | 选材轨迹、原文轮次、正文 Token 和选择耗时，供 D08/A04 使用。 |
| `reader_inputs.jsonl` | E04 直接读取的输入文件。传输时保留原始字节。 |
| `receipt.json` | 批次、计划指纹、输入指纹、预算与 CPU 预检结果。 |

压缩包和输入文件的 SHA-256 见 [G02 核验回执](../../../G/G02/validation.json) 的 `d08_first_batch`。从仓库根目录解包：

```bash
python -m zipfile -e D/D08/delivery/D08_g02-v1_batch-01.zip runs/g02/d08-g02-v1-batch-01
```

首批材料已经生成并核验。D 线可直接从 `batch-02` 继续分批生成，沿用冻结计划和同一 E03 分词器：

```bash
python -m G.G02.prepare --tokenizer /path/to/reader-snapshot \
  --batch-id batch-02 --output-dir runs/g02/d08-g02-v1-batch-02
```
