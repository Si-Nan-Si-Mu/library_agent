# client.py
import requests
import json

SERVER_URL = "http://172.20.0.106:5005/model/parse"
# 如果使用 rest webhook 接口，则：
# SERVER_URL = "http://<服务端IP>:5005/webhooks/rest/webhook"

def send_text(text: str):
    payload = {"text": text}
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(SERVER_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print("解析结果：")
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"请求失败：状态码 {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"请求异常：{e}")

def main():
    print("输入文本（输入 exit 退出）：")
    while True:
        txt = input("用户：").strip()
        if txt.lower() in ["exit", "quit"]:
            print("退出客户端。")
            break
        if txt:
            send_text(txt)

if __name__ == "__main__":
    main()
