from neo4j import GraphDatabase

# Neo4j 数据库连接信息 (需与你 Docker 启动时的配置一致)
URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "kewei2006"

# 定义创建约束的 Cypher 语句集合
# 注意：Neo4j 5.x 版本的语法是 CREATE CONSTRAINT ... FOR (n:Label) REQUIRE n.property IS UNIQUE
SCHEMA_QUERIES = [
    "CREATE CONSTRAINT book_title IF NOT EXISTS FOR (b:Book) REQUIRE b.title IS UNIQUE;",
    "CREATE CONSTRAINT author_name IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE;",
    "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE;",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE;"
]

def init_schema():
    print("正在连接 Neo4j 数据库")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    
    with driver.session() as session:
        for query in SCHEMA_QUERIES:
            try:
                session.run(query)
                print(f"执行成功: {query.split('IF NOT EXISTS FOR')[0].strip()}")
            except Exception as e:
                print(f"执行失败: {e}")
                
    driver.close()
    print("图谱约束初始化完成！")

if __name__ == "__main__":
    init_schema()