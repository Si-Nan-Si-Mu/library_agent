from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

@app.route("/nlu", methods=["POST"])
def nlu_process():
    data = request.json
    text = data.get("text")
    print(f"[NLU Dispatcher] 收到文本: {text}")

    # 调用 Rasa 模型
    rasa_url = "http://localhost:5005/model/parse"
    rasa_resp = requests.post(rasa_url, json={"text": text}).json()

    intent = rasa_resp["intent"]["name"]
    entities = rasa_resp.get("entities", [])

    print(f"[NLU Dispatcher] 识别意图: {intent}, 实体: {entities}")

    # 根据意图路由到不同服务
    if intent == "call":
        target_url = "http://localhost:7001/call"
    elif intent == "query":
        target_url = "http://localhost:7002/query"
    else:
        return jsonify({"error": f"未识别的意图: {intent}"}), 400

    # 转发请求给对应业务服务
    resp = requests.post(target_url, json={
        "text": text,
        "intent": intent,
        "entities": entities
    })

    return jsonify(resp.json())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6001)
