import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 后端部署在 WSL2 的 docker 容器里，前端跑在 Windows 本机。
// - 默认方案：localhost:8000（依赖 WSL2 的 localhost 自动转发，一般能通）
// - 备用方案：如果 localhost 转发失效连不上，改用 WSL 的 IP（wsl hostname -I 查到的
//   第一个地址，当前为 172.26.82.177）。把下面的 BACKEND_HOST 改成该 IP 即可。
const BACKEND_HOST = "localhost";
// const BACKEND_HOST = "172.26.82.177"; // 备用：localhost 不通时取消注释

export default defineConfig({
  plugins: [vue()],
  base: "./",
  build: {
    outDir: "dist",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": `http://${BACKEND_HOST}:8000`,
    },
  },
});
