# 项目开发指南：基于 Rasa 的图书馆智能助手（含 GraphRAG 扩展路线）

本文档在仓库根目录 **[README.md](README.md)** 所索引的**当前可运行实现**之上，整理**目标技术路线**与**环境依赖**，便于后续接入知识图谱与本地大模型。日常联调命令仍以 **[docs/操作指引.md](docs/操作指引.md)** 为准。若修改了 `backend/actions/*.py`，请务必同时重启 Action 与 Rasa 服务。

---

## 1. 项目概述

### 1.1 当前痛点（产品视角）

传统馆员检索与 FAQ 多依赖关键词匹配，多轮澄清成本高，书目与主题之间的**关联查询**（例如「同作者其他在架书」「某主题入门读物」）难以用固定规则穷举。

### 1.2 演进方向（技术视角）


| 阶段      | 说明                                                                                         |
| ------- | ------------------------------------------------------------------------------------------ |
| **已实现** | Rasa 对话管理 + 表单借还/预约演示 + SQLite 馆藏书目演示库 + Vue 前端 Webhook 联调。                                |
| **规划中** | 引入 **Neo4j** 知识图谱与 **GraphRAG**：复杂问法经 NL2Cypher 多跳查询；可选 **Ollama** 等本地推理服务承载中小参数模型，降低外网依赖。 |


> 说明：仓库内**尚未**包含 `graph_rag/`、`neo4j_client.py`、`nl2cypher.py` 等模块时，下文章节中的对应路径表示**建议落地布局**，而非当前文件树。

### 1.3 核心目标（对齐规划）

- **语义理解**：Rasa NLU 提取书名、索书号、主题等槽位/实体（已部分体现在 `backend/domain.yml` 与训练数据中）。
- **知识关联**：图谱中作者—作品—主题—馆藏等关系的多跳推理（待接入 Neo4j 与生成查询链路）。
- **本地化推理**（可选）：通过 Ollama 等调用本地开源模型，辅助 NL2Cypher 或结果解释；模型名称与体量需按机器显存/内存选型，不必固定为某一版本号。

---

## 2. 技术栈（现状 + 规划）


| 层级     | 现状                                                                  | 规划扩展                  |
| ------ | ------------------------------------------------------------------- | --------------------- |
| 对话引擎   | Rasa Open Source（配置与数据在 `backend/`）                                 | 保持 Rasa 为编排核心         |
| 书目演示数据 | SQLite（`backend/data/library.db`，见 `backend/actions/library_db.py`） | 可与 OPAC/ILS 或图谱同步源并存  |
| 图数据库   | 无                                                                   | Neo4j                 |
| 推理后端   | DeepSeek（仅 `data_inquiry` 场景）+ 规则引擎 | Ollama + 自选 GGUF/量化模型 |
| 前端     | `front/lib_agent_vue`（Rasa REST/Webhook）                            | 同左                    |


---

## 3. 目录结构

### 3.1 当前仓库（节选）

```text
library_agent/
├── backend/                 # Rasa 工程根
│   ├── actions/
│   │   ├── actions.py       # 自定义 Action（借还、预约演示、推荐阅读等）
│   │   ├── library_db.py    # SQLite 书目访问
│   │   └── neo4j_graph.py   # Neo4j 主题推荐（与 kg_module 数据一致）
│   ├── kg_module/           # 图谱 Schema、CSV 导入、NL2Cypher 占位
│   ├── data/                # NLU / stories / rules / 词典等
│   ├── config.yml
│   ├── domain.yml
│   ├── endpoints.yml
│   ├── rasa_windows.py      # Windows 下模型解压路径兼容
│   ├── start_rasa.ps1
│   └── start_actions.ps1
├── front/lib_agent_vue/     # Vue 对话页
├── sql/                     # MySQL 注释脚本、SQLite 建表示例
├── docs/                    # 操作指引、改造说明等
├── README.md                # 仓库入口与文档索引
└── README_v2.md             # 本文件：扩展路线与环境说明
```

