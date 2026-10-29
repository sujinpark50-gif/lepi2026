# api/index.py 변경 요청 (프롬프트·스키마 개편 2026-10-28에 맞춤)

프롬프트·스키마는 이미 바뀌었다(`engine/analyzer.md`, `writer.md`, `*.schema.json`). 아래는 코드가 따라와야 할 것. 번호 순서가 우선순위다. 코드가 그대로 읽는 문자열(`- 상투어:` 줄, `<!-- EXAMPLES:START/END -->`, `>` 예시 줄)은 바이트 그대로 두었으므로 `CLICHES`·`EXAMPLE_NGRAMS`는 영향 없다.

## 0. 스키마 변경 (이미 적용)
- analyzer.schema.json 추가: `charm` = `{fact_ids: string[], note: string} | null` / `common_knowledge` = `[{about: string, note: string}]` / `season` = `{fact_id: string, note: string} | null`. 모두 required.
- writer.schema.json `sentences[]`에 `role: "fact" | "charm" | "scene" | "ending"` 추가(required). 기존 `interpretation`·`is_ending` 의미는 그대로. 코드는 `role`이 없어도(옛 출력) 죽지 않게 `sentence.get("role")`로 읽는다.

## 1. clean_analysis — 새 필드 검증
1. `charm.fact_ids`를 `keep_ids`로 거르고, 남은 id가 0개면 `charm = None`.
2. `season.fact_id`가 유효 fact가 아니면 `season = None`.
3. `common_knowledge`: 항목마다 (a) `_N(about)`이 `memo["n"]`에 없으면 버림, (b) `check_banned(note, [], memo)`에 하나라도 걸리면 버림(NUMBER·EFFICACY·EXCLUSIVE·SOCIAL·ORIGIN·MATERIAL·TASTE·COMPARE·PROPER 모두 적용 — "상식"에 수치·효능·재료가 섞이는 걸 막는다), (c) `_unknown_long_words(note, memo)`가 있으면 버림(진화형 이름 등 새 고유명사), (d) 3개까지만. 로그에 `ck_dropped` 수.

## 2. check_story — 근거 검사에서 세 각도 다루기
1. **상식 문장**: `role == "charm"`이고 `interpretation`이 true이거나, 기존 `product_sentence()` 조건(상품 fact + 상품명 어간)을 만족하면 "상식 문장"으로 본다. 이 문장에는 지금처럼 A2 allowance 3 + `_unknown_long_words` PROPER 검사 + B표를 적용하고, **`cited`에 살아남은 `common_knowledge[].note`의 N을 더한다**(상식 낱말이 "메모 밖 어간"으로 세어져 UNGROUNDED가 되지 않게).
2. **charm 사실 문장**(`role == "charm"`, interpretation false): 보통 사실 문장과 같다. 단 `charm.fact_ids`를 전부 달아 fact 셋을 합친 문장이 되기 쉬우니 A2 allowance를 `min(3, 1 + len(ids) - 1)`로 — cited fact 수에 비례(gap-audit A-5의 쥐꼬리 사례).
3. **season**: `season.fact_id`를 단 문장은 기존대로(PERIOD·EXCLUSIVE 면제는 cited로 이미 됨). 새 S 신호 `NO_SEASON_OPEN`: `season`이 있는데 제목 `headline_fact_ids`에도 첫 kept 문장 `ids`에도 `season.fact_id`가 없음. 1차엔 S 신호(둘 모여야 재작성), 2차엔 로그만.
4. **scene 문장**(`role == "scene"`): interpretation true여야 한다. false로 왔으면 코드가 true로 바꾸고 로그(`role_fix`).

## 3. 끝맺음 표시 — 약속·인사가 지워지지 않게
- `ending_type in ("promise", "greeting")`이고 문장이 Writer 출력의 마지막(`is_ending` true 또는 `index == last_index`)이면, Writer가 `interpretation: false`로 보냈더라도 **`is_fact = False`로 취급**한다(단 `kinds ∩ {how_to_buy, price}`가 있으면 그대로 사실 문장). B표·SERVICE·SHOP_INVENT·COST_LOW·ENDING_INVITE는 그대로 적용. 로그 `ending_fix`.
- `_ratio_state`의 제외 조건은 그대로(promise/greeting + 마지막 문장 + ENDING_INVITE 아님).
- `ENDING_INVITE`에서 문의 권유는 뺀다: `물어보세요|여쭤보세요|말씀해 ?주세요|문의 ?주세요`는 invite가 아니다(rerun 머그컵 오탐).

