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
          <div class="a-body">{{ m.article.body }}</div>
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
    messages.value.push({ role: "bot", article: data.result });
  } catch (e) {
    const msg = e.response?.data?.detail || "生成失败";
    messages.value.push({ role: "bot", content: `错误：${msg}` });
  } finally {
    loading.value = false;
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
footer { display: flex; padding: 12px; background: #fff; border-top: 1px solid #eee; }
footer input { flex: 1; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px; }
footer button {
  margin-left: 8px; padding: 10px 18px; border: none; border-radius: 8px;
  background: #2f6fed; color: #fff; cursor: pointer;
}
footer button:disabled { opacity: 0.6; }
</style>