### 3.2 规划中的增强布局（待创建）

接入 GraphRAG 时，建议在 `backend/actions/` 或单独包中增加类似结构，避免与 Rasa 训练数据混淆：

```text
backend/actions/          # 或与 backend 平级的 services/
├── neo4j_client.py       # Neo4j 驱动封装
├── llm_client.py         # Ollama / OpenAI 兼容 HTTP 客户端
graph_rag/                # 可选顶层包
├── schema_builder.py     # 图谱模式与约束
├── data_importer.py      # 批量导入与去重
├── nl2cypher.py          # 自然语言 → Cypher（可接 LLM）
└── prompt_templates.py   # 提示词模板版本管理
```

容器化：仓库已提供 `deploy/docker-compose.yml`（Rasa API + Action；可选 DeepSeek 见根目录 `.env.example`）。后续若接 Neo4j / Ollama，可在同一 compose 中追加服务。

---

## 4. Python 环境与依赖

### 4.1 解释器版本

- 推荐 **Python 3.10.x**（与 Rasa 3.6.x 官方兼容矩阵一致；勿使用 3.13 等尚未支持的版本）。
- 使用 **conda** 或 **venv** 隔离环境；Windows 下完整步骤见 [docs/操作指引.md](docs/操作指引.md)。

### 4.2 依赖分类


| 类别       | 包名（示例）                     | 用途                          |
| -------- | -------------------------- | --------------------------- |
| 对话       | `rasa`、`rasa-sdk`          | NLU/Core、自定义 Action         |
| 图数据库（规划） | `neo4j`                    | 官方驱动执行 Cypher               |
| HTTP（规划） | `requests`、`aiohttp`       | 调用 Ollama 等本地 HTTP API      |
| 中文 NLU   | `jieba`                    | 已在 `backend/config.yml` 中引用 |
| 可选       | `python-dotenv`、`pydantic` | 配置与校验                       |


`py2neo`、`langchain-community` 等仅在选型确定后再加入，避免与 Rasa 子依赖冲突。

### 4.3 版本锁定示例（请以本机可训练版本为准）

```text
rasa==3.6.21
rasa-sdk==3.6.2
neo4j>=5.12.0          # 启用图谱后
requests>=2.28.0
aiohttp>=3.8.0
jieba>=0.42.1
python-dotenv>=1.0.0
```

安装后**不要随意升级** Rasa 锁定的传递依赖（如部分 ASGI/Starlette 相关版本），以免训练或推理异常。

---

## 5. 环境搭建（简版）

```powershell
# 示例：venv
python -m venv .venv
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate       # Linux / macOS

pip install --upgrade pip setuptools wheel
pip install rasa rasa-sdk jieba
# 启用 Neo4j 客户端时再： pip install neo4j
```

训练、双终端启动 Action + Rasa API、前端联调，一律以 [docs/操作指引.md](docs/操作指引.md) 为准。

---

## 6. 兼容性与算力

- **Rasa 3.x**：依赖树较深，升级单个包前建议在虚拟环境中回归 `rasa train` 与一次完整对话。
- **本地大模型**：若使用 GPU，需安装与显卡匹配的 CUDA/ROCm 驱动；CPU 量化模型亦可跑通 NL2Cypher 原型，延迟需预期管理。
- **SQLite**：单机演示足够；生产多实例 Action Server 时，书目层应迁移到集中式数据库或只读副本，并配合连接池与超时。

---

## 7. 文档索引


| 文档                                                         | 内容                      |
| ---------------------------------------------------------- | ----------------------- |
| [README.md](README.md)                                     | 功能索引、文档入口、远程仓库        |
| [docs/操作指引.md](docs/操作指引.md)                               | Windows + Conda + 三终端联调 |
| [docs/图书馆智能助手改造说明.md](docs/图书馆智能助手改造说明.md)                 | 领域与改造说明                 |
| [sql/library_book_sqlite.sql](sql/library_book_sqlite.sql) | SQLite 建表与示例数据（可选手工初始化） |


