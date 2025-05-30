import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import vueDevTools from "vite-plugin-vue-devtools";

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), vueDevTools()],
  server: {
    host: "0.0.0.0", // 외부 접속을 위해 이미 설정했을 수 있습니다.
    // port: 5173, // 필요시 포트 설정
    allowedHosts: ["didimdol.duckdns.org", "6438-3-36-29-2.ngrok-free.app"], // 여기에 호스트명을 추가합니다.
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
