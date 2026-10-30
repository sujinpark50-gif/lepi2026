# LEPI

물건은 흔해도, 고른 이유는 저마다.
LEPI(레피)는 작은 가게 사장님이 적은 상품 메모에서 이야기를 찾아 SNS에 올릴 상품 글로 정리해 주는 AI 서비스입니다.

원칙은 하나입니다. **사실은 지어내지 않고, 감성은 더할 수 있다.**
가격, 날짜, 메뉴명, 조건처럼 틀리면 안 되는 정보는 메모 그대로 지키고,
메모에 없는 효능, 후기, 판매 조건은 쓰지 않습니다. 재료가 모자라면 글 대신 질문을 돌려줍니다.

현재 홈페이지에서 무료로 체험할 수 있고, 무료 베타 신청을 받고 있습니다.
토스 앱 안에서 쓰는 앱인토스 미니앱도 함께 만들고 있습니다.

배포 URL: <https://lepi2026.vercel.app/>


## 1. 주요 기능

### 이야기 입히기 (직접 체험)

사용자가 상품 메모를 입력하면 Story Engine이 메모 속 이야기를 찾아 제목과 본문으로 정리합니다.

- 상품 메모 입력 (최대 500자, 서버에서 검사)
- 결과는 세 가지 중 하나
  - `READY`: 상품명·가격 카드, 제목, 본문 문단. "AI가 쓴 글" 표시가 붙습니다.
  - `NEED_MORE_INFO`: 글을 쓰기에 재료가 부족해 질문 1개를 돌려줍니다. 메모에 답을 덧붙여 다시 누르면 됩니다.
  - `NO_STORY_FOUND`: 메모에서 이야기를 찾지 못했다는 안내를 보여 줍니다.
- 진행 중 단계 안내 (메모를 읽고 있어요 → 이야기를 찾고 있어요 → 글을 다듬고 있어요)
- 처리 중 버튼 비활성화로 중복 요청 방지
- 45초가 지나면 요청을 끊고 안내
- 실패해도 자동으로 다시 부르지 않음
- 주소에 `?test`를 붙이면 구매자 입장에서 쓴 메모를 판매자 글로 바꿔 보는 시연 모드(`DEMO_SELLER`)로 동작


### 무료 베타 신청

랜딩페이지 맨 아래에서 무료 베타를 신청할 수 있습니다.

수집 항목 (모두 필수):

- 이름 또는 닉네임
- 업종 (카페·디저트, 공방·핸드메이드, 네일샵·미용실, 꽃집, 온라인 셀러, 기타 소규모 업장)
- 연락 가능한 이메일
- 베타 참여 동의

신청 데이터는 n8n Webhook으로 보내 처리합니다.

```text
사용자 신청
        ↓
n8n Webhook
        ↓
Google Sheets 저장
        ↓
Discord 신규 신청 알림
```

신청 전 → 신청 중 → 신청 완료로 버튼 상태가 바뀌고, 완료되면 입력칸과 버튼을 잠가 중복 제출을 막습니다.
전송에 실패하면 버튼을 되돌려 다시 시도할 수 있게 합니다.


### 사용 방법 시연

"사용 방법" 영역에서 글쓰기 칸에 적은 메모를 드래그하고, 오른쪽 클릭으로 레피를 불러,
정리된 글을 본문에 넣는 흐름을 보여 줍니다.
마우스를 올리면 커서가 저절로 움직이며 끝까지 진행하고, 휴대폰에서는 화면에 보이면 한 번 자동으로 진행합니다.
직접 드래그하고 클릭해도 똑같이 동작합니다. 실제 API를 부르지 않는 시연 화면입니다.


### 사례

밀짚모자, 선운사 소원의 종, 잉어킹 액막이, 닉스고 인형 키링 사례에서
사장님 메모와 레피가 정리한 글을 나란히 보여 줍니다.
메모 중 글의 재료로 쓴 부분에는 밑줄이 그어집니다.


## 2. 페이지 구성

하나의 랜딩페이지(`index.html`) 안에 여러 섹션이 있고, 상단 메뉴로 이동할 수 있습니다.

- Hero: 핵심 메시지, 밀짚모자 메모 → 정리된 글 전환
- 문제: 설명은 했는데 왜 사야 하는지가 없는 이유 4가지
- 사용 방법: 오른쪽 클릭으로 레피를 부르는 시연
- 사례: 메모와 결과 비교
- 직접 체험: 내 메모로 이야기 입히기
- 레피의 약속: 지어내지 않기, 틀리면 안 되는 정보 지키기, 사장님 말 살리기, 결정은 사장님이
- FAQ
- 베타 신청
- 개인정보 처리 안내: `privacy.html` (`/privacy`)

