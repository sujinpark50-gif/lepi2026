import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    // 번들은 토스 도메인에서 열리므로 자산 경로를 상대 경로로 둔다.
    base: './',
    server: {
      // 개발 중에는 /api를 로컬 엔진 서버로 넘긴다(CORS 없이 테스트).
      proxy: {
        '/api': env.LEPI_DEV_API_ORIGIN || 'http://127.0.0.1:8787',
      },
    },
  };
});
