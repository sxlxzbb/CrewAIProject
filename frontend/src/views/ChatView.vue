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
        <div class="content">{{ m.content }}</div>
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
    messages.value.push({ role: "bot", content: data.result });
  } catch (e) {
    const msg = e.response?.data?.detail || "生成失败";
    messages.value.push({ role: "bot", content: `错误：${msg}` });
  } finally {
    loading.value = false;
  }
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
footer { display: flex; padding: 12px; background: #fff; border-top: 1px solid #eee; }
footer input { flex: 1; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px; }
footer button {
  margin-left: 8px; padding: 10px 18px; border: none; border-radius: 8px;
  background: #2f6fed; color: #fff; cursor: pointer;
}
footer button:disabled { opacity: 0.6; }
</style>
