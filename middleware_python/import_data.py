from neo4j import GraphDatabase
import time

# 连接咱们刚才用 Docker 拉起的 Neo4j 数据库
URI = "bolt://127.0.0.1:7687"
AUTH = ("neo4j", "password123")

def import_graph_to_neo4j(txt_filepath):
    print("🚀 开始连接 Neo4j 数据库...")
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    with driver.session() as session:
        # 1. 先清空历史数据，防止重复导入
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
        
        # 2. 极其硬核的 Cypher 批量插入语句 (UNWIND)
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
                
                # 每 2000 条提交一次，防止撑爆内存
                if count % 2000 == 0:
                    session.run(query, batch=batch)
                    batch = []
                    print(f"   ...已轰炸 {count} 条关系...")
                    
        # 写入最后剩余的零头
        if batch:
            session.run(query, batch=batch)
            
        driver.close()
        print(f"🎉 导入全部完成！耗时: {time.time() - start_time:.2f} 秒")

if __name__ == "__main__":
    # 指向 C++ 目录下的那个 txt 文件
    import_graph_to_neo4j("../backend_cpp/facebook_combined.txt")