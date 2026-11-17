# E01 实验记录

状态：已产生真实输出，待人工核对

开发题：`1cea1afa`
输入 SHA256：`f6a91f1b44ad58a34aa37a70937f47d6ad49794565dc1edc1ae99cae2958399c`

## 开发输入

完整原文轮次：6；消息：12。
结构、来源清单、哈希、顺序和原文拼接检查通过。未把参考答案或旧输出作为新回答。
当前材料的旧 2048 Token 预算使用 Qwen tokenizer；Llama Token 数在模型阶段实测。

## 已有探测记录

- 作业 48841：NVIDIA A40，46068 MiB，驱动 570.148.08；CUDA available=None。每个作业保留自己的设备身份。
- 作业 48855：NVIDIA L40S，46068 MiB，驱动 570.148.08；CUDA available=True。每个作业保留自己的设备身份。

## 模型与生成

配置与实际 GPU：见 `generation/config.json` 和 `generation/environment.json`。
完整输入输出：见 `generation/prompt.txt` 和 `generation/output.txt`。

```json
{
  "question_id": "1cea1afa",
  "input_tokens": 2056,
  "context_tokens": 1949,
  "output_tokens_including_stop": 11,
  "setup_seconds_including_download_if_needed": 108.63443113304675,
  "warmup_seconds": 3.050567283295095,
  "generation_seconds": 0.8060001032426953,
  "output_tokens_per_second_including_prefill": 13.647640931737921,
  "peak_allocated_gib": 15.444947242736816,
  "peak_reserved_gib": 15.54296875,
  "hit_output_limit": false,
  "nonempty_output": true,
  "status": "generated"
}
```

## 人工核对（执行后填写）

- [ ] 已打开完整输入和输出，确认非空并检查截断。
- [ ] 已核对模型 SHA、tokenizer SHA、精度和实际作业 GPU。
- [ ] 已区分排队、下载/加载、warmup 与生成时间。
- [ ] 已填写实际产物路径并交付全员。

本次为 E01 直接回答试跑；E02 的 D02 材料与官方多次调用 CoN 流程仍待接入。
输入结构检查和生成成功均不等于答案已经完成评分。
