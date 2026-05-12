# 文档索引

本目录集中存放**用户与维护者**需要的说明；仓库根目录 [README.md](../README.md) 为项目总览与更新记录。

| 文档 | 读者 | 内容概要 |
|------|------|----------|
| [操作指引.md](操作指引.md) | 日常联调 | Windows + Conda、Rasa / Action / Vue、Webhook、Neo4j、常见问题 |
| [图书馆智能助手改造说明.md](图书馆智能助手改造说明.md) | 产品与开发 | 能力落地状态、改造清单、维护约定；含书籍总览气泡与单书介绍等 |
| [kg_ontology_v2.md](kg_ontology_v2.md) | 数据 / 图谱 | Neo4j 节点与关系规划、与 `kg_module` 导入实现的对照 |
| [扩展路线与环境.md](扩展路线与环境.md) | 架构与规划 | GraphRAG、本地 LLM（Ollama）路线、技术栈与依赖说明 |
| [CrossWOZ语料说明.md](CrossWOZ语料说明.md) | NLU 扩写 | CrossWOZ 抽样语料用途、生成脚本、候选分桶与改写注意 |

**子项目入口**

- 后端 Rasa 工程：`backend/`（极简说明见 [backend/README.md](../backend/README.md)）
- 前端 Vue + Vite：`front/lib_agent_vue/`（开发与构建见该目录 [README.md](../front/lib_agent_vue/README.md)）
