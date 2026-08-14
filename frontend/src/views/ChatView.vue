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

        <!-- 结构化文章卡片 -->
        <div v-if="m.article" class="article-card">
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

          <!-- 重新生成的文章：用分割线与原文分隔，不覆盖原文 -->
          <div v-if="m.regen_article" class="a-regen">
            <hr class="a-divider" />
            <div class="a-regen-head">重新生成结果</div>
            <h3 class="a-title">{{ m.regen_article.title }}</h3>
            <div v-if="m.regen_article.summary" class="a-summary">
              <span class="a-label">摘要</span>{{ m.regen_article.summary }}
            </div>
            <div v-if="m.regen_article.keywords && m.regen_article.keywords.length" class="a-keywords">
              <span class="a-label">关键词</span>
              <span v-for="(k, ki) in m.regen_article.keywords" :key="ki" class="tag">{{ k }}</span>
            </div>
            <div class="a-body">
              <span class="a-label">正文</span>
              <template v-if="m.regen_article.body">{{ m.regen_article.body }}</template>
              <template v-else-if="m.regen_article.summary">{{ m.regen_article.summary }}</template>
              <em v-else class="a-tip">（正文为空）</em>
            </div>
          </div>

          <!-- 人工审核区：放在卡片最底部；需人工审核且状态为待审核时显示 -->
          <div v-if="m.require_review && m.review_status === 0" class="a-review">
            <span class="a-label">待审核</span>
            <button class="rv approve" :disabled="m.reviewing" @click="onReview(m, 'approve')">通过并发布</button>
            <button class="rv reject" :disabled="m.reviewing" @click="onReview(m, 'reject')">放弃</button>
            <button class="rv regen" :disabled="m.reviewing" @click="onReview(m, 'regenerate')">重新生成</button>
          </div>

          <!-- 审核结果提示 -->
          <div v-if="m.review_status === 1" class="a-review-done ok">
            已通过{{ m.published ? '并发布' : '' }}
          </div>
          <div v-else-if="m.review_status === 2" class="a-review-done no">
            已放弃（未发布）
          </div>
        </div>

        <!-- 纯文本（用户消息 / 错误提示） -->
        <div v-else class="content">{{ m.content }}</div>
      </div>
      <div v-if="loading" class="msg bot">
        <div class="role">编辑部</div>
        <div class="content">正在创作中，请稍候...</div>
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
import { ref, onMounted } from "vue";
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

async function onSend() {
  const t = topic.value.trim();
  if (!t || loading.value) return;
  messages.value.push({ role: "user", content: t });
  topic.value = "";
  loading.value = true;
  try {
    const { data } = await axios.post("/api/generate", { topic: t });
    // 后端返回结构化文章对象，直接存入 article 字段供卡片渲染
    messages.value.push({
      role: "bot",
      article: data.result,
      run_id: data.run_id,
      require_review: data.require_review,
      review_status: data.review_status,
      published: false,
      reviewing: false,
    });
  } catch (e) {
    const msg = e.response?.data?.detail || "生成失败";
    messages.value.push({ role: "bot", content: `错误：${msg}` });
  } finally {
    loading.value = false;
  }
}

async function onReview(m, action) {
  if (!m.run_id) return;
  m.reviewing = true;
  try {
    const { data } = await axios.post(`/api/review/${m.run_id}`, { action });
    m.review_status = action === "reject" ? 2 : 1;
    m.published = !!data.published;
    if (action === "regenerate") {
      // 重新生成：不覆盖原文，把新文章放在分割线下方展示；重新生成后仍需审核
      m.regen_article = data.result;
      m.review_status = data.review_status;
      m.require_review = data.require_review;
      m.published = false;
      m.reviewing = false;
      return;
    }
  } catch (e) {
    const msg = e.response?.data?.detail || "操作失败";
    alert(`审核操作失败：${msg}`);
  } finally {
    m.reviewing = false;
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
</style>
