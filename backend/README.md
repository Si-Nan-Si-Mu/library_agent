#  图书馆智能问答与推荐系统 (Rasa + Neo4j + Ollama)

本文档提供了基于 **Graph RAG (图增强检索生成)** 架构的图书馆智能问答系统的完整搭建流程。该系统整合了 Rasa（对话管理）、Neo4j（知识图谱）与 Ollama（本地大语言模型）。

---

## 1. 核心架构设计

系统的工作流如下：
1. **用户输入**：用户询问书籍或请求推荐。
2. **Rasa NLU**：识别意图（Intent）并提取实体（Entity，如书名、研究领域）。
3. **Rasa Action**：触发自定义动作脚本。
4. **Neo4j 检索**：Action 根据实体执行 Cypher 语句，从图谱获取结构化背景知识（如：同方向的高分书籍）。
5. **Ollama 生成**：将检索到的图谱数据嵌入 Prompt，发送给本地 LLM。
6. **自然语言回复**：LLM 生成友好的对话式回复返回给用户。

---

## 2. 环境配置与安装

建议在隔离的 Python 虚拟环境中进行开发，避免依赖冲突。推荐使用 **Python 3.9 或 3.10**。

### 2.1 创建并激活虚拟环境
```bash
# 创建虚拟环境
python3 -m venv library_env

# 激活虚拟环境 (Linux / macOS)
source library_env/bin/activate
# Windows 下使用: library_env\Scripts\activate

# 升级 pip
pip install --upgrade pip
```

### 2.2 安装 Rasa
```bash
# 安装 Rasa
pip install rasa

# 验证安装
rasa --version

# 初始化项目目录 (在项目根目录下执行)
rasa init
```

### 2.3 部署 Neo4j (Docker 方式)
推荐使用 Docker 部署 Neo4j，保持系统环境纯净。
```bash
docker run \
    --name neo4j_library \
    -p 7474:7474 -p 7687:7687 \
    -d \
    -e NEO4J_AUTH=neo4j/12345678 \
    neo4j:latest
```

不使用docker：
```bash
cd neo4j-community-4.4.3/bin
./neo4j console
```

* **可视化界面**: 浏览器访问 `http://localhost:7474` (账号 `neo4j` / 密码 `12345678`)
* **程序连接端口**: `7687`

### 2.4 安装本地大模型 Ollama
1. 前往 [Ollama 官网](https://ollama.com/) 下载并安装。
2. 拉取并运行轻量级中文模型（例如 Qwen 2.5 7B）：
```bash
ollama run qwen2.5:7b
```
* Ollama 默认在本地占用 `11434` 端口。

### 2.5 安装中间件依赖包
```bash
# Neo4j 官方 Python 驱动
pip install neo4j

# 用于发送 API 请求给 Ollama
pip install requests
```

---

## 3. 项目目录结构

使用 `rasa init` 生成基础目录后，按照以下规范进行扩展：

```text
library_graph_rag/
├── data/ # Rasa 训练数据
│   ├── nlu.yml # 意图与实体标注
│   ├── rules.yml  # 简单对话规则
│   └── stories.yml # 复杂对话流示例
├── actions/ # 自定义动作 (核心逻辑)
│   ├── __init__.py
│   ├── actions.py # Rasa Action 类定义
│   ├── neo4j_connector.py # Neo4j 查询封装
│   └── llm_service.py    # Ollama API 调用封装
├── kg_module/        # 知识图谱构建模块
│   ├── schema.cypher     # 数据库约束与索引定义
│   ├── import_data.py     # 数据导入脚本
│   └── raw_data/      # 原始书籍数据文件 (CSV/JSON)
├── config/         # 配置文件
│   ├── config.yml     # Rasa NLU 管道配置
│   ├── domain.yml        # 意图、实体、槽位声明
│   └── endpoints.yml     # Action Server & Ollama 地址配置
└── requirements.txt            # Python 依赖清单
```

---

## 4. 分阶段开发实施路径

### 阶段一：构建 Neo4j 知识图谱 (系统大脑)
系统推荐质量取决于图谱数据。首先需要定义数据的 Schema 并导入测试数据。

**节点 (Nodes)**: `:Book`, `:Author`, `:Category`, `:Topic`
**关系 (Relationships)**: `[:WRITTEN_BY]`, `[:BELONGS_TO]`, `[:COVERS_TOPIC]`

**测试 Cypher 语句示例 (在 Neo4j Browser 中执行)**:
```cypher
// 1. 创建测试节点与关系
CREATE (t:Topic {name: "人工智能"})
CREATE (b1:Book {title: "深度学习", rating: 4.8})-[:COVERS_TOPIC]->(t)
CREATE (b2:Book {title: "统计学习方法", rating: 4.9})-[:COVERS_TOPIC]->(t)

// 2. 进阶推荐查询：查找同研究方向的其他书籍
MATCH (target:Book {title: "深度学习"})-[:COVERS_TOPIC]->(topic:Topic)<-[:COVERS_TOPIC]-(rec:Book)
WHERE target <> rec
RETURN rec.title, rec.rating, topic.name
ORDER BY rec.rating DESC LIMIT 3
```

### 阶段二：训练 Rasa NLU (系统耳朵)
在 `domain.yml` 和 `data/nlu.yml` 中定义意图和实体。

**nlu.yml 示例**:
```yaml
version: "3.1"
nlu:
  - intent: recommend_by_topic
    examples: |
      - 我想看关于[人工智能](topic)的研究书籍
      - 帮我找几本[分布式系统](topic)相关的书
      - 有没有[深度学习](topic)方向的推荐？
```

### 阶段三：打通 Custom Actions (系统神经)
在 `actions/actions.py` 中编写逻辑，连接 Rasa 和 Neo4j。**此阶段先不接入大模型，直接返回结构化数据测试链路。**

1. 启动 Action 服务器：
```bash
rasa run actions
```
2. 确保在 `endpoints.yml` 中开启了 action_endpoint。

### 阶段四：接入 Ollama 生成回复 (系统嘴巴)
当 Neo4j 能稳定返回正确数据后，将其注入 Prompt 发送给 Ollama。

**LLM 服务封装示例 (llm_service.py)**:
```python
import requests
import json

def generate_reply_with_ollama(topic, kg_results):
    prompt = f"""
    你是一个专业的图书馆助理。用户对'{topic}'方向感兴趣。
    我们在数据库中找到了以下资料：{kg_results}。
    请根据上述资料，给出有条理、语气友好的推荐回复。不要虚构未提及的书籍。
    """
    
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "qwen2.5:7b",
        "prompt": prompt,
        "stream": False
    }
    
    response = requests.post(url, json=payload)
    return response.json().get("response", "抱歉，生成回复时出现错误。")
```

---

## 5. 启动与调试流程
完成代码编写后，你需要开启三个终端窗口协同运行：

1. **终端 1 (Neo4j & Ollama)**: 确保 Docker 容器和 Ollama 后台服务正在运行。
2. **终端 2 (Action Server)**: `rasa run actions`
3. **终端 3 (Rasa Shell)**: `rasa shell` (在命令行中与你的机器人进行对话测试)