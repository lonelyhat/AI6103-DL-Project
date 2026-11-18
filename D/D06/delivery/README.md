# D06 交付与复核

D06已完成：34道可回答开发题、K0/K1、2048 token；每个索引17个方法/参数配置，1156份材料、回答及评分均齐全。

最终选择：MMR lambda=0.5；C lambda=1；Q lambda=0.5、gamma=1。每种方法以两索引平均开发正确率选择共同权重；并列先取较小lambda，再取较小gamma，沿用原计划预先记录的建议规则，C/Q分别独立选择。R/FL无扫描参数。完整网格无早停；7条截断原样评分并保留分母。

## 提交内容

| 位置 | 内容 |
| --- | --- |
| `D/D06/*.py`、`server/` | 材料生成/重放、恢复导出、E验收、评分汇总、服务器脚本及测试 |
| `D/D06/output/dev34-parameter-selection-v1/` | 最终报告、参数JSON、完整参数成绩表、1156条逐记录成绩 |
| `F/scores/d06_dev34_grid_v1.jsonl` | 完整f03-v1逐条评分、回答指纹及API用量记录 |
| 本目录的`plan.json`等JSON | 原始冻结计划、交接哈希、Unicode读取修复凭据、预检及下载验收 |
| 本目录的`d06-dev34-results.tar.gz` | 已校验服务器原始结果包：输入、回答、全部尝试、环境、作业日志和运行代码 |
| `E/E03/batch.py`、`prepare_inputs.py`、`test_e03.py` | JSONL物理行读取修复及跨平台测试修复 |

原始结果包保留历史生成状态，`scored=false`及验收时的waiting_for_scores是当时状态；最终完成状态以D06/STATUS.json及参数报告为准。完整结果已通过39个归档文件核对、1156条输入/回答/尝试与F导出对应检查。F评分全部ok、无API错误或不明确判分。

`.gitignore`排除原始shards、returned、upload和缓存目录；压缩包及完整评分保留足够证据，不重复提交数千个中间文件。API Key、.env、模型权重和Conda环境不属于交付。

## 拉取后离线复核

以下均在仓库根目录执行，不调用评分API：

```bash
sha256sum -c D/D06/delivery/SHA256SUMS

mkdir -p D/D06/returned/dev34-grid-v1
tar -xzf D/D06/delivery/d06-dev34-results.tar.gz \
  -C D/D06/returned/dev34-grid-v1

mkdir -p D/D06/output/dev34-grid-v1
cp D/D06/delivery/plan.json D/D06/delivery/handoff.json \
   D/D06/delivery/recovery_manifest.json D/D06/delivery/preflight.json \
   D/D06/output/dev34-grid-v1/
cp D/D06/returned/dev34-grid-v1/inputs/reader_inputs.jsonl \
   D/D06/output/dev34-grid-v1/

python -m D.D06.check_reader \
  --handoff-dir D/D06/output/dev34-grid-v1 \
  --run-dirs D/D06/returned/dev34-grid-v1/runs/dev34-grid-v1 \
  --output D/D06/returned/dev34-grid-v1/e_receipt.json

python -m D.D06.summarize \
  --output-dir D/D06/output/dev34-parameter-selection-recheck
```

汇总仅依赖Python标准库、已有数据和F评分模块，不需要API Key、GPU或模型权重。新建报告路径，避免覆盖已有报告。如果已有e_receipt.json，请为新报告换一个文件名。原始文件哈希与本机路径保留在参数JSON中，换机器后旧绝对路径仅用于审计；复核程序以新仓库路径定位数据。

结论限于开发选参，不能作为正式测试性能。34题中6道偏好题沿用f03-v1已声明的未额外校准限制。下一步D07；正式运行仍需G02冻结。