데스크톱과 모바일에 대응하는 반응형 레이아웃이며, 기기에서 움직임 줄이기를 켜면 전환 애니메이션을 건너뜁니다.


## 3. 기술 스택

### Frontend

- HTML, CSS, JavaScript
- htm + Preact (빌드 없이 페이지 안에 포함)

### Backend

- Python
- Vercel Serverless Functions

### AI

- Claude API (Anthropic)
- 이야기 찾기(Analyzer), 글쓰기(Writer) 모두 `claude-sonnet-5-5`
- 구조화 출력(`output_config.format`), 시스템 프롬프트 캐시, 서버 쪽 fallback 베타 사용

### 앱인토스 미니앱

- Vite, Apps in Toss SDK (`toss/`)

### 배포

- GitHub, Vercel

### 운영 자동화

- n8n, Google Sheets, Discord


## 4. 프로젝트 구조

```text
lepi2026/
├── api/
│   └── index.py          Story Engine 실행 + /api 엔드포인트
├── engine/
│   ├── analyzer.md / analyzer.schema.json   메모 → 사실(fact)과 이야기 재료
│   ├── writer.md / writer.schema.json       재료 → 제목과 문장
│   ├── reviewer.md / reviewer.schema.json   오프라인 채점 전용
│   ├── run_tests.py      테스트 메모 실행, 시간·토큰·원가 출력
│   ├── tests/            기준 결과, 판정(judge), 보정 스크립트
│   ├── design/           설계 문서, 이전 버전 프롬프트
│   └── research/         인스타그램 캡션 조사
├── toss/                 앱인토스 미니앱 (메모 입력 → 결과 화면)
├── images/
│   ├── lepi/             랜딩 사례·Hero 사진
│   └── case-*.jpg        공유용 사례 이미지
├── index.html            랜딩페이지 UI와 동작
├── privacy.html          개인정보 처리 안내
├── og-image.png          링크 미리보기 이미지
├── requirements.txt      Python 패키지 목록
├── vercel.json           Vercel 빌드·경로 설정
├── README.md             프로젝트 설명
└── service_plan.md       서비스 기획서
```

- `vercel.json`이 `/api`를 `api/index.py`로, `/privacy`를 `privacy.html`로 연결합니다.
- `api/index.py`는 `engine/`의 프롬프트와 스키마 파일을 읽어 씁니다.
- 엔진의 자세한 동작과 검사 규칙은 `engine/README.md`, 미니앱은 `toss/README.md`에 있습니다.


## 5. AI 기능 처리 흐름

```text
사용자 메모 입력
        ↓
JavaScript fetch POST /api  { "text": "메모" }
        ↓
Vercel Serverless Function (api/index.py)
        ↓
Analyzer (Claude): 메모에서 사실(fact)과 이야기 재료를 찾음
        ├─ 재료 부족 → NEED_MORE_INFO + 질문 1개
        ├─ 이야기 없음 → NO_STORY_FOUND
        └─ READY
                ↓
        Writer (Claude): 제목과 문장 작성, 문장마다 근거 fact 표시
                ↓
        코드 검사: 메모에 없는 판매 사실이 든 문장 제거
                ↓
JSON 결과 반환
        ↓
웹페이지에 결과 표시
```

- 프론트엔드에서 API 키를 쓰지 않고, 서버리스 함수가 Claude API를 호출합니다.
- Analyzer가 찾는 재료: 판매자 장면, 고른 이유, 상품의 매력(charm), 상품명·풍습 상식(common_knowledge), 제철(season), 가격과 구매 방법.
- 기본 검사 방식(`light`)은 Writer 글을 그대로 쓰되, 메모 어디에도 없는 숫자·금액·기간·서비스·효능·실적·재료·원산지와 원가·주운 물건 이야기가 든 문장만 지웁니다. 이런 제목은 상품명으로 바꿉니다.
- 가격·기간·구매 방법은 본문 마지막 실무 정보 한 줄로 둡니다.
- 앱인토스 미니앱의 토스 도메인(`lepi.apps.tossmini.com`, `lepi.private-apps.tossmini.com`)에서만 CORS를 허용합니다.


## 6. AI 기능 입력 / 출력 / 실패 처리

### 입력

```json
{ "text": "사장님이 적은 상품 메모 (최대 500자)" }
```

### 출력

```json
{
  "status": "READY",
  "product_card": { "name": "상품명", "price": "가격" },
  "headline": "제목",
  "body": ["문단 1", "문단 2"]
}
```

```json
{ "status": "NEED_MORE_INFO", "questions": ["질문 1개"] }
```

```json
{ "status": "NO_STORY_FOUND" }
```

### 실패 처리

