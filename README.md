# AI6103 Deep Learning Project

This project tests whether fact-augmented retrieval and question-aware context selection improve long-conversation question answering under a fixed reading budget. The formal experiment evaluates 80 LongMemEval-S questions with two retrieval indexes and five selection methods, using a 2,048-token history budget and a fixed Llama 3.1 8B Instruct reader.

## Reviewer guide

| Review area | Entry point |
| --- | --- |
| Formal design, settings, and input versions | [G02 frozen protocol](G/G02/README.md) |
| Input data and evidence mapping | [Formal question split](A-数据线/A03-正式题清单.md) · [Evidence analysis](A-数据线/A04/README.md) |
| Retrieval and fact enrichment | [Retrieval pipeline](B-检索线/README.md) · [Fact quality and indexing cost](C05/C05_事实质量与一次性建库成本_交付.md) |
| Budgeted selection | [Selection implementations](D/README.md) · [Formal inputs](D/D08/delivery/README.md) |
| Reading and generation | [E-line source and checks](E/README.md) · [Formal batch runbook](E/E04/README.md) |
| Scoring and human review | [Scoring protocol](F/SCORING_CONFIG.md) · [Final review](F/F05/g02-v1/README.md) |
| Main results, cost, and cases | [Accuracy and paired intervals](F/F06/README.md) · [Cost analysis](F/F07/README.md) · [Cases](A-数据线/A05/README.md) |
| Reproducibility and limitations | [G03 audit](G/G03/README.md) · [Original E04 outputs](https://github.com/lonelyhat/AI6103-DL-Project/tree/95438df71b0730d58ab260d97f4528e3b3228e72/E/E04/results/g02-v1) |

## Offline checks

Run from the project root with Python 3.10 or later. The E-line tests use bundled fixtures and a simulated scoring client.

~~~bash
python -B E/E02/test_e02.py
python -B E/E03/test_e03.py
~~~

For the full formal audit, use a Git clone with the project history and fetch the E04 archive branch. The audit reads the frozen inputs, raw outputs, and scores. It runs without model weights or a scoring API.

~~~bash
git fetch origin e04-results
python -B G/G03/audit.py
~~~

The highest observed accuracy was 42/80 (52.5%) for fact-augmented retrieval with relevance-ranked selection. The paired 95% confidence interval for its gain over plain retrieval with the same selection method spans zero. See the paired results for the coverage and interaction comparisons.

[Historical materials](archive/README.md) record the early planning and superseded handoffs.
