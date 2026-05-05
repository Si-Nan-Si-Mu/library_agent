# CrossWOZ 导出候选（待人工改写）

由 `scripts/crosswoz_nlu_candidates.py` 从 `user_utterances_train.jsonl` 抽样生成。**不要**未改写整段合并进 `nlu.yml`。

## 分桶与建议对应关系（仅供参考）

| 文件前缀 | 建议映射到 Rasa intent | 说明 |
|----------|------------------------|------|
| 01_greet | `greet` | **仅** `General/greet`、且无 `Inform`/`Request`/`Select`（纯寒暄）；复合句已进 05 |
| 02_goodbye | `goodbye` | 含 `General/bye` 或结束会话类感谢 |
| 03_thanks_only | `goodbye` 或删除 | 纯感谢；可改写成「谢谢，先结束」或丢弃 |
| 04_reading_recommend | `reading_recommend` | 含「推荐」等；改写成图书推荐说法 |
| 05_request_inform_query | `borrow_book` / `return_book` / `borrow_record_query` | Inform+Request 查询风格；改成借书/还书/查记录 |
| 06_ask_capabilities | `ask_capabilities` | 「你能…吗」类 |
| 07_short_affirm | `affirm` | 极短肯定（易与其它混淆，请精挑） |
| 08_short_deny | `deny` | 否定/取消开头 |
| 09_metro_taxi | `space_booking` 或 `borrow_guide` | 地铁/出租域；可改成预约/问路说法或丢弃 |
| 10_book_overview_hint | `book_overview` | 含「有哪些/总共」等；可改成馆藏总览说法 |

改写后请删除实体地名/店名，换成书名或「这本书」等图书馆语境，再写入 `backend/data/nlu.yml`。