| 상황 | 처리 |
| -- | -- |
| 메모가 비어 있음 | 화면에서 API를 부르지 않고 "상품 메모를 입력해 주세요." 표시. 서버로 오면 400 |
| 메모가 500자 초과 | 413. 본문이 8KB를 넘으면 읽기 전에 거절 |
| 요청 형식 오류 | 400 |
| API 키 미설정 | 500 |
| 엔진 처리 중 오류 | 500, 내부 정보 없이 일반 안내 |
| 응답 지연 | 서버는 요청 시작부터 42초(호출당 25초)에 마감, 화면은 45초에 끊음 |

오류 메시지에는 내부 상세 정보나 API 키를 담지 않습니다.


## 7. 로컬 실행 방법

```bash
git clone <저장소 URL>
cd lepi2026
pip install -r requirements.txt
```

환경 변수 `ANTHROPIC_API_KEY`를 설정한 뒤 실행합니다.
미니앱을 로컬에서 띄우는 방법은 `toss/README.md`의 개발 항목을 참고합니다.

엔진만 시험하려면 다음을 실행합니다. 테스트 메모를 돌리고 시간·토큰·원가를 출력합니다.

```bash
python engine/run_tests.py
```


## 8. 환경 변수

필수:

- `ANTHROPIC_API_KEY`

선택 (기본값으로 운영, 비교 테스트용):

| 이름 | 기본값 | 설명 |
| -- | -- | -- |
| `LEPI_ANALYZER_MODEL` | `claude-sonnet-5-5` | 이야기 찾기 모델 |
| `LEPI_WRITER_MODEL` | `claude-sonnet-5-5` | 글쓰기 모델 |
| `LEPI_MODEL` | 없음 | 주면 두 단계 모두 이 모델 |
| `LEPI_ANALYZER_EFFORT` | `low` | Analyzer effort |
| `LEPI_WRITER_EFFORT` | `medium` | Writer effort |
| `LEPI_CHECK_MODE` | `light` | 검사 방식 (`light` / `report` / `enforce`) |
| `LEPI_DEADLINE_S` | `42` | 요청 전체 마감(초) |
| `LEPI_CALL_TIMEOUT_S` | `25` | 호출 하나의 제한 시간(초) |

API 키는 코드에 직접 작성하지 않습니다. Vercel에서는 프로젝트의 Environment Variables에 등록합니다.
API 키가 GitHub 저장소, README, 스크린샷 등에 노출되지 않도록 주의해야 합니다.


## 9. 배포

- GitHub 저장소와 Vercel을 연결해 배포합니다.
- main 브랜치에 push하면 Vercel이 다시 배포합니다.
- 서버리스 함수 최대 실행 시간은 60초입니다(`vercel.json`).
- 앱인토스 미니앱은 `toss/`에서 따로 빌드해 `.ait` 파일을 콘솔에 올립니다.


## 10. 개인정보와 로그

- 레피는 체험에 입력한 메모를 저장하지 않습니다.
- 서버 로그에는 요청당 한 줄(`lepi_run`)만 남기며, 메모·문장·제목·질문 같은 내용은 남기지 않고 토큰 수, 처리 시간, 검사 결과 코드 같은 수치만 남깁니다.
- 메모는 글 작성을 위해 Anthropic의 Claude API로 전송되며, Anthropic은 최대 30일 보관 후 삭제합니다. 자세한 내용은 `privacy.html`에 있습니다.


## 11. 반응형 확인

데스크톱 브라우저와 실제 모바일 기기에서 주요 섹션 레이아웃, 메뉴와 텍스트, 체험 입력 영역,
이야기 입히기 기능, 베타 신청 폼과 완료 상태를 확인했습니다.


## 12. 프로젝트에서 학습한 내용

- HTML, CSS, JavaScript를 이용한 웹페이지 구성과 반응형 확인
- JavaScript fetch()를 이용한 프론트엔드와 백엔드 통신
- Python 기반 Vercel Serverless Function 구현
- Claude API 연동, 구조화 출력, 프롬프트 캐시
- 두 단계(분석 → 작성) LLM 파이프라인과 코드 기반 사실 검사 설계
- 테스트 메모와 판정 스크립트로 프롬프트 품질 비교
- 환경 변수를 이용한 API 키 관리
- GitHub와 Vercel을 이용한 배포
- n8n Webhook을 이용한 Google Sheets 저장과 Discord 알림 자동화
- 앱인토스 미니앱 요건에 맞춘 화면 구성


## 13. 관련 문서

- `service_plan.md`: 서비스 목적, 타겟 사용자, 페이지 구성, AI 기능 설계
- `engine/README.md`: Story Engine 구성, 검사 규칙, 검증 방법
- `engine/design/`: 설계 문서와 점검 기록
- `toss/README.md`: 앱인토스 미니앱 개발과 빌드
