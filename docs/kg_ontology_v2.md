# 知识图谱关系扩展定义 (v2.1)

（供 GraphRAG / NL2Cypher 与 `backend/kg_module` 导入脚本对齐；馆藏与书目知识共用 `:LibraryBook`，`book_key` 唯一。）

## 1. 节点标签 (Labels)

| 标签 | 属性（主要） | 说明 |
|------|-------------|------|
| `LibraryBook` | `book_key`, `lib_book`, `title`, `rating`, `summary`, `book_pos`, `is_borrow` | 馆藏 + 书目元数据合一 |
| `Author` | `name`, `bio` | 作者 |
| `Discipline` | `name`, `description`（可选） | **学科**，与 CSV 列 `category` 同值（如「日本文学」） |
| `Category` | `name` | 与 `Discipline` 同名并存，兼容旧查询 |
| `Topic` | `name` | 细粒度主题词 |
| `BorrowRecord` | `borrower_id`, `book_key`, `borrow_at`, … | 借阅流水 |

## 2. 双知识网络

### 2.1 作者关系网络

- 数据来源：`backend/kg_module/raw_data/author_relations.csv`
- 关系类型：
  - `(Author)-[:INFLUENCED]->(Author)` — 有影响方向
  - `(Author)-[:CONTEMPORARY_WITH]-(Author)` — 同时代 / 同领域（无向）
  - `(Author)-[:RIVAL_OF]-(Author)` — 观点对立（无向，可选）
- 派生：同一 `Discipline` 下著作≥2 的作者，补充有限条 `CONTEMPORARY_WITH`（每学科最多 28 对，见 `graph_networks.py`）
- 派生：`(Author)-[:WORKS_IN]->(Discipline)` — 由馆藏 `(LibraryBook)-[:WRITTEN_BY]->(Author)` 与 `(LibraryBook)-[:IN_DISCIPLINE]->(Discipline)` 推导

### 2.2 学科关系网络

- `(LibraryBook)-[:IN_DISCIPLINE]->(Discipline)` — CSV 导入时与 `category` 同步建立
- `(LibraryBook)-[:BELONGS_TO]->(Category)` — 保留兼容
- `(LibraryBook)-[:WRITTEN_BY]->(Author)` — 联结作者
- `(LibraryBook)-[:COVERS_TOPIC]->(Topic)` — 联结主题
- `(Topic)-[:UNDER_DISCIPLINE]->(Discipline)` — 由同一本书同时覆盖的主题与学科推导

## 3. 关系总表

| 关系 | 方向 | 来源 |
|------|------|------|
| `WRITTEN_BY` | Book → Author | `books.csv` |
| `IN_DISCIPLINE` | Book → Discipline | `books.csv`（`category`） |
| `BELONGS_TO` | Book → Category | `books.csv` |
| `COVERS_TOPIC` | Book → Topic | `books.csv` |
| `WORKS_IN` | Author → Discipline | 派生 |
| `UNDER_DISCIPLINE` | Topic → Discipline | 派生 |
| `INFLUENCED` / `CONTEMPORARY_WITH` / `RIVAL_OF` | Author ↔ Author | CSV + 派生 |

## 4. 构建与清空

```bash
cd backend
python kg_module/schema_cypher.py          # 约束（含 Discipline.name）
python kg_module/import_data.py --reset    # 全量：CSV + build_knowledge_networks + 馆藏种子
# 仅重导书目元数据、保留馆藏与借阅：
python kg_module/import_data.py --reset --graph-only
```

单独重建知识网络（需已有 Author / LibraryBook / Discipline）：

```bash
cd backend
python kg_module/graph_networks.py
```

## 5. Cypher 示例

```cypher
// 学科「日本文学」下的在架书目与作者
MATCH (d:Discipline)
WHERE toLower(d.name) CONTAINS '日本文学'
MATCH (b:LibraryBook)-[:IN_DISCIPLINE]->(d)
OPTIONAL MATCH (b)-[:WRITTEN_BY]->(a:Author)
WHERE coalesce(b.is_borrow, 0) = 0
RETURN coalesce(b.lib_book, b.title) AS title, collect(DISTINCT a.name) AS authors
LIMIT 20;
```

```cypher
// 某作者的关系网络
MATCH (a:Author {name: '村上春树'})-[r]-(peer:Author)
RETURN type(r) AS rel, peer.name AS peer, coalesce(r.note, '') AS note
LIMIT 15;
```
