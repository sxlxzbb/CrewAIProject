<template>
  <div class="chat-wrap">
    <header>
      <span>编辑部 Agent · {{ username }}</span>
      <button class="logout" @click="onLogout">退出</button>
    </header>

    <div class="messages">
      <div
        v-for="(m, i) in messages"
        :key="i"
        :class="['msg', m.role]"
      >
        <div class="role">{{ m.role === "user" ? "我" : "编辑部" }}</div>

        <!-- 消息内容四态互斥：生成中 / 错误 / 文章 / 纯文本 -->
        <div v-if="m.run_id && !m.article && !m.error" class="gen-progress">
          <div class="gp-step">{{ describeStep(m.current_step) }}</div>
          <div class="gp-bar">
            <div class="gp-fill" :class="{ active: m.status === 'RUNNING' }"></div>
          </div>
          <div class="gp-actions">
            <button class="gp-stop" @click="onCancel(m)">停止</button>
            <span class="gp-hint">{{ m.status || 'PENDING' }} · 每 1 秒刷新</span>
          </div>
        </div>

        <div v-else-if="m.error" class="gen-error">
          <span v-if="m.error === '已取消'">⛔ 已取消</span>
          <span v-else>⚠ 生成失败：{{ m.error }}</span>
        </div>

        <div v-else-if="m.article" class="article-card">
          <h3 class="a-title">{{ m.article.title }}</h3>
          <p class="a-meta">
            <span class="a-conf">置信度：{{ formatConfidence(m.article.confidence) }}</span>
          </p>
          <div v-if="m.article.summary" class="a-summary">
            <span class="a-label">摘要</span>{{ m.article.summary }}
          </div>
          <div v-if="m.article.keywords && m.article.keywords.length" class="a-keywords">
            <span class="a-label">关键词</span>
            <span v-for="(k, ki) in m.article.keywords" :key="ki" class="tag">{{ k }}</span>
          </div>
          <!-- 正文：完整展示；若 body 为空则回退展示 summary 并提示 -->
          <div class="a-body">
            <span class="a-label">正文</span>
            <template v-if="m.article.body">{{ m.article.body }}</template>
            <template v-else-if="m.article.summary">{{ m.article.summary }}<em class="a-tip">（正文为空，已用摘要代替）</em></template>
            <em v-else class="a-tip">（正文为空）</em>
          </div>

          <!-- 重新生成历史：每次重新生成在「前一次内容」的分割线下追加一层结果；
               进行中的进度卡片始终渲染在最底部（即「当前前一次内容」分割线下） -->
          <template v-if="m.regen_articles && m.regen_articles.length">
            <div v-for="(ra, ri) in m.regen_articles" :key="ri" class="a-regen">
              <hr class="a-divider" />
              <div class="a-regen-result">
                <div class="a-regen-head">重新生成结果（第 {{ ri + 1 }} 次）</div>
                <h3 class="a-title">{{ ra.title }}</h3>
                <div v-if="ra.summary" class="a-summary">
                  <span class="a-label">摘要</span>{{ ra.summary }}
                </div>
                <div v-if="ra.keywords && ra.keywords.length" class="a-keywords">
                  <span class="a-label">关键词</span>
                  <span v-for="(k, ki) in ra.keywords" :key="ki" class="tag">{{ k }}</span>
                </div>
                <div class="a-body">
                  <span class="a-label">正文</span>
                  <template v-if="ra.body">{{ ra.body }}</template>
                  <template v-else-if="ra.summary">{{ ra.summary }}</template>
                  <em v-else class="a-tip">（正文为空）</em>
                </div>
              </div>
            </div>
          </template>

          <!-- 进行中的进度卡片：永远在最底部（前一次内容分割线下） -->
          <div v-if="m.regenerating" class="a-regen">
            <hr class="a-divider" />
            <div class="gen-progress regen-progress">
              <div class="gp-step">{{ describeStep(m.current_step) }}</div>
              <div class="gp-bar">
                <div class="gp-fill" :class="{ active: m.status === 'RUNNING' }"></div>
              </div>
              <div class="gp-actions">
                <button class="gp-stop" @click="onCancel(m)">停止</button>
                <span class="gp-hint">{{ m.status || 'PENDING' }} · 重新生成中</span>
              </div>
            </div>
          </div>

          <!-- 人工审核区：放在卡片最底部；需人工审核且状态为待审核时显示 -->
          <div v-if="m.require_review && m.review_status === 0" class="a-review">
            <span class="a-label">待审核</span>
            <button class="rv approve" :disabled="m.reviewing || m.regenerating" @click="onReview(m, 'approve')">通过并发布</button>
            <button class="rv reject" :disabled="m.reviewing || m.regenerating" @click="onReview(m, 'reject')">放弃</button>
            <button class="rv regen" :disabled="m.reviewing || m.regenerating" @click="onReview(m, 'regenerate')">重新生成</button>
          </div>

          <!-- 审核结果提示 -->
          <div v-if="m.review_status === -1" class="a-review-done ok">
            已自动发布成功
          </div>
          <div v-else-if="m.review_status === 1" class="a-review-done ok">
            已通过{{ m.published ? '并发布' : '' }}
          </div>
          <div v-else-if="m.review_status === 2" class="a-review-done no">
            已放弃（未发布）
          </div>
        </div>

        <div v-else class="content">{{ m.content }}</div>
      </div>
    </div>

    <footer>
      <input
        v-model="topic"
        placeholder="输入主题，例如：阿里云千问模型发布 qwen3"
        @keyup.enter="onSend"
        :disabled="loading"
      />
      <button @click="onSend" :disabled="loading">发送</button>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, nextTick } from "vue";
