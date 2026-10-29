# 레피 Story Engine

사장님 메모를 재료로 상품에 이야기를 입히는 엔진. v2 명세는 `design/v2-design.md`.

원칙: **사실은 지어내지 않고, 감성은 더할 수 있다.**

## 구성 (v2)

```text
engine/
├── analyzer.md / analyzer.schema.json   메모 → facts(원문 그대로 자른 quote)와 이야기 재료
├── writer.md / writer.schema.json       재료 → 제목 + 문장별 근거(fact_ids, interpretation)
├── reviewer.md / reviewer.schema.json   오프라인 채점 전용 (런타임에서 부르지 않음)
├── run_tests.py                         테스트 메모 13개 실행, 시간·토큰·원가 출력
├── tests/check_calibration.py           B·C 검사 보정 (API 호출 없음) → tests/calibration.md
└── design/                              v2-design.md(명세), review.md, v1/(이전 프롬프트)
```

## 흐름 (api/index.py `run_story_engine`)

```text
Analyzer → 코드: analysis 정리
  (quote가 메모의 어절 경계에 맞지 않거나 부정어를 뗐으면 fact 버림,
   kind=seller_scene fact 또는 상품명이 없으면 NEED_MORE_INFO + 질문 1개)
  ├─ NEED_MORE_INFO → 질문 1개
  ├─ NO_STORY_FOUND
  └─ READY → Writer → 코드 검사
        A 근거(fact_ids·어간 겹침·판매자 표지·구매 재진술·끝맺음) / B 금지(숫자·기간·서비스·
        독점·효능·후기·원산지·재료·비교·고유명사·지어낸 가게) / DEMO 구매·방문담 / 어림·의심 표지 누락 → 문장 삭제
        C 기계 같은 글 신호(H 1개 또는 S 2개 이상), 제목 실패, 비율 초과, 2문장 이상 삭제,
        본문에 상품·가격 문장 없음(NO_PRODUCT_BODY), NO_ADDRESS, COPY_EXAMPLE
        → 남은 시간이 18초 이상이면 Writer 재작성 1회(사유 전달)
     → 마무리: 비율 넘는 감성 문장 삭제, 사실 문장 0개면 NO_STORY_FOUND, 제목 실패면 상품명
```

화면 응답 모양은 v1과 같다(READY: product_card{name, price}, headline, body[] / NEED_MORE_INFO: questions / NO_STORY_FOUND / error).

## 모델·시간

- 모델은 `LEPI_ANALYZER_MODEL`(기본 `claude-sonnet-5-5`)과 `LEPI_WRITER_MODEL`(기본 `claude-sonnet-5-5`)로 단계별로 정한다. `LEPI_MODEL`을 주면 두 단계 모두 그 모델을 쓴다(비교 테스트용).
- effort는 `LEPI_ANALYZER_EFFORT`·`LEPI_WRITER_EFFORT`(기본 analyzer low, writer medium)로 늘 명시한다(모델마다 기본값이 다르다).
- 검사 방식 `LEPI_CHECK_MODE`: `light`(기본. Writer 글을 그대로 쓰되, 메모 어디에도 없는 판매 사실(숫자·금액·기간·서비스·효능·실적·재료·원산지)과 원가·주운 물건 이야기가 든 문장만 지우고, 그런 제목은 상품명으로 바꾼다. 재작성 없음) / `report`(검사만 하고 했을 일을 `lepi_run`의 `would`에 기록) / `enforce`(삭제·다듬기·재작성·대체 적용).
- 이야기 문장에는 금액을 쓰지 않고, 가격·기간·구매 방법은 마지막 문단 실무 정보 한 줄(role info)로 둔다. 구조화 출력(`output_config.format`), 시스템 프롬프트 캐시, 서버 쪽 fallback 베타를 쓴다.
- 요청 시작부터 42초 마감(`LEPI_DEADLINE_S`). 호출마다 `timeout=min(25초, 남은 시간)`(`LEPI_CALL_TIMEOUT_S`; run_tests는 120초·60초로 늘리고 운영 기준 초과 여부만 센다), `max_retries=0`, `max_tokens=6000`. LLM 호출은 최대 3회.
- 원가는 `python engine/run_tests.py --model ...`의 마지막 줄에 나온다(1달러 1400원, Opus $4/$20, Sonnet $2/$10 per MTok).

## 로그와 개인정보

- 요청당 한 줄 `lepi_run {...}`만 남긴다: rid, model, mode, memo_len, additions, readiness, facts/facts_dropped, 삭제 코드별 개수, 신호 코드, 재작성 여부·사유 코드·건너뛴 이유, 호출별 토큰(in/out/cache_w/cache_r)·ms·stop_reason·응답 모델, 오류 종류와 HTTP 상태.
- 메모·quote·문장·제목·질문은 로그에 남기지 않는다. 재작성 사유의 문장 조각은 API로만 보낸다.

## 검증 방법

### 1. 기준 샘플 재현

Writer 프롬프트에 들어 있는 네 샘플(밀짚모자, 쥐꼬리 낚시대, 닉스고, 잉어킹)의 메모를 넣고 돌린다. 기준 결과물에 가까운지 본다. 다만 샘플이 프롬프트 안에 있으므로, 여기서 잘 나오는 건 최소 조건일 뿐이다.

### 2. 새 메모로 일반화 확인 (진짜 검증)

샘플과 겹치지 않는 메모로 돌린다. 특히 이런 종류가 좋다.

- 추억과 무관한 상품 (기능, 맛, 편리함이 중심)
- 전혀 다른 업종 (카페 디저트, 네일 시술, 꽃다발)
- 메모가 아주 짧은 경우 (한두 줄) → NEED_MORE_INFO가 적절히 나오는지
- 메모에 요청문만 많고 재료가 적은 경우

### 3. 확인 항목

- [ ] 메모에 없는 장면이나 손님 반응이 있는가
- [ ] 첫 문장이 인사나 소개 상투구인가
- [ ] 헤드라인의 의미가 본문 마지막에서 반복되는가
- [ ] 같은 동사가 세 번 이상 나오는가
- [ ] 상품명만 바꾸면 다른 상품에도 통하는 문장이 있는가
- [ ] 샘플의 표현("추억템", "사냥 모드", "~해도, ~한다")을 흉내 냈는가
- [ ] 모든 헤드라인이 같은 유형으로 나오는가
- [ ] Reviewer가 위 문제를 실제로 잡아내는가 (일부러 문제 있는 글을 넣어서 확인)

마지막 항목이 중요하다. Reviewer가 통과만 시키면 파이프라인 전체가 의미 없어진다. 앞서 문제가 됐던 쥐꼬리 낚시대 결과물("고양이가 진짜 사냥한다는 게 무슨 의미인지 알게 되는 낚시대…")을 Reviewer에 넣어서 BLOCK과 MAJOR 이슈가 나오는지 먼저 확인할 것.

## 기준 샘플을 추가할 때

사장님이 "이런 느낌"이라고 확정한 결과물만 `writer.md`의 "기준 샘플"에 추가한다. 샘플이 늘수록 프롬프트가 길어지고 비용이 오르므로 5~6개를 넘기지 않는다. 새 샘플은 기존 샘플과 **주제와 헤드라인 유형이 겹치지 않는 것**을 고른다. 겹치는 샘플이 쌓이면 모델이 그 패턴을 규칙처럼 따라 한다.
