# E02 → F 历史兼容补丁

基于 `origin/F_Evaluation` commit `36dd0a8f39ae89d416c81dda6a95f06a1945a8c7`。补丁仅修改 `F/src/evaluation/judge.py`、`join_f02.py`，本地隔离副本已完成11项离线测试。E 分支没有直接复制/合入 F 源码。

修复内容：

1. 正确从 `F/src/evaluation` 定位项目根目录，移除旧 `AI6103-DL-Project-main_V1` 路径。
2. E02 v2 使用 E 提取的明确答案；缺少标记时使用全文并保留需复核标记，避免两套提取规则不一致。
3. Judge 续跑键增加 variant、topk、阅读器版本、历史哈希，评分输出保留这些字段。
4. F02 关联键增加配置版本、variant/topk，防止混合两版结果。旧 D02 缺省 variant 按 budget 处理。
5. B/D 版本核对使用 D 记录的 input_config_version 对照 B 版本；不再把 B 的 a01-v2 与 D 的 d02-v1 当成同一个阶段版本。

当前项目主线已含兼容的 F 代码。本补丁供复查旧版交接。需要检查补丁时，将当前项目中的补丁绝对路径传给指定历史 F 提交的工作树。

```bash
git -C /path/to/legacy-F-checkout apply --check "/path/to/current-project/archive/E/E02/handoff/f_evaluation.patch"
```

补丁的适用范围是当时的导出兼容逻辑。当前正式评分规则见 [F 评分配置](../../../../F/SCORING_CONFIG.md)。

E 的 `answers_for_f.jsonl` 已把正常生成转换为 `status=ok`；F 不需要把所有 E 状态都当作成功。`truncated/empty/technical_failure` 不进入正常答案评分，保留失败记录，不应从最终完成率统计中悄悄删除。

真实评分前先无API检查（替换 JOBID）：

```bash
python F/src/evaluation/judge.py --answers runs/e02/job-JOBID/answers_for_f.jsonl --dry-run
```

该命令会读取开发集参考答案组装评分 prompt，不应把它的输出加入 E 输入。正式调用 API 和评分校准由 F 执行。

F02：预算版使用 `E/E02/inputs/sources/d02_selections.jsonl`；参照版使用 `E/E02/inputs/topk_selections.jsonl`；候选都使用 `E/E02/inputs/sources/b02_candidates.jsonl`。参照版的精确 token 数要在真实运行后从结果关联补充，当前没有伪造 token 计数。

人工核对仍需检查 E02 输出是否完整、答案提取是否合理。离线模拟接口通过不等于真实 Judge 服务可用或评分已经校准。
