import { defineConfig } from '@apps-in-toss/web-framework/config';

export default defineConfig({
  // 콘솔에 등록한 appName과 같아야 해요. 한 번 정하면 바꿀 수 없어요.
  appName: 'lepi',
  brand: {
    primaryColor: '#283618',
  },
  // 결과 글을 복사할 때만 클립보드 쓰기 권한을 써요.
  permissions: [{ name: 'clipboard', access: 'write' }],
  navigationBar: {
    withBackButton: true,
    withHomeButton: true,
    withTitle: true,
    theme: 'light',
  },
  webView: {
    bounces: false,
    pullToRefreshEnabled: false,
    overScrollMode: 'never',
  },
  webBundleDir: 'dist',
});