## 4. 하한 검사 (needs_rewrite)
- `NO_CHARM`: `analysis.charm`이 있거나 `common_knowledge`가 비어 있지 않은데, kept 문장 중 `role == "charm"`이 없음 → 1차 재작성 사유(`NO_PRODUCT_BODY`와 같은 급), 2차엔 로그만. 모든 문장에 `role`이 없으면(옛 출력) 검사 생략.
- `NO_SCENE`: 끝맺음을 뺀 kept 본문이 4문장 이상인데 `role == "scene"`도 interpretation 문장도 없음 → S 신호.
- `finalize` RATIO_TRIM 순서: 비율 초과로 감성 문장을 지울 때 `role == "fact"`인 감성 문장 → `scene` → `charm` 순으로 지운다(매력 문장을 마지막까지 지킨다).

## 5. 삭제 오탐 줄이기 (gap-audit A-5, prompt-plan §3)
1. `_seller_ungrounded`를 `interpretation: true` 문장(특히 role charm·scene·ending)에는 적용하지 않는다. `고민`·`결정` 같은 표지가 손님 장면 문장에 들어가 지워지는 일(rerun 반려돌)을 막는다. 사실 문장에는 그대로.
2. `ADDRESS` regex 보강: `|실 거예요|실 수 있|셔도 (?:좋|돼)` 추가(Writer가 "~사실 수 있어요"를 말 건넴으로 쓰는데 지금은 NO_ADDRESS, 20회 중 4회).
3. 재작성 사유 `detail`에 지워진 문장이 달고 있던 fact id를 덧붙인다: `f"{detail}; facts={','.join(ids)}"`. Writer 9절이 "지워진 문장이 담던 fact는 메모 말로 다시 쓴다"고 지시하므로 id가 보여야 한다.
4. (선택) 제목 `_ungrounded(headline, ...)` allowance를 2로. 프롬프트는 "하나까지"로 두었으니 코드 2는 여유분이다. HEADLINE 재작성 7/20의 절반이 어간 2개 초과였다.

## 6. 재작성 코드 사전과 맞추기
Writer 9절이 아는 코드: UNGROUNDED NO_FACT SELLER_UNGROUNDED HEADLINE NO_ADDRESS RATIO NO_PRODUCT_BODY LOST_FACT NO_CHARM NUMBER PERIOD EFFICACY EXCLUSIVE SOCIAL ORIGIN MATERIAL TASTE SERVICE COMPARE PROPER SHOP_INVENT COST_LOW DEMO_BUYER BUYER_RESTATE HEDGE CLICHE SAME_LAST LIST3 COPY_EXAMPLE. `reasons[].code`는 이 이름 그대로 보낸다(`TRIM_` 접두어는 stats에만). `ENDING_INFO`·`ENDING_INVITE`·`NO_SEASON_OPEN`·`NO_SCENE`은 사전에 없으니 `detail`에 한국어 한 줄을 넣는다(예: "끝맺음이 info인데 구매 방법·가격 fact가 없음").

## 7. 로그·stats 추가
`lepi_run`에 `charm: bool`, `ck: int`(살아남은 common_knowledge 수), `season: bool`, `roles: {fact,charm,scene,ending 개수}`, `ending_fix`, `role_fix`, `ck_dropped`, 신호에 `NO_CHARM`·`NO_SCENE`·`NO_SEASON_OPEN`. 문자열은 남기지 않는다(기존 원칙).

## 8. 바뀌지 않는 것 (확인용)
- `_cliche_patterns`가 읽는 `- 상투어:` 줄: 내용 동일, 이제 writer.md 7절. `_example_ngrams`의 마커·`>` 줄: 동일(해설 "구조:" 2줄만 삭제, n-gram 집합에 영향 없음).
- index.py 1007행 주석 "writer.md 1절 상품명 상식": 여전히 1절이다.
- 테스트 러너(`run_tests.py`, `judge.py`)는 새 필드를 읽지 않아도 된다. `tests/check_calibration.py`가 writer 출력 모양을 가정한다면 `role` 추가에 영향 없음(추가 필드).
