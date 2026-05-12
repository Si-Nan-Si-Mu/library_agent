# 知识图谱关系扩展定义 (v2.0)

（由 `library-RAG-Rasa` 并入，供 GraphRAG 规划参考；当前导入脚本实现的是 **LibraryBook** / Author / Category / Topic 基础模型，馆藏与书目图谱共用 `:LibraryBook`。）

## 1. 节点标签 (Labels)

- LibraryBook: 以 **book_key** 为唯一标识（与 CSV 列 `book_key` 一致）；属性含 `lib_book`/`title`（题名）、`rating`、`summary`、`book_pos`、`is_borrow` 等。与 Author / Category / Topic 的关系见下表。
- Author: 作者信息 (Name, Nationality, Era)
- Tag: 标签节点，包含 Style (风格) 和 Theme (题材)

## 2. 基础与进阶关系列表

**当前 CSV 导入已实现**：`(LibraryBook)-[:WRITTEN_BY]->(Author)`、`(LibraryBook)-[:BELONGS_TO]->(Category)`、`(LibraryBook)-[:COVERS_TOPIC]->(Topic)`；`LibraryBook` 以 `book_key` 唯一（与 Neo4j 约束一致）。

| 关系 (Relationship)      | 方向 (Direction)          | 业务逻辑说明                                |
|-------------------------|--------------------------|-------------------------------------------|
| WROTE                   | (Author) <- (LibraryBook) | 基础创作关系（导入边为 WRITTEN_BY，自书指向作者） |
| SAME_STYLE_AS           | (LibraryBook) <-> (LibraryBook) | 写作风格相似（规划中） |
| SHARES_THEME            | (LibraryBook) <-> (LibraryBook) | 核心母题相同（规划中） |
| CONTEMPORARY            | (Author) <-> (Author)    | 齐名/同时代关系                            |
| RIVAL                   | (Author) <-> (Author)    | 竞争或学术观点对立                          |
| INFLUENCED              | (Author) -> (Author)     | 文学或学术上的启发与影响                    |
| MEMBER_OF               | (Author) -> (Affiliation) | 所属流派、学院或文学团体 [cite: 1, 5]        |

## 3. Cypher 查询示例 (用于 GraphRAG)

```cypher
// 场景：寻找受‘卡夫卡’影响的作者写的‘荒诞主义’风格作品
MATCH (a:Author {name: '卡夫卡'})-[:INFLUENCED]->(student:Author)
MATCH (student:Author)<-[:WRITTEN_BY]-(b:LibraryBook)-[:HAS_STYLE]->(s:Style {name: '荒诞主义'})
RETURN coalesce(b.lib_book, b.title, '') AS title, student.name;
```
