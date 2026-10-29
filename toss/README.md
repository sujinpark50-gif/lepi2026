# 레피 앱인토스 미니앱 (appName `lepi`)

메모 입력 → 결과 글 화면 하나만 있는 WebView 미니앱이에요. 글은 Vercel에 배포한 레피 서버(`api/index.py`)가 써요. 홍보용 홈페이지(`../index.html`)는 따로 운영해요.

## 개발

```bash
cd toss
npm install
python dev_api.py        # 다른 창에서. Lepi/.env의 ANTHROPIC_API_KEY로 로컬 엔진을 127.0.0.1:8787에 띄워요
npm run dev              # http://localhost:5173 , /api는 로컬 엔진으로 넘어가요
```

일반 브라우저에는 토스 브릿지가 없어요. 그래서 저장(Storage)·복사(Clipboard)·외부 링크(openURL)는 웹 기능으로 대신 동작해요.

## 빌드 (.ait)

```bash
cp .env.example .env     # VITE_LEPI_API_ORIGIN에 배포한 레피 서버 주소를 넣어요
npm run build            # vite build && ait build → lepi.ait
```

`lepi.ait`를 콘솔에 올리고 QR로 토스 앱 테스트를 한 번 이상 마쳐야 검수를 요청할 수 있어요.

## 앱인토스 요건과 이 프로젝트

- 첫 화면이 바로 글 만들기 도구예요(홍보 목적 출시 금지).
- 자체 헤더·로고·뒤로가기는 없어요. 토스 내비게이션 바만 써요(`apps-in-toss.config.ts`).
- 라이트 모드만 쓰고, 핀치 줌은 껐어요.
- AI 고지는 처음 생성할 때 한 번 시트로 띄워요(앱에 들어오자마자 띄우지 않아요). 입력창 아래에 늘 안내가 있고, 결과에는 "AI가 쓴 글" 표시가 붙어요.
- 실패하면 자동으로 다시 부르지 않아요. 45초가 지나면 끊어요.
- 권한은 결과 복사용 클립보드 쓰기만 써요.
- 서버 CORS는 `https://lepi.apps.tossmini.com`, `https://lepi.private-apps.tossmini.com`만 허용해요(`api/index.py`).
- 로고: `brand/logo-600.png`(600×600, 콘솔 업로드용). 랜딩페이지의 새싹 달린 "lepi." 로고를 색 버전으로 그린 것이고, 원본은 `brand/logo.html`(Chrome 헤드리스로 600×600 스크린샷)이에요.