import { useRouter } from "vue-router";
import axios from "axios";

const router = useRouter();
const username = ref(localStorage.getItem("username") || "");
const topic = ref("");
const loading = ref(false);
const messages = ref([]);

onMounted(() => {
  messages.value.push({
    role: "bot",
    content: "你好，我是技术媒体编辑部 Agent。给我一个主题，我会搜索、分析、撰写并审校成稿。",
  });
});

// Agent 小步骤中文映射（不展示大步骤，只展示具体 Agent）
const STEP_LABELS = {
  researching: "调研中",
  analyzing: "分析中",
  writing: "撰写中",
  editing: "审校中",
  working: "处理中",
};

function describeStep(step) {
  if (!step) return "已提交，排队中...";
  // step 形如 "writing#2"
  const [name, round] = step.split("#");
  const label = STEP_LABELS[name] || name || "处理中";
  const suffix = round ? `（第 ${round} 轮）` : "";
  return `${label}${suffix}`;
}

// 轮询单个生成任务的进度，直到 SUCCESS / FAILED / CANCELLED
async function pollTask(m, isRegen) {
  m._cancelled = false;
  const startedAt = Date.now();
  for (let i = 0; i < 1200; i++) {
    // 最多轮询 20 分钟
    if (m._cancelled) {
      return false;
    }
    await new Promise((r) => setTimeout(r, 1000));
    if (m._cancelled) return false;

    let data;
    try {
      data = (await axios.get(`/api/tasks/${m.run_id}`)).data;
    } catch (e) {
      continue;
    }
    m.current_step = data.current_step;
    m.status = data.status;

    if (data.status === "SUCCESS") {
      if (isRegen) {
        // 把重新生成结果追加到历史列表末尾；进度卡片（m.regenerating）延迟到下方隐藏，
        // 确保进度卡片始终显示在前一次内容的分割线下
        if (!Array.isArray(m.regen_articles)) m.regen_articles = [];
        m.regen_articles.push(data.article);
        m.review_status = data.review_status;
        m.require_review = data.require_review;
        m.published = false;
        // 最小展示时长：若任务过快完成（<1.5s），多等一会儿，避免进度卡片「闪现即消失」
        const elapsed = Date.now() - startedAt;
        if (elapsed < 1500) await new Promise((r) => setTimeout(r, 1500 - elapsed));
        await nextTick();
        m.regenerating = false;   // 进度卡片消，展示本轮重新生成内容
      } else {
        m.article = data.article;
        m.require_review = data.require_review;
        m.review_status = data.review_status;
        m.published = false;
      }
      return true;
    }
    if (data.status === "FAILED") {
      m.regenerating = false;
      m.error = data.error || "生成失败";
      return false;
    }
    if (data.status === "CANCELLED") {
      m.regenerating = false;
      m.error = "已取消";
      return false;
    }
  }
  m.regenerating = false;
  m.error = "生成超时（超过 20 分钟）";
  return false;
}

