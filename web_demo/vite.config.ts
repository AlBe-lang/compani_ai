import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev 보조 — CompaniAI dashboard 백엔드(localhost:8000)로 /api/* 프록시.
// SSE 도 동일 origin 으로 forward 되어 CORS / EventSource 인증 이슈 회피.
//
// 사용:
//   터미널 1: cd <repo> && .venv/bin/python main.py --dashboard
//             (배너에 출력되는 URL 의 ?token=... 을 복사)
//   터미널 2: cd web_demo && npm run dev
//   브라우저:  http://localhost:5173/?token=<위에서 복사한 token>
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/healthz": "http://localhost:8000",
    },
  },
});
