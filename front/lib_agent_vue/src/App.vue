<template>
  <div class="page" :class="`density-${densityMode}`">
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
          <label class="debug-toggle density-select">
            <span>显示密度</span>
            <select v-model="densityMode" @change="persistDensityMode">
              <option value="standard">标准</option>
              <option value="large">大字</option>
            </select>
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
          <div class="bubble">
            <template v-if="item.kind === 'catalog'">
              <div class="catalog-panel">
                <div class="catalog-header">
                  <strong>借书书目表（可查询/翻页）</strong>
                  <span>共 {{ catalogFiltered(item).length }} / {{ item.rows.length }} 本</span>
                </div>
                <div v-if="item.borrowPolicy" class="catalog-policy" :class="{ danger: !item.borrowPolicy.can_borrow }">
                  {{ item.borrowPolicy.message }}
                </div>
                <div
                  v-if="item.borrowPolicy && Array.isArray(item.borrowPolicy.active_books) && item.borrowPolicy.active_books.length"
                  class="catalog-active-books"
                >
                  <div class="catalog-active-title">当前已借未还：</div>
                  <div
                    v-for="(b, idx) in item.borrowPolicy.active_books"
                    :key="`${b.call_number}-${idx}`"
                    class="catalog-active-item"
                  >
                    {{ idx + 1 }}. 《{{ b.book_title }}》 {{ b.call_number }}
                  </div>
                </div>
                <div class="catalog-tools">
                  <input
                    v-model.trim="item.catalogQuery"
                    type="text"
                    placeholder="按书名/索书号查询"
                    @input="item.catalogPage = 1"
                  />
                  <label>
                    每页
                    <select v-model.number="item.catalogPageSize" @change="item.catalogPage = 1">
                      <option :value="5">5</option>
                      <option :value="10">10</option>
                      <option :value="20">20</option>
                    </select>
                  </label>
                </div>
                <table class="catalog-table">
                  <thead>
                    <tr>
                      <th>书名</th>
                      <th>索书号</th>
                      <th>位置</th>
                      <th>借阅情况</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="row in catalogPageRows(item)"
                      :key="`${row.call_number}-${row.book_title}`"
                    >
                      <td>{{ row.book_title }}</td>
                      <td>{{ row.call_number }}</td>
                      <td>{{ row.book_pos }}</td>
                      <td>{{ row.status }}</td>
                      <td>
                        <button
                          type="button"
                          class="btn-pick"
                          :disabled="
                            !row.is_available ||
                            !canAddToQueue(item, row) ||
                            (item.borrowPolicy && !item.borrowPolicy.can_borrow)
                          "
                          @click="pickCatalogBook(row)"
                        >
                          选择此书
                        </button>
                      </td>
                    </tr>
                    <tr v-if="!catalogPageRows(item).length">
                      <td colspan="5" class="catalog-empty">当前查询无匹配结果</td>
                    </tr>
                  </tbody>
                </table>
                <div class="catalog-pager">
                  <button
                    type="button"
                    :disabled="item.catalogPage <= 1"
                    @click="item.catalogPage--"
                  >
                    上一页
                  </button>
                  <span>第 {{ item.catalogPage }} / {{ catalogTotalPages(item) }} 页</span>
                  <button
                    type="button"
                    :disabled="item.catalogPage >= catalogTotalPages(item)"
                    @click="item.catalogPage++"
                  >
                    下一页
                  </button>
                </div>
                <div class="catalog-queue">
                  <div class="catalog-active-title">
                    借书单（{{ borrowQueue.length }}/{{ queueLimit(item) }}）
                  </div>
                  <div v-if="borrowQueue.length">
                    <div
                      v-for="(b, idx) in borrowQueue"
                      :key="`queue-${b.call_number}-${idx}`"
                      class="catalog-active-item queue-item"
                    >
                      <span>{{ idx + 1 }}. 《{{ b.book_title }}》 {{ b.call_number }}</span>
                      <button
                        type="button"
                        class="btn-remove"
                        @click="removeBorrowQueueBook(b.call_number)"
                      >
                        移除
                      </button>
                    </div>
                    <div class="queue-actions">
                      <button
                        type="button"
                        class="btn-undo"
                        :disabled="!lastRemovedQueueItem"
                        @click="undoRemoveBorrowQueueBook"
                      >
                        撤销移除
                      </button>
                      <button type="button" class="btn-cancel" @click="clearBorrowQueue">清空借书单</button>
                      <button type="button" class="btn-pick" @click="openBorrowQueueForm">
                        填写借阅信息并提交
                      </button>
                    </div>
                  </div>
                  <div v-else class="catalog-active-item">尚未选择图书</div>
                </div>
              </div>
            </template>
            <template v-else-if="item.kind === 'return_catalog'">
              <div class="catalog-panel">
                <div class="catalog-header">
                  <strong>还书书目表（可查询/翻页）</strong>
                  <span>共 {{ catalogFiltered(item).length }} / {{ item.rows.length }} 本</span>
                </div>
                <div v-if="item.returnPolicy" class="catalog-policy" :class="{ danger: !item.returnPolicy.can_return }">
                  {{ item.returnPolicy.message }}
                </div>
                <div class="catalog-tools">
                  <input
                    v-model.trim="item.catalogQuery"
                    type="text"
                    placeholder="按书名/索书号查询"
                    @input="item.catalogPage = 1"
                  />
                  <label>
                    每页
                    <select v-model.number="item.catalogPageSize" @change="item.catalogPage = 1">
                      <option :value="5">5</option>
                      <option :value="10">10</option>
                      <option :value="20">20</option>
                    </select>
                  </label>
                </div>
                <table class="catalog-table">
                  <thead>
                    <tr>
                      <th>书名</th>
                      <th>索书号</th>
                      <th>位置</th>
                      <th>借阅时间</th>
                      <th>预计归还</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="row in catalogPageRows(item)"
                      :key="`${row.call_number}-${row.book_title}`"
                    >
                      <td>{{ row.book_title }}</td>
                      <td>{{ row.call_number }}</td>
                      <td>{{ row.book_pos || "-" }}</td>
                      <td>{{ row.borrow_at || "-" }}</td>
                      <td>{{ row.due_at || "-" }}</td>
                      <td>
                        <button
                          type="button"
                          class="btn-pick"
                          :disabled="!canAddToReturnQueue(row)"
                          @click="pickReturnCatalogBook(row)"
                        >
                          选择归还
                        </button>
                      </td>
                    </tr>
                    <tr v-if="!catalogPageRows(item).length">
                      <td colspan="6" class="catalog-empty">当前查询无匹配结果</td>
                    </tr>
                  </tbody>
                </table>
                <div class="catalog-pager">
                  <button
                    type="button"
                    :disabled="item.catalogPage <= 1"
                    @click="item.catalogPage--"
                  >
                    上一页
                  </button>
                  <span>第 {{ item.catalogPage }} / {{ catalogTotalPages(item) }} 页</span>
                  <button
                    type="button"
                    :disabled="item.catalogPage >= catalogTotalPages(item)"
                    @click="item.catalogPage++"
                  >
                    下一页
                  </button>
                </div>
                <div class="catalog-queue">
                  <div class="catalog-active-title">
                    还书单（{{ returnQueue.length }} 本）
                  </div>
                  <div v-if="returnQueue.length">
                    <div
                      v-for="(b, idx) in returnQueue"
                      :key="`return-queue-${b.call_number}-${idx}`"
                      class="catalog-active-item queue-item"
                    >
                      <span>{{ idx + 1 }}. 《{{ b.book_title }}》 {{ b.call_number }}</span>
                      <button
                        type="button"
                        class="btn-remove"
                        @click="removeReturnQueueBook(b.call_number)"
                      >
                        移除
                      </button>
                    </div>
                    <div class="queue-actions">
                      <button
                        type="button"
                        class="btn-undo"
                        :disabled="!lastRemovedReturnQueueItem"
                        @click="undoRemoveReturnQueueBook"
                      >
                        撤销移除
                      </button>
                      <button type="button" class="btn-cancel" @click="clearReturnQueue">清空还书单</button>
                      <button type="button" class="btn-pick" :disabled="returningQueueSubmitting" @click="submitReturnQueue">
                        {{ returningQueueSubmitting ? "提交中..." : "提交归还" }}
                      </button>
                    </div>
                  </div>
                  <div v-else class="catalog-active-item">尚未选择图书</div>
                </div>
              </div>
            </template>
            <template v-else-if="item.kind === 'borrow_form'">
              <div class="borrow-form-panel">
                <div class="borrow-form-title">借阅信息填写</div>
                <div class="borrow-form-book">
                  <div>借书单共 {{ item.selectedBooks.length }} 本：</div>
                  <div
                    v-for="(b, idx) in item.selectedBooks"
                    :key="`form-${b.call_number}-${idx}`"
                    class="catalog-active-item"
                  >
                    {{ idx + 1 }}. 《{{ b.book_title }}》 {{ b.call_number }}
                  </div>
                </div>
                <div class="borrow-form-grid">
                  <label>
                    学号/手机号
                    <input v-model.trim="item.form.studentOrPhone" type="text" />
                  </label>
                  <label>
                    姓名
                    <input v-model.trim="item.form.name" type="text" />
                  </label>
                  <label>
                    借阅时间
                    <input v-model="item.form.borrowAt" type="datetime-local" />
                  </label>
                  <label>
                    预计归还时间
                    <input v-model="item.form.dueAt" type="datetime-local" />
                  </label>
                </div>
                <div class="borrow-form-actions">
                  <button type="button" class="btn-pick" @click="submitBorrowForm(item)">
                    提交借阅信息
                  </button>
                </div>
              </div>
            </template>
            <template v-else-if="item.kind === 'batch_result'">
              <div class="batch-result-panel">
                <div class="batch-result-title">
                  借书单提交完成：成功 {{ item.okRows.length }} 本，失败 {{ item.failRows.length }} 本
                </div>
                <div class="batch-result-meta">
                  <div>读者：{{ item.profile.name }}（{{ item.profile.studentOrPhone }}）</div>
                  <div>借阅时间：{{ item.profile.borrowAt }}</div>
                  <div>预计归还：{{ item.profile.dueAt }}</div>
                </div>
                <div class="batch-result-section ok">
                  <div class="batch-result-section-title">成功</div>
                  <div v-if="item.okRows.length">
                    <div
                      v-for="(r, idx) in item.okRows"
                      :key="`ok-${r.call_number}-${idx}`"
                      class="batch-result-row"
                    >
                      {{ idx + 1 }}. 《{{ r.book_title }}》 {{ r.call_number }}
                      <span v-if="r.book_pos">（位置：{{ r.book_pos }}）</span>
                    </div>
                  </div>
                  <div v-else class="batch-result-row">无</div>
                </div>
                <div class="batch-result-section fail">
                  <div class="batch-result-section-title">
                    失败
                    <span v-if="batchFailStats(item.failRows)" class="batch-result-stats">
                      （{{ batchFailStats(item.failRows) }}）
                    </span>
                  </div>
                  <div v-if="item.failRows.length">
                    <div
                      v-for="(r, idx) in item.failRows"
                      :key="`fail-${r.call_number}-${idx}`"
                      class="batch-result-row"
                    >
                      {{ idx + 1 }}. 《{{ r.book_title }}》 {{ r.call_number }}
                      <span v-if="r.book_pos">（位置：{{ r.book_pos }}）</span>
                      （{{ r.reason }}）
                    </div>
                  </div>
                  <div v-else class="batch-result-row">无</div>
                </div>
              </div>
            </template>
            <template v-else-if="item.kind === 'return_batch_result'">
              <div class="batch-result-panel">
                <div class="batch-result-title">
                  还书单提交完成：成功 {{ item.okRows.length }} 本，失败 {{ item.failRows.length }} 本
                </div>
                <div class="batch-result-section ok">
                  <div class="batch-result-section-title">成功</div>
                  <div v-if="item.okRows.length">
                    <div
                      v-for="(r, idx) in item.okRows"
                      :key="`return-ok-${r.call_number}-${idx}`"
                      class="batch-result-row"
                    >
                      {{ idx + 1 }}. 《{{ r.book_title }}》 {{ r.call_number }}
                      <span v-if="r.book_pos">（位置：{{ r.book_pos }}）</span>
                    </div>
                  </div>
                  <div v-else class="batch-result-row">无</div>
                </div>
                <div class="batch-result-section fail">
                  <div class="batch-result-section-title">
                    失败
                    <span v-if="batchFailStats(item.failRows)" class="batch-result-stats">
                      （{{ batchFailStats(item.failRows) }}）
                    </span>
                  </div>
                  <div v-if="item.failRows.length">
                    <div
                      v-for="(r, idx) in item.failRows"
                      :key="`return-fail-${r.call_number}-${idx}`"
                      class="batch-result-row"
                    >
                      {{ idx + 1 }}. 《{{ r.book_title }}》 {{ r.call_number }}
                      <span v-if="r.book_pos">（位置：{{ r.book_pos }}）</span>
                      （{{ r.reason }}）
                    </div>
                  </div>
                  <div v-else class="batch-result-row">无</div>
                </div>
              </div>
            </template>
            <template v-else>{{ item.text }}</template>
          </div>
        </div>
      </section>
      <div v-if="borrowFormModalVisible" class="modal-mask" @click.self="closeBorrowFormModal">
        <div class="modal-panel">
          <div class="borrow-form-title">借阅信息填写</div>
          <div class="borrow-form-book">
            <div>借书单共 {{ borrowFormSelectedBooks.length }} 本：</div>
            <div
              v-for="(b, idx) in borrowFormSelectedBooks"
              :key="`modal-form-${b.call_number}-${idx}`"
              class="catalog-active-item"
            >
              {{ idx + 1 }}. 《{{ b.book_title }}》 {{ b.call_number }}
            </div>
          </div>
          <div class="borrow-form-grid">
            <label>
              学号/手机号
              <input v-model.trim="borrowFormDraft.studentOrPhone" type="text" />
            </label>
            <label>
              姓名
              <input v-model.trim="borrowFormDraft.name" type="text" />
            </label>
            <label>
              借阅时间
              <input v-model="borrowFormDraft.borrowAt" type="datetime-local" />
            </label>
            <label>
              预计归还时间
              <input v-model="borrowFormDraft.dueAt" type="datetime-local" />
            </label>
          </div>
          <div class="borrow-form-actions">
            <button type="button" class="btn-cancel" @click="closeBorrowFormModal">取消</button>
            <button type="button" class="btn-pick" :disabled="borrowingQueueSubmitting" @click="submitBorrowForm()">
              {{ borrowingQueueSubmitting ? "提交中..." : "提交借阅信息" }}
            </button>
          </div>
        </div>
      </div>

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
const STORAGE_DENSITY_KEY = "rasa_density_mode";

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
      /** 页面显示密度：standard | large */
      densityMode: "standard",
      /** 借书交互表单数据 */
      borrowCatalogRows: [],
      borrowQueue: [],
      returnCatalogRows: [],
      returnQueue: [],
      lastRemovedQueueItem: null,
      lastRemovedReturnQueueItem: null,
      borrowFormModalVisible: false,
      borrowFormSelectedBooks: [],
      borrowFormDraft: {
        studentOrPhone: "",
        name: "",
        borrowAt: "",
        dueAt: "",
      },
      currentBorrowPolicy: null,
      borrowingQueueSubmitting: false,
      currentReturnPolicy: null,
      returningQueueSubmitting: false,
    };
  },
  computed: {},
  watch: {},
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
    const savedDensityMode = localStorage.getItem(STORAGE_DENSITY_KEY);
    if (savedDensityMode === "large" || savedDensityMode === "standard") {
      this.densityMode = savedDensityMode;
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
    persistDensityMode() {
      localStorage.setItem(STORAGE_DENSITY_KEY, this.densityMode);
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
      this.borrowCatalogRows = [];
      this.borrowQueue = [];
      this.returnCatalogRows = [];
      this.returnQueue = [];
      this.lastRemovedQueueItem = null;
      this.lastRemovedReturnQueueItem = null;
      this.borrowFormModalVisible = false;
      this.borrowFormSelectedBooks = [];
      this.currentBorrowPolicy = null;
      this.currentReturnPolicy = null;
      this.borrowingQueueSubmitting = false;
      this.returningQueueSubmitting = false;
      this.pushMessage("system", "聊天记录与 JSON 调试记录已清空。");
    },
    queueLimit(item) {
      const policy = (item && item.borrowPolicy) || this.currentBorrowPolicy;
      if (!policy) return 3;
      const maxActive = Number(policy.max_active || 3);
      const active = Number(policy.active_count || 0);
      return Math.max(0, maxActive - active);
    },
    canAddToQueue(item, row) {
      if (!row || !row.call_number) return false;
      if (this.borrowQueue.some((x) => x.call_number === row.call_number)) return false;
      return this.borrowQueue.length < this.queueLimit(item);
    },
    pickCatalogBook(row) {
      if (!row) return;
      if (this.borrowQueue.some((x) => x.call_number === row.call_number)) {
        return;
      }
      const limit = this.queueLimit(null);
      if (this.borrowQueue.length >= limit) {
        return;
      }
      this.borrowQueue.push(row);
      this.lastRemovedQueueItem = null;
    },
    clearBorrowQueue() {
      this.borrowQueue = [];
      this.lastRemovedQueueItem = null;
    },
    canAddToReturnQueue(row) {
      if (!row || !row.call_number) return false;
      if (this.returnQueue.some((x) => x.call_number === row.call_number)) return false;
      return true;
    },
    pickReturnCatalogBook(row) {
      if (!row) return;
      if (this.returnQueue.some((x) => x.call_number === row.call_number)) return;
      this.returnQueue.push(row);
      this.lastRemovedReturnQueueItem = null;
    },
    clearReturnQueue() {
      this.returnQueue = [];
      this.lastRemovedReturnQueueItem = null;
    },
    removeReturnQueueBook(callNumber) {
      if (!callNumber) return;
      const i = this.returnQueue.findIndex((x) => x.call_number === callNumber);
      if (i < 0) return;
      const [removed] = this.returnQueue.splice(i, 1);
      this.lastRemovedReturnQueueItem = { book: removed, index: i };
    },
    undoRemoveReturnQueueBook() {
      if (!this.lastRemovedReturnQueueItem || !this.lastRemovedReturnQueueItem.book) return;
      const { book, index } = this.lastRemovedReturnQueueItem;
      if (this.returnQueue.some((x) => x.call_number === book.call_number)) {
        this.lastRemovedReturnQueueItem = null;
        return;
      }
      const insertAt = Math.max(0, Math.min(index, this.returnQueue.length));
      this.returnQueue.splice(insertAt, 0, book);
      this.lastRemovedReturnQueueItem = null;
    },
    removeBorrowQueueBook(callNumber) {
      if (!callNumber) return;
      const i = this.borrowQueue.findIndex((x) => x.call_number === callNumber);
      if (i < 0) return;
      const [removed] = this.borrowQueue.splice(i, 1);
      this.lastRemovedQueueItem = { book: removed, index: i };
    },
    undoRemoveBorrowQueueBook() {
      if (!this.lastRemovedQueueItem || !this.lastRemovedQueueItem.book) {
        this.pushMessage("system", "暂无可撤销的移除记录。");
        return;
      }
      const { book, index } = this.lastRemovedQueueItem;
      if (this.borrowQueue.some((x) => x.call_number === book.call_number)) {
        this.lastRemovedQueueItem = null;
        this.pushMessage("system", "撤销失败：该书已存在于借书单。");
        return;
      }
      const limit = this.queueLimit(null);
      if (this.borrowQueue.length >= limit) {
        this.pushMessage("system", `撤销失败：当前借书单最多可保留 ${limit} 本。`);
        return;
      }
      const insertAt = Math.max(0, Math.min(index, this.borrowQueue.length));
      this.borrowQueue.splice(insertAt, 0, book);
      this.lastRemovedQueueItem = null;
    },
    pushMessage(role, text) {
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role,
        kind: "text",
        text,
      });
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
    },
    nowLocalDatetime() {
      const d = new Date();
      d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
      return d.toISOString().slice(0, 16);
    },
    afterDaysLocalDatetime(days) {
      const d = new Date();
      d.setDate(d.getDate() + days);
      d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
      return d.toISOString().slice(0, 16);
    },
    openBorrowQueueForm() {
      if (!this.borrowQueue.length) {
        this.pushMessage("system", "请先在书目表中选择至少 1 本书。");
        return;
      }
      this.borrowFormSelectedBooks = [...this.borrowQueue];
      this.borrowFormDraft = {
        studentOrPhone: "",
        name: "",
        borrowAt: this.nowLocalDatetime(),
        dueAt: this.afterDaysLocalDatetime(30),
      };
      this.borrowFormModalVisible = true;
    },
    closeBorrowFormModal() {
      if (this.borrowingQueueSubmitting) return;
      this.borrowFormModalVisible = false;
    },
    async submitBorrowForm(item) {
      const sourceForm = item && item.form ? item.form : this.borrowFormDraft;
      const selectedBooks =
        item && Array.isArray(item.selectedBooks) ? item.selectedBooks : this.borrowFormSelectedBooks;
      if (!sourceForm || !Array.isArray(selectedBooks) || !selectedBooks.length) return;
      const { studentOrPhone, name, borrowAt, dueAt } = sourceForm;
      if (!studentOrPhone || !name || !borrowAt || !dueAt) {
        this.pushMessage("system", "请完整填写借阅信息后再提交。");
        return;
      }
      if (this.borrowingQueueSubmitting) return;
      this.borrowingQueueSubmitting = true;
      const batchResults = [];
      for (const book of selectedBooks) {
        // 自动逐本直办：一次请求携带借阅信息，不再走“确认借阅”二次意图。
        const confirmData = await this.sendToRasa(book.book_title || "", {
          borrow_profile: {
            studentOrPhone,
            name,
            borrowAt: borrowAt.replace("T", " "),
            dueAt: dueAt.replace("T", " "),
            bookTitle: book.book_title || "",
            callNumber: book.call_number || "",
          },
        }, { muteBotMessages: true });
        const result = this.extractBorrowResult(confirmData, book);
        batchResults.push(result);
      }
      this.borrowingQueueSubmitting = false;
      const okRows = batchResults.filter((x) => x.ok);
      const failRows = batchResults.filter((x) => !x.ok);
      this.syncBorrowCatalogAfterSubmit(okRows);
      this.borrowQueue = [];
      this.lastRemovedQueueItem = null;
      this.borrowFormModalVisible = false;
      this.borrowFormSelectedBooks = [];
      this.pushBatchResultMessage(okRows, failRows, {
        name,
        studentOrPhone,
        borrowAt: borrowAt.replace("T", " "),
        dueAt: dueAt.replace("T", " "),
      });
    },
    async submitReturnQueue() {
      if (!Array.isArray(this.returnQueue) || !this.returnQueue.length) {
        this.pushMessage("system", "请先在待还列表中选择至少 1 本书。");
        return;
      }
      if (this.returningQueueSubmitting) return;
      this.returningQueueSubmitting = true;
      const selectedBooks = [...this.returnQueue];
      const batchResults = [];
      for (const book of selectedBooks) {
        // 逐本归还前先静默拉起还书表单，避免上一本提交后表单已被重置导致后续落入 utter_default。
        await this.sendToRasa("还书", null, { muteBotMessages: true });
        const data = await this.sendToRasa(book.book_title || "", {
          return_profile: {
            bookTitle: book.book_title || "",
            callNumber: book.call_number || "",
          },
        }, { muteBotMessages: true });
        batchResults.push(this.extractReturnResult(data, book));
      }
      this.returningQueueSubmitting = false;
      const okRows = batchResults.filter((x) => x.ok);
      const failRows = batchResults.filter((x) => !x.ok);
      this.syncReturnCatalogAfterSubmit(okRows);
      this.returnQueue = failRows.map((x) => ({
        book_title: x.book_title,
        call_number: x.call_number,
        book_pos: x.book_pos || "",
      }));
      this.lastRemovedReturnQueueItem = null;
      this.pushReturnBatchResultMessage(okRows, failRows);
    },
    extractBorrowResult(data, book) {
      const rows = Array.isArray(data) ? data : [];
      const texts = rows
        .map((x) => (x && typeof x.text === "string" ? x.text.trim() : ""))
        .filter(Boolean);
      const merged = texts.join(" ");
      const ok = /借阅已办理|状态已更新为「已借出」/.test(merged);
      let reason = "后端未返回明确结果";
      if (merged) {
        reason = this.simplifyBorrowFailureReason(merged);
      }
      return {
        ok,
        book_title: (book && book.book_title) || "未命名图书",
        call_number: (book && book.call_number) || "未知索书号",
        book_pos: (book && book.book_pos) || "",
        reason,
      };
    },
    simplifyBorrowFailureReason(text) {
      const raw = String(text || "");
      if (!raw) return "未知错误";
      if (/已借出|重复借阅|无法在演示库中重复借阅/.test(raw)) return "该书已借出";
      if (/上限|未归还.*达到上限|请先归还/.test(raw)) return "超出可借上限";
      if (/未找到|无匹配|核对书名|核对书名与索书号/.test(raw)) return "书目信息无效";
      if (/数据库|处理失败|稍后再试|系统错误/.test(raw)) return "系统繁忙，请稍后重试";
      if (/确认借阅/.test(raw)) return "未完成借阅确认";
      return raw.slice(0, 48);
    },
    extractReturnResult(data, book) {
      const rows = Array.isArray(data) ? data : [];
      const texts = rows
        .map((x) => (x && typeof x.text === "string" ? x.text.trim() : ""))
        .filter(Boolean);
      const merged = texts.join(" ");
      const ok = /归还已办理|状态已更新为「在架」/.test(merged);
      let reason = "后端未返回明确结果";
      if (merged) {
        reason = this.simplifyReturnFailureReason(merged);
      }
      return {
        ok,
        book_title: (book && book.book_title) || "未命名图书",
        call_number: (book && book.call_number) || "未知索书号",
        book_pos: (book && book.book_pos) || "",
        reason,
      };
    },
    simplifyReturnFailureReason(text) {
      const raw = String(text || "");
      if (!raw) return "未知错误";
      if (/我不太明白您的意思|utter_default/.test(raw)) return "会话状态失效，请重试";
      if (/无需办理归还|在架状态/.test(raw)) return "该书已在架";
      if (/无此书的待还记录|当前账号下无此书/.test(raw)) return "无待还记录";
      if (/未找到|核对书名与索书号/.test(raw)) return "书目信息无效";
      if (/数据库|处理失败|稍后再试|系统错误/.test(raw)) return "系统繁忙，请稍后重试";
      return raw.slice(0, 48);
    },
    pushBatchResultMessage(okRows, failRows, profile) {
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role: "bot",
        kind: "batch_result",
        text: "",
        okRows: Array.isArray(okRows) ? okRows : [],
        failRows: Array.isArray(failRows) ? failRows : [],
        profile,
      });
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
    },
    pushReturnBatchResultMessage(okRows, failRows) {
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role: "bot",
        kind: "return_batch_result",
        text: "",
        okRows: Array.isArray(okRows) ? okRows : [],
        failRows: Array.isArray(failRows) ? failRows : [],
      });
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
    },
    batchFailStats(failRows) {
      const rows = Array.isArray(failRows) ? failRows : [];
      if (!rows.length) return "";
      const counter = {};
      rows.forEach((r) => {
        const reason = (r && r.reason) || "其他";
        counter[reason] = (counter[reason] || 0) + 1;
      });
      return Object.entries(counter)
        .map(([k, v]) => `${k} ${v}`)
        .join("，");
    },
    syncBorrowCatalogAfterSubmit(okRows) {
      const successRows = Array.isArray(okRows) ? okRows.filter((x) => x && x.call_number) : [];
      if (!successRows.length) return;
      const successMap = new Map(successRows.map((x) => [x.call_number, x]));
      const patchPolicy = (policy) => {
        if (!policy || typeof policy !== "object") return policy;
        const maxActive = Number(policy.max_active || 3);
        const existing = Array.isArray(policy.active_books) ? policy.active_books : [];
        const byCall = new Map(
          existing
            .filter((x) => x && x.call_number)
            .map((x) => [x.call_number, { book_title: x.book_title || "", call_number: x.call_number }])
        );
        successRows.forEach((r) => {
          byCall.set(r.call_number, {
            book_title: r.book_title || "",
            call_number: r.call_number,
          });
        });
        const active_books = Array.from(byCall.values());
        const active_count = active_books.length;
        const can_borrow = active_count < maxActive;
        const borrower_id = policy.borrower_id || this.senderId;
        return {
          ...policy,
          active_books,
          active_count,
          can_borrow,
          message: `当前账号（${borrower_id}）已借 ${active_count}/${maxActive} 本；${
            can_borrow ? "可继续借阅。" : "已达上限，请先归还后再借。"
          }`,
        };
      };
      this.messages = this.messages.map((msg) => {
        if (!msg || msg.kind !== "catalog") return msg;
        const rows = Array.isArray(msg.rows)
          ? msg.rows.map((row) =>
              successMap.has(row.call_number)
                ? { ...row, status: "已借出", is_available: false }
                : row
            )
          : msg.rows;
        return {
          ...msg,
          rows,
          borrowPolicy: patchPolicy(msg.borrowPolicy),
        };
      });
      this.borrowCatalogRows = Array.isArray(this.borrowCatalogRows)
        ? this.borrowCatalogRows.map((row) =>
            successMap.has(row.call_number) ? { ...row, status: "已借出", is_available: false } : row
          )
        : this.borrowCatalogRows;
      this.currentBorrowPolicy = patchPolicy(this.currentBorrowPolicy);
    },
    syncReturnCatalogAfterSubmit(okRows) {
      const successRows = Array.isArray(okRows) ? okRows.filter((x) => x && x.call_number) : [];
      if (!successRows.length) return;
      const successSet = new Set(successRows.map((x) => x.call_number));
      const patchReturnPolicy = (policy, removedCount = 0) => {
        if (!policy || typeof policy !== "object") return policy;
        const active_count = Math.max(0, Number(policy.active_count || 0) - removedCount);
        const borrower_id = policy.borrower_id || this.senderId;
        return {
          ...policy,
          active_count,
          can_return: active_count > 0,
          message: `当前账号（${borrower_id}）待还 ${active_count} 本；${
            active_count > 0 ? "可在下方选择并批量归还。" : "暂无待还图书。"
          }`,
        };
      };
      this.messages = this.messages.map((msg) => {
        if (!msg || msg.kind !== "return_catalog") return msg;
        const before = Array.isArray(msg.rows) ? msg.rows : [];
        const rows = before.filter((row) => !successSet.has(row.call_number));
        return {
          ...msg,
          rows,
          returnPolicy: patchReturnPolicy(msg.returnPolicy, before.length - rows.length),
        };
      });
      this.returnCatalogRows = Array.isArray(this.returnCatalogRows)
        ? this.returnCatalogRows.filter((row) => !successSet.has(row.call_number))
        : this.returnCatalogRows;
      this.currentReturnPolicy = patchReturnPolicy(this.currentReturnPolicy, successRows.length);

      // 同步借书目录中的可借状态与借阅策略，减少“还书后需手动刷新”的成本。
      this.messages = this.messages.map((msg) => {
        if (!msg || msg.kind !== "catalog") return msg;
        const rows = Array.isArray(msg.rows)
          ? msg.rows.map((row) =>
              successSet.has(row.call_number)
                ? { ...row, status: "在架可借", is_available: true }
                : row
            )
          : msg.rows;
        const policy = msg.borrowPolicy;
        if (!policy || typeof policy !== "object") {
          return { ...msg, rows };
        }
        const maxActive = Number(policy.max_active || 3);
        const existing = Array.isArray(policy.active_books) ? policy.active_books : [];
        const active_books = existing.filter((x) => x && !successSet.has(x.call_number));
        const active_count = active_books.length;
        const can_borrow = active_count < maxActive;
        const borrower_id = policy.borrower_id || this.senderId;
        return {
          ...msg,
          rows,
          borrowPolicy: {
            ...policy,
            active_books,
            active_count,
            can_borrow,
            message: `当前账号（${borrower_id}）已借 ${active_count}/${maxActive} 本；${
              can_borrow ? "可继续借阅。" : "已达上限，请先归还后再借。"
            }`,
          },
        };
      });
    },
    pushCatalogMessage(rows, borrowPolicy = null) {
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role: "bot",
        kind: "catalog",
        text: "",
        rows: Array.isArray(rows) ? rows : [],
        borrowPolicy,
        catalogQuery: "",
        catalogPage: 1,
        catalogPageSize: 10,
      });
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
    },
    pushReturnCatalogMessage(rows, returnPolicy = null) {
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role: "bot",
        kind: "return_catalog",
        text: "",
        rows: Array.isArray(rows) ? rows : [],
        returnPolicy,
        catalogQuery: "",
        catalogPage: 1,
        catalogPageSize: 10,
      });
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
    },
    catalogFiltered(item) {
      const rows = Array.isArray(item.rows) ? item.rows : [];
      const q = (item.catalogQuery || "").toLowerCase();
      if (!q) return rows;
      return rows.filter(
        (x) =>
          (x.book_title || "").toLowerCase().includes(q) ||
          (x.call_number || "").toLowerCase().includes(q)
      );
    },
    catalogTotalPages(item) {
      const n = Math.ceil(this.catalogFiltered(item).length / (item.catalogPageSize || 10));
      return n > 0 ? n : 1;
    },
    catalogPageRows(item) {
      const totalPages = this.catalogTotalPages(item);
      if (item.catalogPage > totalPages) item.catalogPage = totalPages;
      const start = (item.catalogPage - 1) * item.catalogPageSize;
      return this.catalogFiltered(item).slice(start, start + item.catalogPageSize);
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
      await this.sendToRasa(userText);
    },
    async sendToRasa(userText, metadata = null, options = null) {
      if (!userText || this.sending) return [];
      this.sending = true;
      const opts = options && typeof options === "object" ? options : {};
      const muteBotMessages = !!opts.muteBotMessages;

      const requestBody = {
        sender: this.senderId,
        message: userText,
      };
      if (metadata && typeof metadata === "object") {
        requestBody.metadata = metadata;
      }

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
          return [];
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
          return [];
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
          if (!muteBotMessages) {
            this.pushMessage(
              "bot",
              "（暂无回复：后端返回空列表。请确认 Rasa 已加载模型；在 backend 执行 rasa train 后重启 API。可展开「页面内 JSON」或下载 JSON 查看完整响应。）"
            );
          }
          return [];
        }

        data.forEach((item, index) => {
          const payload = item && item.custom && typeof item.custom === "object" ? item.custom : item;
          if (payload && payload.payload_type === "borrow_catalog" && Array.isArray(payload.rows)) {
            this.borrowCatalogRows = payload.rows;
            this.currentBorrowPolicy = payload.borrow_policy || null;
            this.pushCatalogMessage(payload.rows, payload.borrow_policy || null);
          }
          if (payload && payload.payload_type === "return_catalog" && Array.isArray(payload.rows)) {
            this.returnCatalogRows = payload.rows;
            this.currentReturnPolicy = payload.return_policy || null;
            this.pushReturnCatalogMessage(payload.rows, payload.return_policy || null);
          }
          if (!muteBotMessages && item && typeof item.text === "string" && item.text.trim()) {
            this.pushMessage("bot", item.text);
          } else if (this.debugLog && item) {
            this.logRasa(`← 消息项 #${index}（无 text，完整对象）`, item);
          }
        });
        return data;
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
        return [];
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
  padding: 24px;
  font-family: "Microsoft YaHei", Arial, sans-serif;
}

