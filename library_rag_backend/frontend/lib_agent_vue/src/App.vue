<template>
  <div class="page">
    <main class="card">
      <header class="header">
        <div>
          <h1>Rasa 聊天助手</h1>
          <p>Vue 前端可视化交互页面</p>
        </div>
        <div class="header-controls">
          <div class="endpoint-box">
            <input
              v-model.trim="endpoint"
              type="text"
              placeholder="Rasa webhook 地址"
            />
            <button type="button" @click="saveEndpoint">保存</button>
          </div>
          <label class="debug-toggle">
            <input v-model="debugLog" type="checkbox" @change="persistDebugLog" />
            <span>控制台调试（F12 → Console，前缀 [Rasa]）</span>
          </label>
        </div>
      </header>

      <section ref="chatRef" class="chat-list">
        <div v-for="item in messages" :key="item.id" class="row" :class="item.role">
          <div class="bubble">{{ item.text }}</div>
        </div>
      </section>

      <footer class="composer">
        <input
          v-model.trim="inputText"
          type="text"
          placeholder="请输入内容，按 Enter 发送"
          @keydown.enter="sendMessage"
        />
        <button type="button" :disabled="sending" @click="sendMessage">
          {{ sending ? "发送中..." : "发送" }}
        </button>
        <button type="button" class="ghost" @click="clearMessages">清空</button>
      </footer>
    </main>
  </div>
</template>

<script>
const STORAGE_ENDPOINT_KEY = "rasa_endpoint";
const STORAGE_SENDER_KEY = "rasa_sender_id";
const STORAGE_DEBUG_KEY = "rasa_debug_log";

export default {
  name: "App",
  data() {
    return {
      endpoint: "http://127.0.0.1:5005/webhooks/rest/webhook",
      inputText: "",
      sending: false,
      messages: [],
      senderId: "",
      /** 为 true 时在浏览器控制台输出请求/原始响应/解析后的 JSON，便于联调 */
      debugLog: true,
    };
  },
  mounted() {
    const savedEndpoint = localStorage.getItem(STORAGE_ENDPOINT_KEY);
    if (savedEndpoint) {
      this.endpoint = savedEndpoint;
    }

    const savedSender = localStorage.getItem(STORAGE_SENDER_KEY);
    if (savedSender) {
      this.senderId = savedSender;
    } else {
      this.senderId = `web-user-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
      localStorage.setItem(STORAGE_SENDER_KEY, this.senderId);
    }

    const savedDebug = localStorage.getItem(STORAGE_DEBUG_KEY);
    if (savedDebug !== null) {
      this.debugLog = savedDebug === "true";
    }

    this.pushMessage("system", "欢迎使用 Rasa 可视化聊天页面。");
    this.pushMessage("system", "请先确保 Rasa 服务已启动并开启 CORS。");
    if (this.debugLog) {
      this.pushMessage(
        "system",
        "已开启「控制台调试」：按 F12 打开开发者工具 → Console，可看到前缀为 [Rasa] 的请求与响应日志。"
      );
    }
  },
  methods: {
    persistDebugLog() {
      localStorage.setItem(STORAGE_DEBUG_KEY, String(this.debugLog));
    },
    /**
     * @param {string} title
     * @param {unknown} payload
     */
    logRasa(title, payload) {
      if (!this.debugLog) return;
      const t = new Date().toISOString();
      console.groupCollapsed(`[Rasa] ${title} @ ${t}`);
      if (payload !== undefined) {
        console.log(payload);
      }
      console.groupEnd();
    },
    saveEndpoint() {
      if (!this.endpoint) {
        this.pushMessage("system", "Webhook 地址不能为空。");
        return;
      }
      localStorage.setItem(STORAGE_ENDPOINT_KEY, this.endpoint);
      this.pushMessage("system", "Webhook 地址已保存。");
    },
    clearMessages() {
      this.messages = [];
      this.pushMessage("system", "聊天记录已清空。");
    },
    pushMessage(role, text) {
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role,
        text,
      });
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
    },
    async sendMessage() {
      if (this.sending || !this.inputText) return;
      if (!this.endpoint) {
        this.pushMessage("system", "请填写 Rasa webhook 地址。");
        return;
      }

      const userText = this.inputText;
      this.inputText = "";
      this.pushMessage("user", userText);
      this.sending = true;

      const requestBody = {
        sender: this.senderId,
        message: userText,
      };

      try {
        this.logRasa("→ 请求", {
          url: this.endpoint,
          method: "POST",
          body: requestBody,
        });

        const response = await fetch(this.endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(requestBody),
        });

        const rawText = await response.text();
        const contentType = response.headers.get("content-type") || "";

        this.logRasa("← HTTP 元信息", {
          ok: response.ok,
          status: response.status,
          statusText: response.statusText,
          contentType,
          rawLength: rawText.length,
        });
        this.logRasa("← 响应体（原始字符串）", rawText);

        if (!response.ok) {
          this.pushMessage("system", `请求失败：HTTP ${response.status}`);
          this.logRasa("← 非 2xx，未解析为消息列表", { rawText });
          return;
        }

        let data;
        try {
          data = rawText ? JSON.parse(rawText) : [];
        } catch (parseErr) {
          this.logRasa("← JSON.parse 失败", {
            message: parseErr.message,
            rawText,
          });
          this.pushMessage("system", "响应不是合法 JSON，详情见控制台 [Rasa] 日志。");
          return;
        }

        this.logRasa("← 响应体（解析后）", data);
        if (this.debugLog && Array.isArray(data) && data.length) {
          console.table(
            data.map((item, i) => ({
              index: i,
              hasText: !!(item && item.text),
              keys:
                item && typeof item === "object"
                  ? Object.keys(item).join(", ")
                  : String(item),
            }))
          );
        }

        // Rasa REST 正常为数组；若为空多为未加载模型、策略未命中或 NLU 未识别意图
        if (!Array.isArray(data) || data.length === 0) {
          this.pushMessage(
            "bot",
            "（暂无回复：后端返回空列表。请确认 Rasa 已加载模型；在 backend 执行 rasa train 后重启 API。F12→Network 可查看响应体。）"
          );
          return;
        }

        let hasText = false;
        data.forEach((item, index) => {
          if (item && typeof item.text === "string" && item.text.trim()) {
            this.pushMessage("bot", item.text);
            hasText = true;
          } else if (this.debugLog && item) {
            this.logRasa(`← 消息项 #${index}（无 text，完整对象）`, item);
          }
        });
        if (!hasText) {
          this.pushMessage(
            "bot",
            "（收到响应，但没有文本字段；可在浏览器 F12 → Network 查看该请求的响应体）"
          );
        }
      } catch (error) {
        this.logRasa("× fetch 异常", { message: error.message, stack: error.stack });
        this.pushMessage("system", `请求异常：${error.message}`);
      } finally {
        this.sending = false;
      }
    },
  },
};
</script>

