# CrossWOZ 抽样语料（用户话轮）

本目录存放从 [CrossWOZ](https://github.com/thu-coai/CrossWOZ) 训练集抽取的**用户侧话轮**，用于中文任务型对话的语料参考与 Rasa `nlu.yml` 扩写（需自行映射到你项目的 intent，不可直接当作图书馆领域 ground truth）。

- **原始项目**：`git@github.com:thu-coai/CrossWOZ.git`
- **论文**：[CrossWOZ: A Large-Scale Chinese Cross-Domain Task-Oriented Dialogue Dataset](https://arxiv.org/abs/2002.11893)
- **许可证**：Apache License 2.0（见上游仓库 `LICENSE`）

## 文件说明

| 文件 | 说明 |
|------|------|
| `user_utterances_train.jsonl` | 自 `train.json` 按对话顺序抽取的用户话轮（条数取决于生成时的 `--max-lines`；全量用户轮约 **4.2 万**）。每行 JSON：`text` 与 `dialog_act`（`[类型, 领域, 槽, 值]`，与上游一致）。 |
| `candidates/` | 由 `scripts/crosswoz_nlu_candidates.py` 分桶导出的 **待人工改写** 纯文本；见该目录下 `README.md`。 |

领域为酒店、餐馆、景点、地铁、出租车等，**与图书馆业务不对齐**；适合作为「怎么说得像任务型中文」的补充素材。

## 重新生成或扩大样本量

1. 下载上游 `data/crosswoz/train.json.zip` 并解压得到 `train.json`。
2. 在项目根目录执行：

```bash
python scripts/build_crosswoz_user_utterances_sample.py --input path/to/train.json --output backend/data/crosswoz/user_utterances_train.jsonl --max-lines 50000
```

调大 `--max-lines` 可生成更多行（注意仓库体积与 Git 限制）。

## 生成 NLU 改写候选（推荐工作流）

```bash
python scripts/crosswoz_nlu_candidates.py --input backend/data/crosswoz/user_utterances_train.jsonl --output-dir backend/data/crosswoz/candidates --per-bucket 120
```

在 `candidates/*.txt` 中挑选、改写成图书馆说法后，再合并进 `backend/data/nlu.yml`。

## 引用

若发表论文或公开报告使用 CrossWOZ，请按上游 README 引用其 TACL 论文。