.card {
  width: min(1120px, 100%);
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
  font-size: 24px;
}

.header p {
  margin: 6px 0 0;
  color: #667085;
  font-size: 14px;
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

.density-select select {
  border: 1px solid #cfd5e2;
  border-radius: 6px;
  padding: 2px 6px;
  background: #fff;
  color: #344054;
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
  height: 64vh;
  min-height: 420px;
  overflow-y: auto;
  background: #fbfcff;
  padding: 16px;
}

.catalog-panel {
  margin-bottom: 12px;
  padding: 10px;
  border: 1px solid #d5deef;
  border-radius: 10px;
  background: #f8fbff;
}

.catalog-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  color: #334155;
}

.catalog-tools {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
}

.catalog-policy {
  margin-bottom: 8px;
  font-size: 13px;
  color: #334155;
}

.catalog-policy.danger {
  color: #b42318;
  font-weight: 600;
}

.catalog-active-books {
  margin-bottom: 8px;
  font-size: 13px;
  color: #334155;
}

.catalog-active-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.catalog-active-item {
  margin-bottom: 2px;
}

.queue-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.catalog-queue {
  margin-bottom: 8px;
  padding: 8px;
  border: 1px dashed #cfd5e2;
  border-radius: 8px;
  background: #ffffff;
}

