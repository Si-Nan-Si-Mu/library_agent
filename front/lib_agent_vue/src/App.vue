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
            <button
              type="button"
              class="btn-json"
              title="导出：每轮 Rasa REST 请求/原始响应/解析结果 + 对话区全部气泡（含书目表、推荐阅读载荷等）"
              @click="downloadInteractionData"
            >
              下载交互数据
            </button>
            <span v-if="canDownloadInteractionData" class="json-hint"
              >HTTP 往返 {{ exchanges.length }} 轮 · 对话气泡 {{ chatBubbleCount }} 条</span
            >
          </div>
        </div>
      </header>

      <section
        v-show="showJsonPanel && exchanges.length"
        class="json-debug-strip"
        aria-label="Rasa 请求响应 JSON"
      >
        <p class="json-debug-title">各轮 HTTP 与 Rasa 返回 JSON（可展开；完整数据请用「下载交互数据」）</p>
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
          <div
            class="bubble"
            :class="{
              'bubble-pending': item.kind === 'pending',
              'bubble-wide': item.kind === 'reading_recommend',
              'bubble-catalog':
                item.kind === 'catalog' ||
                item.kind === 'return_catalog' ||
                item.kind === 'overview_catalog' ||
                item.kind === 'borrow_form',
            }"
          >
            <template v-if="item.kind === 'catalog'">
              <div class="catalog-panel">
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div
                  v-if="item.introText"
                  class="catalog-intro markdown-body"
                  v-html="markdownToSafeHtml(item.introText)"
                />
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
                      <th>简介</th>
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
                      <td class="catalog-summary-cell">{{ row.book_summary || "—" }}</td>
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
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div
                  v-if="item.introText"
                  class="catalog-intro markdown-body"
                  v-html="markdownToSafeHtml(item.introText)"
                />
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
                      <th>简介</th>
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
                      <td class="catalog-summary-cell">{{ row.book_summary || "—" }}</td>
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
                      <td colspan="7" class="catalog-empty">当前查询无匹配结果</td>
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
            <template v-else-if="item.kind === 'overview_catalog'">
              <div class="catalog-panel overview-catalog-panel">
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div
                  v-if="item.introText"
                  class="catalog-intro markdown-body"
                  v-html="markdownToSafeHtml(item.introText)"
                />
                <div class="catalog-header">
                  <strong>在架书目总览（只读）</strong>
                  <span v-if="item.overviewStats">
                    馆藏 {{ item.overviewStats.total }} · 在架 {{ item.overviewStats.on_shelf }} · 已借
                    {{ item.overviewStats.borrowed }}
                  </span>
                </div>
                <div class="overview-pager-hint">
                  每次只从数据库加载尚未浏览过的页码；已看过的页会缓存在本页，返回<strong>上一页</strong>不再请求后端、也不显示加载动画。
                </div>
                <div class="overview-table-wrap" :class="{ 'is-loading': item.overviewLoading }">
                  <div v-if="item.overviewLoading" class="overview-loading-overlay" aria-busy="true">
                    <span class="overview-spinner" />
                    <span>加载中…</span>
                  </div>
                  <table class="catalog-table overview-table">
                    <thead>
                      <tr>
                        <th class="col-idx">序号</th>
                        <th>书名</th>
                        <th>索书号</th>
                        <th>架位</th>
                        <th>简介</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(row, idx) in item.rows"
                        :key="`ov-${row.call_number}-${idx}-${item.overviewPage}`"
                      >
                        <td class="col-idx">{{ (item.overviewPage - 1) * item.overviewPageSize + idx + 1 }}</td>
                        <td>《{{ row.book_title }}》</td>
                        <td>{{ row.call_number }}</td>
                        <td>{{ row.book_pos }}</td>
                        <td class="catalog-summary-cell">{{ row.book_summary || "—" }}</td>
                      </tr>
                      <tr v-if="!item.rows.length && !item.overviewLoading">
                        <td colspan="5" class="catalog-empty">本页无在架记录</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div class="catalog-pager overview-server-pager">
                  <button
                    type="button"
                    :disabled="item.overviewLoading || !item.overviewHasPrev"
                    @click="changeOverviewCatalogPage(item, -1)"
                  >
                    上一页
                  </button>
                  <span>第 {{ item.overviewPage }} / {{ overviewCatalogTotalPages(item) }} 页</span>
                  <button
                    type="button"
                    :disabled="item.overviewLoading || !item.overviewHasMore"
                    @click="changeOverviewCatalogPage(item, 1)"
                  >
                    下一页
                  </button>
                </div>
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div
                  v-if="item.overviewFootnote"
                  class="catalog-intro markdown-body overview-footnote"
                  v-html="markdownToSafeHtml(item.overviewFootnote)"
                />
              </div>
            </template>
            <template v-else-if="item.kind === 'reading_recommend'">
              <div class="rr-panel">
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div class="rr-intro markdown-body" v-html="markdownToSafeHtml(item.readingPayload.intro)" />
                <div class="rr-topic-pill">检索主题：{{ item.readingPayload.topic }}</div>

                <div class="rr-sep" role="separator" aria-hidden="true">━━━━━</div>
                <h4 class="rr-section-title">本馆馆藏 · 在架可借</h4>
                <table class="rr-table">
                  <thead>
                    <tr>
                      <th>书名</th>
                      <th>简介</th>
                      <th>索书号</th>
                      <th>馆藏位置</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, idx) in item.readingPayload.on_shelf_rows" :key="`rr-os-${row.call_number}-${idx}`">
                      <td>《{{ row.book_title }}》</td>
                      <td class="rr-summary">{{ row.book_summary || "—" }}</td>
                      <td>{{ row.call_number }}</td>
                      <td>{{ row.book_pos }}</td>
                      <td><span class="rr-badge rr-badge-ok">{{ row.status }}</span></td>
                    </tr>
                    <tr v-if="!item.readingPayload.on_shelf_rows.length">
                      <td colspan="5" class="rr-empty">暂无在架记录</td>
                    </tr>
                  </tbody>
                </table>

                <div class="rr-sep" role="separator" aria-hidden="true">━━━━━</div>
                <h4 class="rr-section-title">本馆馆藏 · 已借出</h4>
                <table class="rr-table">
                  <thead>
                    <tr>
                      <th>书名</th>
                      <th>简介</th>
                      <th>索书号</th>
                      <th>馆藏位置</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, idx) in item.readingPayload.borrowed_rows" :key="`rr-bw-${row.call_number}-${idx}`">
                      <td>《{{ row.book_title }}》</td>
                      <td class="rr-summary">{{ row.book_summary || "—" }}</td>
                      <td>{{ row.call_number }}</td>
                      <td>{{ row.book_pos }}</td>
                      <td><span class="rr-badge rr-badge-out">{{ row.status }}</span></td>
                    </tr>
                    <tr v-if="!item.readingPayload.borrowed_rows.length">
                      <td colspan="5" class="rr-empty">暂无已借出记录</td>
                    </tr>
                  </tbody>
                </table>

                <div class="rr-sep" role="separator" aria-hidden="true">━━━━━</div>
                <h4 class="rr-section-title">扩展推荐（知识图谱 / 可能非本馆）</h4>
                <table class="rr-table rr-table-graph">
                  <thead>
                    <tr>
                      <th>题名</th>
                      <th>简介</th>
                      <th>索书号</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, idx) in item.readingPayload.graph_rows" :key="`rr-gr-${row.call_number}-${idx}`">
                      <td>《{{ row.book_title }}》</td>
                      <!-- eslint-disable-next-line vue/no-v-html -->
                      <td class="rr-summary rr-md-cell markdown-body" v-html="markdownToSafeHtml(row.book_summary)" />
                      <td>{{ row.call_number }}</td>
                      <td class="rr-hint-cell">{{ row.hint }}</td>
                    </tr>
                    <tr v-if="!item.readingPayload.graph_rows.length">
                      <td colspan="4" class="rr-empty">暂无图谱候选或未配置 Neo4j</td>
                    </tr>
                  </tbody>
                </table>

                <!-- eslint-disable-next-line vue/no-v-html -->
                <div class="rr-footnote markdown-body" v-html="markdownToSafeHtml(item.readingPayload.footnote)" />
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
            <template v-else-if="item.kind === 'pending'">
              <div class="bot-pending" aria-live="polite">
                <span class="bot-pending-label">{{ item.statusText }}</span>
                <span class="bot-pending-dots" aria-hidden="true" />
              </div>
            </template>
            <template v-else-if="item.role === 'bot' && item.kind === 'text'">
              <!-- eslint-disable-next-line vue/no-v-html -->
              <div class="md-bubble markdown-body" v-html="markdownToSafeHtml(item.text)" />
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
import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";

