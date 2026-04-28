# 知识图谱关系扩展定义 (v2.0)

## 1. 节点标签 (Labels)
- Book: 包含书籍基本信息 (ISBN, Title, Year)
- Author: 作者信息 (Name, Nationality, Era)
- Tag: 标签节点，包含 Style (风格) 和 Theme (题材)

## 2. 基础与进阶关系列表

| 关系 (Relationship)      | 方向 (Direction)          | 业务逻辑说明                                |
|-------------------------|--------------------------|-------------------------------------------|
| WROTE                   | (Author) -> (Book)       | 基础创作关系                               |
| SAME_STYLE_AS           | (Book) <-> (Book)        | 写作风格相似（如：同样是简洁洗练的文字）       |
| SHARES_THEME            | (Book) <-> (Book)        | 核心母题相同（如：人工智能的自我意识）         |
| CONTEMPORARY            | (Author) <-> (Author)    | 齐名/同时代关系                            |
| RIVAL                   | (Author) <-> (Author)    | 竞争或学术观点对立                          |
| INFLUENCED              | (Author) -> (Author)     | 文学或学术上的启发与影响                    |
| MEMBER_OF               | (Author) -> (Affiliation) | 所属流派、学院或文学团体 [cite: 1, 5]        |

## 3. Cypher 查询示例 (用于 GraphRAG)
// 场景：寻找受‘卡夫卡’影响的作者写的‘荒诞主义’风格作品
MATCH (a:Author {name: '卡夫卡'})-[:INFLUENCED]->(student:Author)
MATCH (student)-[:WROTE]->(b:Book)-[:HAS_STYLE]->(s:Style {name: '荒诞主义'})
RETURN b.title, student.name;