<style>
* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

.page {
  min-height: 100vh;
  background: #f3f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  font-family: "Microsoft YaHei", Arial, sans-serif;
}

.card {
  width: min(960px, 100%);
  background: #fff;
  border: 1px solid #d9dde6;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
}

.header {
  padding: 14px 16px;
  border-bottom: 1px solid #e7eaf0;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.header h1 {
  margin: 0;
  font-size: 20px;
}

.header p {
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
}

.header-controls {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.endpoint-box {
  display: flex;
  gap: 8px;
  align-items: center;
}

.debug-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #475467;
  cursor: pointer;
  user-select: none;
}

.debug-toggle input {
  cursor: pointer;
}

.endpoint-box input {
  width: 380px;
  max-width: 45vw;
  border: 1px solid #cfd5e2;
  border-radius: 8px;
  padding: 8px 10px;
}

.endpoint-box button,
.composer button {
  border: 1px solid #cfd5e2;
  border-radius: 8px;
  padding: 8px 12px;
  background: #fff;
  cursor: pointer;
}

.chat-list {
  height: 58vh;
  min-height: 360px;
  overflow-y: auto;
  background: #fbfcff;
  padding: 14px;
}

.row {
  display: flex;
  margin-bottom: 10px;
}

.row.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 78%;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  border-radius: 12px;
  padding: 10px 12px;
}

.row.user .bubble {
  background: #2563eb;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.row.bot .bubble {
  background: #e8edf7;
  color: #1f2937;
  border-bottom-left-radius: 4px;
}

.row.system .bubble {
  background: #f2f4f7;
  color: #667085;
  border-bottom-left-radius: 4px;
}

.composer {
  border-top: 1px solid #e7eaf0;
  padding: 10px;
  display: flex;
  gap: 8px;
}

.composer input {
  flex: 1;
  border: 1px solid #cfd5e2;
  border-radius: 8px;
  padding: 10px 12px;
}

.composer button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.composer .ghost {
  color: #444;
  background: #fafafa;
}

@media (max-width: 900px) {
  .header {
    flex-direction: column;
    align-items: stretch;
  }

  .endpoint-box input {
    width: 100%;
    max-width: none;
  }
}
</style>