.queue-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.catalog-tools input {
  flex: 1;
  border: 1px solid #cfd5e2;
  border-radius: 6px;
  padding: 6px 8px;
}

.catalog-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: #fff;
}

.catalog-table th,
.catalog-table td {
  border: 1px solid #e5e7eb;
  padding: 6px 8px;
  text-align: left;
}

.btn-pick {
  border: 1px solid #2563eb;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 6px;
  padding: 5px 10px;
  cursor: pointer;
}

.btn-pick:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.catalog-empty {
  text-align: center;
  color: #64748b;
}

.catalog-pager {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
}

.borrow-form-panel {
  min-width: 360px;
}

.borrow-form-title {
  font-weight: 700;
  margin-bottom: 8px;
}

.borrow-form-book {
  font-size: 12px;
  color: #334155;
  margin-bottom: 8px;
}

.borrow-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.borrow-form-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #334155;
}

.borrow-form-grid input {
  border: 1px solid #cfd5e2;
  border-radius: 6px;
  padding: 6px 8px;
}

.borrow-form-actions {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.borrow-confirm-title {
  font-size: 14px;
  margin-bottom: 8px;
}

.borrow-confirm-actions {
  display: flex;
  gap: 8px;
}

.btn-cancel {
  border: 1px solid #d0d5dd;
  color: #344054;
  background: #f8fafc;
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
}

.btn-remove {
  border: 1px solid #fecaca;
  color: #b42318;
  background: #fff5f5;
  border-radius: 6px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 12px;
}

.btn-undo {
  border: 1px solid #fde68a;
  color: #92400e;
  background: #fffbeb;
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
}

.btn-undo:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.batch-result-panel {
  min-width: 360px;
}

.batch-result-title {
  font-weight: 700;
  margin-bottom: 8px;
}

.batch-result-meta {
  font-size: 12px;
  color: #475467;
  margin-bottom: 8px;
}

.batch-result-section {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 8px;
  background: #fff;
}

.batch-result-section.ok {
  border-color: #86efac;
  background: #f0fdf4;
}

.batch-result-section.fail {
  border-color: #fca5a5;
  background: #fef2f2;
}

.batch-result-section-title {
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 4px;
}

.batch-result-stats {
  font-weight: 500;
  color: #475467;
}

.batch-result-row {
  font-size: 12px;
  margin-bottom: 2px;
}

.row {
  display: flex;
  margin-bottom: 10px;
}

.row.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 82%;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 14px;
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
  padding: 12px;
  display: flex;
  gap: 8px;
}

