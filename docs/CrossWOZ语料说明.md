# CrossWOZ 抽样语料与 NLU 候选

本页替代原 `backend/data/crosswoz/README.md` 与 `candidates/README.md`，集中说明语料用途与脚本命令。

---

## 1. 用户话轮样本（`backend/data/crosswoz/`）

从 [CrossWOZ](https://github.com/thu-coai/CrossWOZ) 训练集抽取的**用户侧话轮**，用于中文任务型对话的语料参考与 Rasa `nlu.yml` 扩写（需自行映射 intent，**不可**直接当作图书馆领域 ground truth）。

- **论文**：[CrossWOZ: A Large-Scale Chinese Cross-Domain Task-Oriented Dialogue Dataset](https://arxiv.org/abs/2002.11893)
- **许可证**：Apache License 2.0（见上游仓库）

| 文件 | 说明 |
|------|------|
| `user_utterances_train.jsonl` | 自 `train.json` 按对话顺序抽取的用户话轮。每行 JSON：`text` 与 `dialog_act`。 |
| `candidates/` | 由 `scripts/crosswoz_nlu_candidates.py` 分桶导出的**待人工改写**纯文本。 |

领域为酒店、餐馆、景点、地铁、出租车等，**与图书馆业务不对齐**；仅作「任务型中文」风格补充。

### 重新生成或扩大样本量

1. 下载上游 `data/crosswoz/train.json.zip` 并解压得到 `train.json`。
2. 在仓库根目录执行：

```bash
python scripts/build_crosswoz_user_utterances_sample.py --input path/to/train.json --output backend/data/crosswoz/user_utterances_train.jsonl --max-lines 50000
```

### 生成 NLU 改写候选

```bash
python scripts/crosswoz_nlu_candidates.py --input backend/data/crosswoz/user_utterances_train.jsonl --output-dir backend/data/crosswoz/candidates --per-bucket 120
```

在 `candidates/*.txt` 中挑选、改写成图书馆说法后，再合并进 `backend/data/nlu.yml`。

---

## 2. 候选分桶与 intent 映射（仅供参考）

| 文件前缀 | 建议映射到 Rasa intent | 说明 |
|----------|------------------------|------|
| `01_greet` | `greet` | 仅纯寒暄；复合句多在 `05` |
| `02_goodbye` | `goodbye` | 结束会话、感谢类 |
| `03_thanks_only` | `goodbye` 或删除 | 纯感谢；可改写成「谢谢，先结束」或丢弃 |
| `04_reading_recommend` | `reading_recommend` | 含「推荐」等；改写成荐书说法 |
| `05_request_inform_query` | `borrow_book` / `return_book` / `borrow_record_query` | 查询风格；改成借还/查记录 |
| `06_ask_capabilities` | `ask_capabilities` | 「你能…吗」类 |
| `07_short_affirm` | `affirm` | 极短肯定，精挑 |
| `08_short_deny` | `deny` | 否定/取消开头 |
| `09_metro_taxi` | `space_booking` 或 `borrow_guide` | 地铁/出租域；可改预约语境或丢弃 |
| `10_book_overview_hint` | `book_overview` | 「有哪些/总共」等；改成馆藏总览 |

**不要**未改写整段合并进 `nlu.yml`。改写后删除实体地名/店名，换成书名或馆场景。

---

## 3. 引用

若发表论文或公开报告使用 CrossWOZ，请按上游 README 引用其 TACL 论文。
