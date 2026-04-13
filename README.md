# library_agent

基于 [Rasa](https://rasa.com/) 的中文**图书馆智能对话助手**（演示）：借还书、借阅指引、空间预约、推荐阅读、数据咨询话术、馆规 FAQ 等；书目借还与推荐阅读使用 **SQLite** 演示库（见 `backend/actions/library_db.py`）。

| 文档 | 说明 |
| ---- | ---- |
| [**docs/操作指引.md**](docs/操作指引.md) | Windows + Conda、双终端启动 Rasa / Action、Vue 与 Webhook、常见问题 |
| [**docs/图书馆智能助手改造说明.md**](docs/图书馆智能助手改造说明.md) | 领域改造、**已完成/未完成**标注、外部系统对接与产品化清单 |

扩展路线（Neo4j / GraphRAG 等）见 [**README_v2.md**](README_v2.md)。

**远程仓库**：`git@github.com:Si-Nan-Si-Mu/library_agent.git`

---

## 更新记录

**维护约定**：凡影响功能、配置或文档结构的合并，在本表**顶部**追加一行（`YYYY-MM-DD` + 一句话摘要）；细则见 [docs/图书馆智能助手改造说明.md](docs/图书馆智能助手改造说明.md) 文末 **「维护约定」**。纯错别字或无关格式微调可不记。

| 日期 | 摘要 |
| ---- | ---- |
| 2026-04-13 | 语义纠偏：新增借还/预约/FAQ 对抗样本与口语短句；优化“咨询 vs 办理”“总览 vs 推荐”等易混淆边界，连续多轮扩充 `nlu.yml` 并通过数据校验。 |
| 2026-04-13 | 借还鲁棒性增强：`actions.py` 对输入书名做归一化提取（支持 `《书名》`、整行书目信息粘贴、去除架位/索书号噪声），并下调 `FallbackClassifier.threshold` 至 `0.35` 以减少误兜底。 |
| 2026-04-13 | 继续优化语义识别：补充 `space_booking` 的 `time_slot` 实体样本，缓解训练告警；新增序号选书（如「第2本」「1」）的回归测试故事。 |
| 2026-04-13 | 借还书多条候选选择支持「索书号或序号」（如 `1`/`第2本`）；扩充借还确认口语语料与索书号正则，降低 `nlu_fallback` 误触发。需 `rasa train` 并重启 API + Action。 |
| 2026-04-13 | 借还表单：移除 `ignored_intents` 中的 `nlu_fallback`，并为 `book_title`/`call_number` 增加 `from_text` 条件映射，避免纯数字索书号退出表单。需 `rasa train` 并重启 API。 |
| 2026-04-13 | SQLite 书目库自动补全至 ≥120 条；`borrow_book`/`return_book` 区分未找到/已借出/在架；借还确认前 `lookup_circulation` 查询；结果写入 `last_borrow_detail`/`last_return_detail`。需重启 Action；已有 `library.db` 会在连接时自动补行。 |
| 2026-04-11 | chore: 合并提交对话与文档（`action_deactivate_loop` 规则与故事、表单 NLU/lookup、预约槽位校验、`nlu_fallback` 条件、InvalidRule 修复、操作指引与改造说明）。 |
| 2026-04-11 | 修复 `action_deactivate_loop` 404：从 `domain.yml` 的 `actions` 列表移除（内置动作勿写入该列表，否则会被误发到 Action Server）。`rasa train` 后重启 API 即可。 |
| 2026-04-11 | 预约填槽：仅当无活跃表单时触发 `nlu_fallback` 兜底；`room_type` lookup + NLU 例句；`validate_space_booking_form` 从原文归一化「研讨室」等。需 `rasa train` 并重启 Action。 |
| 2026-04-11 | 修复 `InvalidRule`：`rules.yml` 中三条「激活*表单」去掉首步 `action_deactivate_loop`，与 `stories.yml` 对齐；`greet`/`goodbye` 故事补上 `action_deactivate_loop` 与问候规则一致；`tests/test_stories.yml` 同步。 |
| 2026-04-11 | 修复双气泡与「预约」进兜底：`rules.yml` 在问候/FAQ/兜底及三表单激活前增加 `action_deactivate_loop`；`nlu.yml` 为 `space_booking` 补充单字「预约」等例句。需 `rasa train` 并重启 API。 |
| 2026-04-11 | 《改造说明》§2 对话与数据层：增加文件总览表与各文件优化清单；扩充 `nlu.yml` 例句、`dict.txt`、`test_stories.yml`。合并后请 `rasa train`。 |
| 2026-04-11 | 修复「每条回复后重复追问预约空间」：`domain.yml` 为各表单增加 `ignored_intents`，并调整 `session_config`（避免会话与表单状态无限期占用同一 sender）。需 `rasa train` 后重启 API。 |
| 2026-04-11 | 仓库结构重组：`backend` 承载 Rasa、Vue 前端与 `sql/` 脚本；忽略 `.rasa/`、`models/*.tar.gz`、`data/library.db`；`git push --force-with-lease` 同步至 `origin/main`。 |
| 2026-04-11 | 《改造说明》增加完成状态总览、分节 ✅/⏳/⬜ 与维护约定；根 README 增加本节「更新记录」并链向改造说明中的约定。 |