/** GFM 风格 Markdown（换行、列表、加粗等）；源码中的 HTML 由 markdown-it 转义后再经 DOMPurify 清洗。 */
const mdRenderer = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
});

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
  computed: {
    chatBubbleCount() {
      return this.messages.filter((m) => m && (m.role === "user" || m.role === "bot")).length;
    },
    canDownloadInteractionData() {
      return this.exchanges.length > 0 || this.chatBubbleCount > 0;
    },
  },
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
    /**
     * 将 Markdown 转为安全 HTML（供 v-html）。
     * @param {unknown} src
     * @returns {string}
     */
    markdownToSafeHtml(src) {
      const s = typeof src === "string" ? src.trim() : "";
      if (!s) return "";
      try {
        const raw = mdRenderer.render(s);
        return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
      } catch {
        return DOMPurify.sanitize(String(src));
      }
    },
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
    /**
     * 深拷贝为可 JSON 序列化的纯数据。
     * @template T
     * @param {T} obj
     * @param {T | null} fallback
     * @returns {T | null}
     */
    safeJsonClone(obj, fallback = null) {
      try {
        return JSON.parse(JSON.stringify(obj));
      } catch (e) {
        return fallback;
      }
    },
    downloadInteractionData() {
      const pack = {
        exportType: "library_agent_full_interaction",
        exportedAt: new Date().toISOString(),
        client: "lib_agent_vue",
        endpoint: this.endpoint,
        senderId: this.senderId,
        densityMode: this.densityMode,
        debugLogEnabled: this.debugLog,
        messages: this.safeJsonClone(this.messages, []),
        borrowQueue: this.safeJsonClone(this.borrowQueue, []),
        returnQueue: this.safeJsonClone(this.returnQueue, []),
        currentBorrowPolicy: this.safeJsonClone(this.currentBorrowPolicy, null),
        currentReturnPolicy: this.safeJsonClone(this.currentReturnPolicy, null),
        borrowCatalogRowsSnapshot: this.safeJsonClone(this.borrowCatalogRows, []),
        returnCatalogRowsSnapshot: this.safeJsonClone(this.returnCatalogRows, []),
        borrowFormModalVisible: !!this.borrowFormModalVisible,
        borrowFormSelectedBooks: this.safeJsonClone(this.borrowFormSelectedBooks, []),
        borrowFormDraft: this.safeJsonClone(this.borrowFormDraft, {}),
        /** 每轮 Rasa REST：请求体、HTTP 元信息、rawText、parsed（含 text / custom 等） */
        rasaRestExchanges: this.safeJsonClone(this.exchanges, []),
      };
      const text = JSON.stringify(pack, null, 2);
      const blob = new Blob([text], { type: "application/json;charset=utf-8" });
      const fileName = `library-agent-interaction-${Date.now()}.json`;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = fileName;
      a.click();
      URL.revokeObjectURL(a.href);
      this.logRasa("已下载交互数据", {
        fileName,
        exchanges: this.exchanges.length,
        messages: this.messages.length,
      });
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
      this.pushMessage("system", "聊天记录、交互导出数据与 JSON 调试记录已清空。");
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
    pushPendingBotMessage(statusText) {
      const id = `${Date.now()}-${Math.random()}`;
      this.messages.push({
        id,
        role: "bot",
        kind: "pending",
        statusText: statusText || "查询中…",
        text: "",
      });
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
      return id;
    },
    updateMessageById(id, patch) {
      if (!id || !patch || typeof patch !== "object") return;
      const i = this.messages.findIndex((m) => m && m.id === id);
      if (i < 0) return;
      const cur = this.messages[i];
      this.messages.splice(i, 1, { ...cur, ...patch });
    },
    removeMessageById(id) {
      if (!id) return;
      const i = this.messages.findIndex((m) => m && m.id === id);
      if (i < 0) return;
      this.messages.splice(i, 1);
    },
    scrollChatToBottom() {
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
    },
    /** 将一轮 Rasa 返回中的纯文本合并为一条；书目/还书/推荐阅读与引导语合并到同一气泡（introText）。Rasa 常把 text 与 custom 拆成两条数组元素，需把前一条纯 text 并入下一条结构化消息。 */
    applyRasaResponseMessages(data, muteBotMessages) {
      if (!Array.isArray(data) || !data.length) {
        return [];
      }
      const actions = [];
      let pendingIntro = "";

      const mergeIntroParts = (...parts) =>
        parts
          .map((x) => (typeof x === "string" ? x.trim() : ""))
          .filter(Boolean)
          .join("\n\n");

      for (let index = 0; index < data.length; index += 1) {
        const item = data[index];
        const textOne =
          item && typeof item.text === "string" && item.text.trim() ? item.text.trim() : "";
        const payload =
          item && item.custom && typeof item.custom === "object" ? item.custom : null;

        if (payload && payload.payload_type === "reading_recommend") {
          const introText = mergeIntroParts(pendingIntro, textOne);
          pendingIntro = "";
          actions.push({ type: "reading_recommend", payload, introText });
          continue;
        }
        if (payload && payload.payload_type === "borrow_catalog" && Array.isArray(payload.rows)) {
          const introText = mergeIntroParts(pendingIntro, textOne);
          pendingIntro = "";
          actions.push({ type: "borrow_catalog", payload, introText });
          continue;
        }
        if (payload && payload.payload_type === "return_catalog" && Array.isArray(payload.rows)) {
          const introText = mergeIntroParts(pendingIntro, textOne);
          pendingIntro = "";
          actions.push({ type: "return_catalog", payload, introText });
          continue;
        }
        if (payload && payload.payload_type === "overview_catalog") {
          if (payload.mode === "replace_page" && payload.target_message_id) {
            this.patchOverviewCatalogMessage(String(payload.target_message_id), payload);
            pendingIntro = "";
            continue;
          }
          if (Array.isArray(payload.rows)) {
            const introText = mergeIntroParts(pendingIntro, textOne);
            pendingIntro = "";
            actions.push({ type: "overview_catalog", payload, introText });
            continue;
          }
        }
        if (textOne) {
          pendingIntro = mergeIntroParts(pendingIntro, textOne);
        } else if (this.debugLog && item) {
          this.logRasa(`← 消息项 #${index}（无 text，完整对象）`, item);
        }
      }
      const mergedText = pendingIntro.trim();

      const runCatalog = () => {
        for (const a of actions) {
          const p = a.payload;
          if (a.type === "borrow_catalog") {
            this.borrowCatalogRows = p.rows;
            this.currentBorrowPolicy = p.borrow_policy || null;
            this.pushCatalogMessage(p.rows, p.borrow_policy || null, a.introText || "");
          } else if (a.type === "return_catalog") {
            this.returnCatalogRows = p.rows;
            this.currentReturnPolicy = p.return_policy || null;
            this.pushReturnCatalogMessage(p.rows, p.return_policy || null, a.introText || "");
          } else if (a.type === "reading_recommend") {
            this.pushReadingRecommendMessage(p, a.introText || "");
          } else if (a.type === "overview_catalog") {
            this.pushOverviewCatalogMessage(p, a.introText || "");
          }
        }
      };

      runCatalog();
      if (!muteBotMessages && mergedText) {
        this.pushMessage("bot", mergedText);
      }
      if (this.debugLog && muteBotMessages) {
        if (mergedText) {
          this.logRasa("← 静默轮次 合并文本", mergedText);
        }
      }
      this.scrollChatToBottom();
      return data;
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
    pushCatalogMessage(rows, borrowPolicy = null, introText = "") {
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role: "bot",
        kind: "catalog",
        text: "",
        introText: typeof introText === "string" ? introText : "",
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
    pushReturnCatalogMessage(rows, returnPolicy = null, introText = "") {
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role: "bot",
        kind: "return_catalog",
        text: "",
        introText: typeof introText === "string" ? introText : "",
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
    pushOverviewCatalogMessage(payload, introText = "") {
      const p = payload && typeof payload === "object" ? payload : {};
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role: "bot",
        kind: "overview_catalog",
        text: "",
        introText: typeof introText === "string" ? introText : "",
        overviewStats: p.stats && typeof p.stats === "object" ? p.stats : null,
        overviewPage: p.page != null ? Number(p.page) : 1,
        overviewPageSize: p.page_size != null ? Number(p.page_size) : 10,
        overviewHasPrev: !!p.has_prev,
        overviewHasMore: !!p.has_more,
        rows: Array.isArray(p.rows) ? p.rows : [],
        overviewFootnote: typeof p.footnote === "string" ? p.footnote : "",
        overviewLoading: false,
        overviewPageCache: (() => {
          const pg = p.page != null ? Number(p.page) : 1;
          const rows = Array.isArray(p.rows) ? p.rows.map((r) => ({ ...r })) : [];
          return {
            [String(pg)]: {
              rows,
              has_prev: !!p.has_prev,
              has_more: !!p.has_more,
              stats: p.stats && typeof p.stats === "object" ? { ...p.stats } : null,
            },
          };
        })(),
      });
      this.$nextTick(() => {
        const chatEl = this.$refs.chatRef;
        if (chatEl) {
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      });
    },
    patchOverviewCatalogMessage(id, p) {
      const i = this.messages.findIndex((m) => m && m.id === id && m.kind === "overview_catalog");
      if (i < 0) return false;
      const cur = this.messages[i];
      const pk = String(p.page != null ? Number(p.page) : cur.overviewPage || 1);
      const prevCache = cur.overviewPageCache && typeof cur.overviewPageCache === "object" ? cur.overviewPageCache : {};
      const cache = { ...prevCache };
      cache[pk] = {
        rows: Array.isArray(p.rows) ? p.rows.map((r) => ({ ...r })) : [],
        has_prev: !!p.has_prev,
        has_more: !!p.has_more,
        stats: p.stats && typeof p.stats === "object" ? { ...p.stats } : cur.overviewStats,
      };
      this.messages.splice(i, 1, {
        ...cur,
        overviewLoading: false,
        overviewPageCache: cache,
        overviewStats: p.stats && typeof p.stats === "object" ? p.stats : cur.overviewStats,
        overviewPage: p.page != null ? Number(p.page) : cur.overviewPage,
        overviewPageSize: p.page_size != null ? Number(p.page_size) : cur.overviewPageSize,
        overviewHasPrev: !!p.has_prev,
        overviewHasMore: !!p.has_more,
        rows: Array.isArray(p.rows) ? p.rows : [],
        overviewFootnote:
          typeof p.footnote === "string" ? p.footnote : cur.overviewFootnote || "",
      });
      return true;
    },
    overviewCatalogTotalPages(item) {
      const os = Number(item && item.overviewStats && item.overviewStats.on_shelf) || 0;
      const ps = Number(item && item.overviewPageSize) || 10;
      if (!os) return 1;
      return Math.max(1, Math.ceil(os / ps));
    },
    async changeOverviewCatalogPage(item, delta) {
      if (!item || item.overviewLoading || !this.endpoint) return;
      const msgId = item.id;
      const live = this.messages.find((m) => m && m.id === msgId && m.kind === "overview_catalog");
      if (!live) return;

      const ps = Number(live.overviewPageSize) || 10;
      const cur = Number(live.overviewPage) || 1;
      const nextPage = cur + delta;
      if (nextPage < 1) return;
      const totalPages = this.overviewCatalogTotalPages(live);
      if (nextPage > totalPages) return;

      const cache = live.overviewPageCache && typeof live.overviewPageCache === "object" ? live.overviewPageCache : {};
      const hit = cache[String(nextPage)];
      if (hit && Array.isArray(hit.rows)) {
        const idx = this.messages.findIndex((m) => m && m.id === msgId && m.kind === "overview_catalog");
        if (idx < 0) return;
        const curMsg = this.messages[idx];
        this.messages.splice(idx, 1, {
          ...curMsg,
          overviewLoading: false,
          overviewPage: nextPage,
          rows: hit.rows.map((r) => ({ ...r })),
          overviewHasPrev: !!hit.has_prev,
          overviewHasMore: !!hit.has_more,
          overviewStats: hit.stats && typeof hit.stats === "object" ? hit.stats : curMsg.overviewStats,
          overviewPageCache: { ...cache },
        });
        return;
      }

      live.overviewLoading = true;
      try {
        const token = delta < 0 ? "__LIB_OVERVIEW_PREV__" : "__LIB_OVERVIEW_PAGE__";
        await this.sendToRasa(
          token,
          {
            overview_catalog: {
              page: nextPage,
              page_size: ps,
              target_message_id: msgId,
            },
          },
          { muteBotMessages: true },
        );
      } finally {
        const L = this.messages.find((m) => m && m.id === msgId && m.kind === "overview_catalog");
        if (L) {
          L.overviewLoading = false;
        } else {
          item.overviewLoading = false;
        }
      }
    },
    pushReadingRecommendMessage(payload, introPrefix = "") {
      const p = payload && typeof payload === "object" ? payload : {};
      const prefix = (introPrefix || "").trim();
      const baseIntro = typeof p.intro === "string" ? p.intro : "";
      const introMerged = [prefix, baseIntro].filter(Boolean).join("\n\n");
      const readingPayload = {
        topic: typeof p.topic === "string" ? p.topic : "",
        intro: introMerged,
        on_shelf_rows: Array.isArray(p.on_shelf_rows) ? p.on_shelf_rows : [],
        borrowed_rows: Array.isArray(p.borrowed_rows) ? p.borrowed_rows : [],
        graph_rows: Array.isArray(p.graph_rows) ? p.graph_rows : [],
        footnote: typeof p.footnote === "string" ? p.footnote : "",
      };
      this.messages.push({
        id: `${Date.now()}-${Math.random()}`,
        role: "bot",
        kind: "reading_recommend",
        text: "",
        readingPayload,
      });
      this.scrollChatToBottom();
    },
    catalogFiltered(item) {
      const rows = Array.isArray(item.rows) ? item.rows : [];
      const q = (item.catalogQuery || "").toLowerCase();
      if (!q) return rows;
      return rows.filter(
        (x) =>
          (x.book_title || "").toLowerCase().includes(q) ||
          (x.call_number || "").toLowerCase().includes(q) ||
          (x.book_summary || "").toLowerCase().includes(q)
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

      let pendingId = null;
      let thinkTimer = null;
      const clearThinkTimer = () => {
        if (thinkTimer) {
          clearTimeout(thinkTimer);
          thinkTimer = null;
        }
      };

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
        if (!muteBotMessages) {
          pendingId = this.pushPendingBotMessage("查询中…");
          thinkTimer = setTimeout(() => {
            const msg = this.messages.find((m) => m.id === pendingId);
            if (msg && msg.kind === "pending") {
              this.updateMessageById(pendingId, { statusText: "思考中…" });
            }
          }, 1100);
        }

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
          clearThinkTimer();
          this.removeMessageById(pendingId);
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
          clearThinkTimer();
          this.removeMessageById(pendingId);
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
          clearThinkTimer();
          this.removeMessageById(pendingId);
          if (!muteBotMessages) {
            this.pushMessage(
              "bot",
              "（暂无回复：后端返回空列表。请确认 Rasa 已加载模型；在 backend 执行 rasa train 后重启 API。可展开「页面内 JSON」或下载交互数据查看完整响应。）"
            );
          }
          return [];
        }

        clearThinkTimer();
        if (!muteBotMessages && pendingId) {
          const msg = this.messages.find((m) => m.id === pendingId);
          if (msg && msg.kind === "pending") {
            this.updateMessageById(pendingId, { statusText: "回复中…" });
          }
          await this.$nextTick();
        }
        this.removeMessageById(pendingId);
        this.applyRasaResponseMessages(data, muteBotMessages);
        return data;
      } catch (error) {
        clearThinkTimer();
        this.removeMessageById(pendingId);
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

.catalog-intro {
  margin-bottom: 10px;
  font-size: 14px;
  line-height: 1.55;
  color: #0f172a;
}

.catalog-intro.markdown-body {
  white-space: normal;
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

.catalog-summary-cell,
.rr-summary {
  font-size: 12px;
  color: #475569;
  line-height: 1.35;
  max-width: 14rem;
  word-break: break-word;
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

.overview-catalog-panel .overview-pager-hint {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 8px;
}

.overview-table-wrap {
  position: relative;
  min-height: 120px;
}

.overview-table-wrap.is-loading .overview-table {
  opacity: 0.45;
  pointer-events: none;
  transition: opacity 0.2s ease;
}

.overview-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 13px;
  color: #0f172a;
  background: rgba(248, 251, 255, 0.82);
  border-radius: 8px;
}

.overview-spinner {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 3px solid #cbd5e1;
  border-top-color: #2563eb;
  animation: overview-spin 0.75s linear infinite;
}

@keyframes overview-spin {
  to {
    transform: rotate(360deg);
  }
}

.overview-table .col-idx {
  width: 48px;
  text-align: center;
  color: #64748b;
}

.overview-footnote {
  margin-top: 10px;
  font-size: 13px;
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

.row.bot .bubble.bubble-pending {
  background: #dce7f7;
  border: 1px dashed #93b4e8;
}

.bot-pending {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.bot-pending-label {
  font-weight: 600;
  color: #1d4ed8;
}

.bot-pending-dots::after {
  content: "…";
  display: inline-block;
  animation: rasa-pending-pulse 1s ease-in-out infinite;
}

@keyframes rasa-pending-pulse {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

.row.system .bubble {
  background: #f2f4f7;
  color: #667085;
  border-bottom-left-radius: 4px;
}

.row.bot .bubble.bubble-wide {
  max-width: min(96%, 920px);
}

/* 借书/还书书目表、借阅表单：固定气泡宽度，避免随内容或分页在 82% 与窄版之间跳动 */
.row.bot .bubble.bubble-catalog {
  width: 880px;
  max-width: 100%;
  box-sizing: border-box;
}

.row.bot .bubble.bubble-catalog .catalog-panel,
.row.bot .bubble.bubble-catalog .borrow-form-panel {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.rr-panel {
  width: 100%;
}

.rr-intro {
  font-size: 13px;
  color: #374151;
  margin: 0 0 8px;
  line-height: 1.55;
  white-space: normal;
}

/* Markdown：DeepSeek 回复与扩展推荐简介 */
.markdown-body {
  white-space: normal;
}

.markdown-body > *:first-child {
  margin-top: 0;
}

.markdown-body > *:last-child {
  margin-bottom: 0;
}

.markdown-body p {
  margin: 0.4em 0;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
  margin: 0.5em 0 0.35em;
  font-size: 1.05em;
  font-weight: 700;
  color: #0f172a;
}

.markdown-body ul,
.markdown-body ol {
  margin: 0.35em 0;
  padding-left: 1.35em;
}

.markdown-body li {
  margin: 0.15em 0;
}

.markdown-body strong {
  font-weight: 700;
  color: #111827;
}

.markdown-body code {
  font-size: 0.9em;
  background: #f1f5f9;
  padding: 0.1em 0.35em;
  border-radius: 4px;
}

.markdown-body pre {
  margin: 0.4em 0;
  padding: 8px;
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 12px;
}

.markdown-body pre code {
  background: transparent;
  padding: 0;
  color: inherit;
}

.markdown-body a {
  color: #1d4ed8;
}

.md-bubble {
  white-space: normal;
}

.row.bot .bubble .md-bubble {
  min-width: 0;
}

.rr-md-cell.markdown-body {
  font-size: 12px;
  line-height: 1.45;
}

.rr-topic-pill {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 2px 10px;
  border-radius: 999px;
  margin-bottom: 10px;
}

.rr-sep {
  text-align: center;
  letter-spacing: 0.25em;
  color: #94a3b8;
  font-size: 11px;
  margin: 14px 0 10px;
}

.rr-section-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.rr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin-bottom: 4px;
  table-layout: fixed;
}

.rr-table th,
.rr-table td {
  border: 1px solid #cbd5e1;
  padding: 6px 8px;
  vertical-align: top;
  word-break: break-word;
}

.rr-table th {
  background: #f1f5f9;
  color: #334155;
  text-align: left;
}

.rr-empty {
  text-align: center;
  color: #64748b;
  font-style: italic;
}

.rr-hint-cell {
  color: #475569;
  font-size: 11px;
  white-space: normal;
}

.rr-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.rr-badge-ok {
  background: #dcfce7;
  color: #166534;
}

.rr-badge-out {
  background: #fee2e2;
  color: #991b1b;
}

.rr-badge-graph {
  background: #e0e7ff;
  color: #3730a3;
}

.rr-footnote {
  margin: 12px 0 0;
  font-size: 11px;
  color: #64748b;
  white-space: normal;
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
