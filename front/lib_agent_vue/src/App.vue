<template>
  <div class="page">
    <main class="card">
      <header class="header">
        <div>
          <h1>图书馆智能助手</h1>
          <p>Vue 与 Rasa REST Webhook 联调</p>
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
          <label class="debug-toggle">
            <input
              v-model="showJsonPanel"
              type="checkbox"
              @change="persistShowJsonPanel"
            />
            <span>页面内显示请求/响应 JSON</span>
          </label>
          <div class="json-actions">
            <button type="button" class="btn-json" @click="downloadExchanges">
              下载会话 JSON
            </button>
            <span v-if="exchanges.length" class="json-hint"
              >已记录 {{ exchanges.length }} 轮</span
            >
          </div>
        </div>
      </header>

      <section
        v-show="showJsonPanel && exchanges.length"
        class="json-debug-strip"
        aria-label="Rasa 请求响应 JSON"
      >
        <p class="json-debug-title">各轮与后端的 JSON 交互（可展开）</p>
        <div
          v-for="(ex, idx) in exchanges"
          :key="ex.id"
          class="json-debug-turn"
        >
          <details>
            <summary>
              第 {{ idx + 1 }} 轮
              <span class="json-debug-user-preview">{{ ex.userText }}</span>
            </summary>
            <pre class="json-pre">{{ formatExchangeJson(ex) }}</pre>
          </details>
        </div>
      </section>

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
const STORAGE_JSON_PANEL_KEY = "rasa_json_panel";

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
      /** 在页面上显示每轮与后端的 JSON 交互 */
      showJsonPanel: true,
      /** 每轮一条：请求体、HTTP 元信息、原始响应、解析后数组或解析错误 */
      exchanges: [],
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

    const savedJsonPanel = localStorage.getItem(STORAGE_JSON_PANEL_KEY);
    if (savedJsonPanel !== null) {
      this.showJsonPanel = savedJsonPanel === "true";
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
    persistShowJsonPanel() {
      localStorage.setItem(STORAGE_JSON_PANEL_KEY, String(this.showJsonPanel));
    },
    /**
     * @param {Record<string, unknown>} ex
     * @returns {string}
     */
    formatExchangeJson(ex) {
      return JSON.stringify(ex, null, 2);
    },
    downloadExchanges() {
      const pack = {
        exportedAt: new Date().toISOString(),
        client: "lib_agent_vue",
        endpoint: this.endpoint,
        senderId: this.senderId,
        turns: this.exchanges,
      };
      const text = JSON.stringify(pack, null, 2);
      const blob = new Blob([text], { type: "application/json;charset=utf-8" });
      const fileName = `rasa-library-chat-${Date.now()}.json`;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = fileName;
      a.click();
      URL.revokeObjectURL(a.href);
      this.logRasa("已下载 JSON", { fileName, turns: this.exchanges.length });
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
      this.exchanges = [];
      this.pushMessage("system", "聊天记录与 JSON 调试记录已清空。");
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

      /** @type {Record<string, unknown>} */
      const exchange = {
        id: `${Date.now()}-${Math.random()}`,
        at: new Date().toISOString(),
        userText,
        request: { url: this.endpoint, method: "POST", body: requestBody },
        response: {
          http: null,
          rawText: null,
          parsed: null,
          parseError: null,
        },
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

        exchange.response.http = {
          ok: response.ok,
          status: response.status,
          statusText: response.statusText,
          contentType,
          rawLength: rawText.length,
        };
        exchange.response.rawText = rawText;

        this.logRasa("← HTTP 元信息", {
          ok: response.ok,
          status: response.status,
          statusText: response.statusText,
          contentType,
          rawLength: rawText.length,
        });
        this.logRasa("← 响应体（原始字符串）", rawText);

        if (!response.ok) {
          this.exchanges.push(exchange);
          this.pushMessage("system", `请求失败：HTTP ${response.status}`);
          this.logRasa("← 非 2xx，未解析为消息列表", { rawText });
          return;
        }

        let data;
        try {
          data = rawText ? JSON.parse(rawText) : [];
          exchange.response.parsed = data;
        } catch (parseErr) {
          exchange.response.parseError = {
            name: parseErr && parseErr.name ? parseErr.name : "Error",
            message: parseErr && parseErr.message ? parseErr.message : String(parseErr),
          };
          this.exchanges.push(exchange);
          this.logRasa("← JSON.parse 失败", {
            message: parseErr.message,
            rawText,
          });
          this.pushMessage("system", "响应不是合法 JSON，详情见控制台 [Rasa] 日志。");
          return;
        }

        this.exchanges.push(exchange);

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
            "（暂无回复：后端返回空列表。请确认 Rasa 已加载模型；在 backend 执行 rasa train 后重启 API。可展开「页面内 JSON」或下载 JSON 查看完整响应。）"
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
        this.exchanges.push({
          id: `${Date.now()}-${Math.random()}`,
          at: new Date().toISOString(),
          userText,
          request: { url: this.endpoint, method: "POST", body: requestBody },
          error: { message: error.message, name: error.name },
        });
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

.json-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.btn-json {
  font-size: 12px;
  padding: 6px 10px;
  border: 1px solid #2563eb;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  cursor: pointer;
}

.btn-json:hover {
  background: #dbeafe;
}

.json-hint {
  font-size: 11px;
  color: #98a2b3;
}

.json-debug-strip {
  max-height: 36vh;
  overflow-y: auto;
  border-bottom: 1px solid #e7eaf0;
  background: #f8fafc;
  padding: 10px 14px;
}

.json-debug-title {
  margin: 0 0 8px;
  font-size: 12px;
  color: #475467;
  font-weight: 600;
}

.json-debug-turn {
  margin-bottom: 6px;
}

.json-debug-turn details {
  font-size: 12px;
  color: #344054;
}

.json-debug-turn summary {
  cursor: pointer;
  user-select: none;
  list-style: none;
}

.json-debug-turn summary::-webkit-details-marker {
  display: none;
}

.json-debug-user-preview {
  margin-left: 8px;
  color: #667085;
  font-weight: normal;
  max-width: 48vw;
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.json-pre {
  margin: 8px 0 0;
  padding: 10px;
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 11px;
  line-height: 1.45;
  overflow-x: auto;
  max-height: 28vh;
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