async function onCancel(m) {
  if (!m.run_id || m.status === "CANCELLED") return;
  try {
    await axios.post(`/api/tasks/${m.run_id}/cancel`);
    m._cancelled = true;
    m.status = "CANCELLED";
    m.error = "已取消";
  } catch (e) {
    alert(e.response?.data?.detail || "取消失败");
  }
}

async function onSend() {
  const t = topic.value.trim();
  if (!t || loading.value) return;
  messages.value.push({ role: "user", content: t });
  topic.value = "";
  loading.value = true;

  const m = reactive({
    role: "bot",
    run_id: null,
    status: "PENDING",
    current_step: null,
    article: null,
    regen_articles: [],
    regenerating: false,
    require_review: false,
    review_status: 0,
    published: false,
    reviewing: false,
    error: null,
  });
  messages.value.push(m);
  try {
    const { data } = await axios.post("/api/generate", { topic: t });
    m.run_id = data.run_id;
    m.require_review = data.require_review;
    const ok = await pollTask(m, false);
    if (!ok && !m.error) {
      m.error = "生成失败";
    }
  } catch (e) {
    const msg = e.response?.data?.detail || "提交失败";
    m.error = msg;
  } finally {
    loading.value = false;
  }
}

async function onReview(m, action) {
  if (!m.run_id) {
    console.warn("[onReview] 无 run_id，忽略", action);
    return;
  }
  console.log("[onReview] 点击:", action, "busy=", m._busy, "reviewing=", m.reviewing, "regenerating=", m.regenerating);
  // 防连点：用独立锁，避免依赖 m.reviewing/m.regenerating 初始值
  if (m._busy) return;
  m._busy = true;
  try {
    if (action === "regenerate") {
      // 重新生成：乐观地立即展示进度卡片（在分割线下），再异步提交；新结果追加到 regen_articles
      m.reviewing = true;
      m.regenerating = true;
      m.status = "RUNNING";
      m.current_step = null;
      m.error = null;
      // 强制让进度卡片先渲染出来再发请求
      await nextTick();
      await new Promise((r) => setTimeout(r, 50));
      try {
        await axios.post(`/api/review/${m.run_id}`, { action });
      } catch (e) {
        m.regenerating = false;
        m.reviewing = false;
        alert(`重新生成提交失败：${e.response?.data?.detail || e.message}`);
        return;
      }
      const ok = await pollTask(m, true);
      if (!ok && !m.error) m.error = "重新生成失败";
    } else {
      m.reviewing = true;
      try {
        const { data } = await axios.post(`/api/review/${m.run_id}`, { action });
        m.review_status = action === "reject" ? 2 : data.review_status ?? 1;
        m.published = !!data.published;
      } catch (e) {
        alert(`审核操作失败：${e.response?.data?.detail || e.message}`);
      }
    }
  } finally {
    m._busy = false;
    // 重新生成的进度卡片由 pollTask 在结果就绪后再隐藏；此处兜底清除按钮锁定
    m.reviewing = false;
    if (!m.regenerating) m.reviewing = false;
  }
}