.composer input {
  flex: 1;
  border: 1px solid #cfd5e2;
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 14px;
}

.composer button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.composer .ghost {
  color: #444;
  background: #fafafa;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.38);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
  padding: 16px;
}

.modal-panel {
  width: min(720px, 100%);
  max-height: 82vh;
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid #d9dde6;
  border-radius: 12px;
  box-shadow: 0 20px 45px rgba(0, 0, 0, 0.2);
  padding: 14px;
}

.page.density-large .card {
  width: min(1220px, 100%);
}

.page.density-large .header h1 {
  font-size: 26px;
}

.page.density-large .header p,
.page.density-large .debug-toggle,
.page.density-large .json-debug-title,
.page.density-large .catalog-header,
.page.density-large .catalog-policy,
.page.density-large .catalog-active-books,
.page.density-large .catalog-table,
.page.density-large .borrow-form-book,
.page.density-large .borrow-form-grid label,
.page.density-large .batch-result-meta,
.page.density-large .batch-result-section-title,
.page.density-large .batch-result-row {
  font-size: 14px;
}

.page.density-large .bubble {
  font-size: 15px;
}

.page.density-large .chat-list {
  height: 68vh;
}

.page.density-large .endpoint-box input,
.page.density-large .composer input {
  font-size: 15px;
}

.page.density-large .btn-pick,
.page.density-large .btn-cancel,
.page.density-large .btn-remove,
.page.density-large .btn-undo,
.page.density-large .btn-json,
.page.density-large .endpoint-box button,
.page.density-large .composer button {
  font-size: 14px;
}

.page.density-large .modal-panel {
  width: min(820px, 100%);
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
