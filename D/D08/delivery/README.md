# D08 正式材料交接

交付按 [G02 冻结配置](../../../G/G02/plan.json)生成，题单版本为 `a03-v2`。8 批各 10 题、100 个设置，总共 80 题和 800 条正式阅读输入。每道题都有 K0/K1 × R/MMR/C/Q/FL。逐批题号和压缩包、输入、选材记录的 SHA-256 见 [交付清单](manifest.json)。

| 解包文件 | 用途 |
| --- | --- |
| `selections.jsonl` | 选材轨迹、原文轮次、正文 Token 和选择耗时，供 D08/A04 使用。 |
| `reader_inputs.jsonl` | E04 直接读取的输入文件。传输时保留原始字节。 |
| `receipt.json` | 批次、计划指纹、输入指纹、预算与 CPU 预检结果。 |

从仓库根目录解包，例如首批：

```bash
python -m zipfile -e D/D08/delivery/D08_g02-v1_batch-01.zip runs/g02/d08-g02-v1-batch-01
```

E04 对每批使用解包后的 `reader_inputs.jsonl`，每批使用单独的运行目录。A04 读取同批次的 `selections.jsonl`。逐批换用 `batch-01` 至 `batch-08` 的文件，不需要重新选材。可以在 CPU 上复核八批压缩包、输入身份、候选来源和原文：

```bash
python -m D.D08.verify_delivery
```

如需用冻结的 Llama 分词器逐条复算历史正文和完整 CoN prompt，请加 `--tokenizer /path/to/reader-snapshot`。本次交付已对全部 800 条做过这项复核。证据保留情况单列为选材诊断，实际答题正确率以 E04/F04 为准。

模型回答与评分分别由 E04 和 F04 生成和归档。
