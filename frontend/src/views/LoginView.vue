<template>
  <div class="login-wrap">
    <div class="login-card">
      <h2>技术媒体编辑部 Agent</h2>
      <p class="sub">请登录后使用</p>
      <form @submit.prevent="onLogin">
        <input v-model="username" placeholder="账号" autocomplete="username" />
        <input v-model="password" type="password" placeholder="密码" autocomplete="current-password" />
        <button type="submit" :disabled="loading">
          {{ loading ? "登录中..." : "登录" }}
        </button>
      </form>
      <p v-if="error" class="error">{{ error }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import axios from "axios";

const username = ref("");
const password = ref("");
const loading = ref(false);
const error = ref("");
const router = useRouter();

async function onLogin() {
  error.value = "";
  loading.value = true;
  try {
    const params = new URLSearchParams();
    params.append("username", username.value);
    params.append("password", password.value);
    const { data } = await axios.post("/api/auth/login", params, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    localStorage.setItem("token", data.access_token);
    localStorage.setItem("username", data.username);
    router.push("/chat");
  } catch (e) {
    error.value = e.response?.data?.detail || "登录失败";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-card {
  width: 340px;
  background: #fff;
  padding: 32px;
  border-radius: 12px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
  text-align: center;
}
.login-card h2 { margin: 0 0 4px; font-size: 18px; }
.sub { color: #999; margin: 0 0 20px; font-size: 13px; }
input {
  width: 100%;
  padding: 10px 12px;
  margin-bottom: 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
}
button {
  width: 100%;
  padding: 10px;
  border: none;
  border-radius: 8px;
  background: #2f6fed;
  color: #fff;
  font-size: 15px;
  cursor: pointer;
}
button:disabled { opacity: 0.6; }
.error { color: #e5484d; font-size: 13px; margin-top: 10px; }
.hint { color: #bbb; font-size: 12px; margin-top: 12px; }
</style>
