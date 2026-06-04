import os
from neo4j import GraphDatabase
import time

URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "password123")


def import_graph_to_neo4j(txt_filepath):
    print("🚀 开始连接 Neo4j 数据库...")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
        print("✅ 历史数据已清空。")

        print(f"📂 正在读取 {txt_filepath}...")
        try:
            with open(txt_filepath, 'r') as f:
                edges = f.readlines()
        except FileNotFoundError:
            print(f"❌ 找不到文件：{txt_filepath}，请检查路径！")
            return

        print(f"⏳ 准备将 {len(edges)} 条连线写入图数据库，请稍候...")
        start_time = time.time()

        query = """
        UNWIND $batch AS edge
        MERGE (u:User {id: edge.source})
        MERGE (v:User {id: edge.target})
        MERGE (u)-[:KNOWS]->(v)
        """

        batch = []
        count = 0
        for line in edges:
            parts = line.strip().split()
            if len(parts) == 2:
                batch.append({"source": parts[0], "target": parts[1]})
                count += 1
                if count % 2000 == 0:
                    session.run(query, batch=batch)
                    batch = []
                    print(f"   ...已导入 {count} 条关系...")

        if batch:
            session.run(query, batch=batch)

        driver.close()
        print(f"🎉 导入全部完成！耗时: {time.time() - start_time:.2f} 秒")


if __name__ == "__main__":
    data_path = os.environ.get(
        "GRAPH_DATA_PATH",
        os.path.join(os.path.dirname(__file__), "..", "backend_cpp", "facebook_combined.txt")
    )
    import_graph_to_neo4j(os.path.normpath(data_path))
