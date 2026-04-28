import requests
import json

def generate_ollama_reply(topic, kg_context):
    print("-> 正在调用 Ollama 生成回复...")
    
    prompt = f"""
    你是一个专业的图书馆智能助理。用户正在寻找关于【{topic}】方向的书籍。
    我从图书馆知识图谱中为你检索到了以下真实的书籍资料：
    {json.dumps(kg_context, ensure_ascii=False, indent=2)}
    
    请根据以上资料，用自然、专业且友好的语气向用户推荐。
    要求：
    1. 必须基于提供的资料进行推荐，绝对不能虚构或编造图谱中没有的书籍。
    2. 顺便提一下书籍的评分和亮点简介。
    3. 排版清晰，可以直接给用户阅读。
    """
    
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "qwen",  # ⚠️确保这里填写的是你本地 pull 的模型名称
        "prompt": prompt,
        "stream": False
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json().get("response", "抱歉，我大脑卡壳了，请稍后再试。")
    except Exception as e:
        print(f"Ollama 请求失败: {e}")
        # 兜底逻辑：如果大模型挂了，直接把结构化数据扔给用户
        return f"[系统提示：大模型服务未开启，回退为结构化数据]\n为您找到以下书籍：\n{kg_context}"