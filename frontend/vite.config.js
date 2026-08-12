import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 后端内嵌托管：构建到 dist，base 用相对路径
export default defineConfig({
  plugins: [vue()],
  base: "./",
  build: {
    outDir: "dist",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
