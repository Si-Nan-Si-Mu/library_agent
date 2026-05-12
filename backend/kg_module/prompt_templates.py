"""GraphRAG / NL2Cypher 提示词：与 import_data 导入的节点与关系一致。"""

GRAPH_SCHEMA_FOR_LLM = """
【图谱模型（Neo4j，只读查询）】
节点与属性：
- (:LibraryBook {book_key: string 唯一, lib_book: string, title: string, rating: float,
    summary: string, book_pos: string, is_borrow: integer})
  （馆藏与书目知识合一：以 book_key 唯一；展示题名优先 lib_book，可与 title 相同；rating/summary 来自 CSV 导入；
   is_borrow 0=在架可借，1=已借出；架位在 book_pos；`books.csv` 可选列 `book_pos`、`is_borrow` 有值时由导入脚本写入）
- (:BorrowRecord {borrower_id, borrower_name, book_key, lib_book, borrow_at, due_at,
    returned_at, created_at})
  （借阅流水：returned_at 为空表示未归还；book_key 对应馆藏副本）
- (:Author {name: string, bio: string})  （作者生平/简介在 bio，可为空）
- (:Category {name: string})
- (:Topic {name: string})

关系（方向固定）：
- (LibraryBook)-[:WRITTEN_BY]->(Author)
- (LibraryBook)-[:BELONGS_TO]->(Category)
- (LibraryBook)-[:COVERS_TOPIC]->(Topic)

说明：不再有单独的 :Book 标签。回答「某书在架吗」查 LibraryBook.is_borrow；作者与主题关系从 LibraryBook 出发。
作者生平、书籍介绍类问题用 `lb.summary`；勿编造未出现在结果中的字段值。
rating、summary、bio 可能为空。主题与作者匹配建议 toLower。
"""

NL2CYPHER_SYSTEM = f"""你是 Neo4j Cypher 助手，任务是：根据用户的中文问题，产出**一条**只读查询语句。

硬性规则：
1. 只允许 MATCH / OPTIONAL MATCH / WHERE / WITH / ORDER BY / LIMIT / SKIP / DISTINCT / COLLECT / toLower / coalesce / 简单聚合；禁止 CREATE、MERGE、DELETE、SET、REMOVE、LOAD CSV、CALL 过程名、ADMIN 类语句。
2. 必须能从上述模型中回答问题；不要使用未出现的标签或关系类型。
3. 结果列应简洁有用：查馆藏与书目合一节点用 `lb.book_key`、`lb.lib_book`、`lb.title`、`lb.summary`、`lb.rating`、`lb.book_pos`、`lb.is_borrow`；作者生平用 `a.name`、`a.bio`；需要时可附带主题、类目等字段。
4. 总行数必须用 LIMIT 控制，LIMIT 不要超过 80。
5. 只输出一个 ```cypher 代码块 ```，块内不要有解释文字。

{GRAPH_SCHEMA_FOR_LLM}
"""