function formatConfidence(c) {
  const v = Number(c);
  if (!isFinite(v)) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

function onLogout() {
  localStorage.removeItem("token");
  localStorage.removeItem("username");
  router.push("/login");
}
</script>

<style scoped>
.chat-wrap { display: flex; flex-direction: column; height: 100vh; }
header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; background: #2f6fed; color: #fff;
}
.logout {
  background: rgba(255,255,255,0.2); border: none; color: #fff;
  padding: 6px 12px; border-radius: 6px; cursor: pointer;
}
.messages { flex: 1; overflow-y: auto; padding: 16px; }
.msg { margin-bottom: 14px; max-width: 80%; }
.msg.user { margin-left: auto; text-align: right; }
.msg .role { font-size: 12px; color: #999; margin-bottom: 4px; }
.msg .content {
  display: inline-block; text-align: left;
  background: #fff; padding: 10px 14px; border-radius: 10px;
  white-space: pre-wrap; line-height: 1.6;
}
.msg.user .content { background: #2f6fed; color: #fff; }
.article-card {
  display: inline-block; text-align: left;
  background: #fff; padding: 16px 18px; border-radius: 12px;
  border: 1px solid #eaeaea; max-width: 720px; line-height: 1.7;
}
.a-title { margin: 0 0 6px; font-size: 18px; color: #1f2d3d; }
.a-meta { margin: 0 0 10px; font-size: 12px; color: #888; }
.a-conf { background: #eef4ff; color: #2f6fed; padding: 2px 8px; border-radius: 6px; }
.a-summary {
  background: #f7f9fc; padding: 8px 12px; border-radius: 8px;
  font-size: 14px; color: #555; margin-bottom: 10px;
}
.a-label {
  display: inline-block; font-size: 12px; font-weight: 600; color: #888;
  margin-right: 8px;
}
.a-keywords { margin-bottom: 10px; }
.tag {
  display: inline-block; background: #eef4ff; color: #2f6fed;
  font-size: 12px; padding: 2px 8px; border-radius: 6px; margin: 0 6px 4px 0;
}
.a-body { white-space: pre-wrap; font-size: 14px; color: #333; }
.a-body .a-label { vertical-align: top; margin-right: 8px; }
.a-tip { color: #e0902a; font-style: normal; font-size: 12px; margin-left: 4px; }
.a-regen { margin-top: 16px; }
.a-divider { border: none; border-top: 1px dashed #d9d9d9; margin: 4px 0 14px; }
.a-regen-head { font-size: 13px; font-weight: 600; color: #f0a020; margin-bottom: 10px; }
.regen-progress { display: block; max-width: none; margin-top: 2px; }
.a-review { margin-top: 12px; padding-top: 12px; border-top: 1px dashed #eee; }
.a-review .rv {
  margin-left: 8px; padding: 6px 14px; border: none; border-radius: 6px;
  cursor: pointer; font-size: 13px; color: #fff;
}
.a-review .rv:disabled { opacity: 0.6; cursor: default; }
.a-review .approve { background: #21a366; }
.a-review .reject { background: #e15b5b; }
.a-review .regen { background: #f0a020; }
.a-review-done { margin-top: 12px; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.a-review-done.ok { background: #eafaf1; color: #21a366; }
.a-review-done.no { background: #fdeeee; color: #e15b5b; }
footer { display: flex; padding: 12px; background: #fff; border-top: 1px solid #eee; }
footer input { flex: 1; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px; }
footer button {
  margin-left: 8px; padding: 10px 18px; border: none; border-radius: 8px;
  background: #2f6fed; color: #fff; cursor: pointer;
}
footer button:disabled { opacity: 0.6; }

/* 生成中进度 */
.gen-progress {
  display: inline-block; text-align: left;
  background: #fff; padding: 14px 18px; border-radius: 12px;
  border: 1px solid #eaeaea; max-width: 480px;
}
.gp-step { font-size: 15px; font-weight: 600; color: #1f2d3d; margin-bottom: 10px; }
.gp-bar { height: 8px; background: #eef1f6; border-radius: 6px; overflow: hidden; }
.gp-fill {
  height: 100%; width: 30%; background: #c3d4f5; border-radius: 6px;
  transition: width 0.4s ease;
}
.gp-fill.active {
  width: 65%;
  background: linear-gradient(90deg, #2f6fed, #6fa0ff);
  animation: gp-pulse 1.2s ease-in-out infinite;
}
@keyframes gp-pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }
.gp-hint { font-size: 12px; color: #999; }
.gp-actions { margin-top: 10px; display: flex; align-items: center; gap: 10px; }
.gp-stop {
  border: 1px solid #e15b5b; background: #fff; color: #e15b5b;
  padding: 4px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.gp-stop:hover { background: #fdeeee; }
.gen-error {
  display: inline-block; text-align: left;
  background: #fff0f0; padding: 12px 16px; border-radius: 12px;
  border: 1px solid #f3c2c2; color: #de5a5a; max-width: 480px; font-size: 14px;
}
</style>
