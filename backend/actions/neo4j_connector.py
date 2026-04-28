from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "kewei2006"

def get_books_by_topic(topic_name):
    print(f"-> 正在 Neo4j 中检索主题: {topic_name}")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    
    # Cypher 查询：查找包含该主题的书籍，按评分降序，最多取 3 本
# 同时匹配 Topic 和 Category，只要任意一个包含关键词即可
    cypher_query = """
    MATCH (b:Book)-[:COVERS_TOPIC|BELONGS_TO]->(node)
    WHERE node.name CONTAINS $topic
    RETURN DISTINCT b.title AS title, b.summary AS summary, b.rating AS rating
    ORDER BY b.rating DESC
    LIMIT 3
    """
    
    results = []
    with driver.session() as session:
        records = session.run(cypher_query, topic=topic_name)
        for record in records:
            results.append({
                "书名": record["title"],
                "评分": record["rating"],
                "简介": record["summary"]
            })
            
    driver.close()
    return results