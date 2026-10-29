# 레피 Story Engine v2 설계 (검토 반영판)

작성 2026-10-28 · 카피라이터 에이전트 · 검토 `engine/design/review.md` 24개 항목 반영 · 초안: `engine/design/draft/` (analyzer.md, writer.md, analyzer.schema.json, writer.schema.json). 라이브 파일은 건드리지 않았다.
원칙: **사실은 지어내지 않고, 감성은 더할 수 있다. 사실 중에서도 손님에게 상품·판매자의 가치를 깎아 보이게 하는 건 고르지 않는다**(2026-10-28 사용자 확정). 기준 순서: 사용자 승인 규칙 > 지시문 2단계 > 조사(`research/insta-copy.md`).

## 1. 런타임과 시간
`Analyzer → 코드: analysis 정리 → Writer → 코드 검사 → [조건부 Writer 재작성 1회 → 코드 검사] → 마무리 정리 → 응답`. LLM 최대 3회. reviewer.md는 채점 전용.
- **모델은 설정값 하나** `MODEL`(두 단계 공통). 비교 대상은 전체 Opus 5.5 vs 전체 Sonnet 5.5뿐이다. effort는 low.
- **마감 42초**(요청 시작 기준. 페이지 45초, Vercel 60초). 호출마다 `timeout=min(20, 남은 시간)`, `max_retries=0`, `max_tokens=6000`. 재작성은 남은 시간이 18초 이상일 때만. 재작성이 시간 초과·오류로 끝나면 1차 결과에 삭제와 마무리 정리(4-E)를 적용해 돌려준다. 최악 경로 ≈ 10+10+18초 + 코드 < 42초.
- **analysis 정리(LLM 없음):** (1) fact quote 검증(4-A1) 실패 fact와 그 fact를 가리키는 D 항목·id 참조를 버린다. (2) `seller_scene.fact_ids`에 kind=`seller_scene`인 유효 fact가 1개 이상 없으면, Analyzer가 READY라고 해도 NEED_MORE_INFO + 고정 질문("이 상품을 만들거나 고르면서 직접 하신 일을 한 줄로 알려 주세요."). (3) READY인데 `product.name`이 null이면 NEED_MORE_INFO(같은 고정 질문). (4) 질문은 1개로 자르고, 비어 있으면 고정 질문. (5) `convertible_to`도 4-A2·4-B를 거쳐 실패하면 null.

## 2. Analyzer (draft/analyzer.md, analyzer.schema.json)
| 필드 | 내용 |
|---|---|
| facts[] {id, quote, kind, convertible_to} | quote = raw_input/seller_additions의 글자 그대로, 어절 단위 구간. 부정어(안·못·없·않)를 떼지 않는다. kind: product·price·how_to_buy·seller_scene·seller_feeling·customer_fact·buyer_action |
| product {name, name_fact_id, price_fact_id} | 가격 fact 없으면 null. 상품을 알 수 없으면 name null → NO_STORY_FOUND |
| distinctive_phrases[] {id, phrase, fact_id} / sensory_hook | 1~4어절 원문 / D id 또는 null |
| seller_scene {fact_ids, note} 또는 null | kind=seller_scene fact가 1개 이상 있어야 함. 고정된 선택("~만 써요", "일부러 ~해요")도 seller_scene. 느낌만으로는 안 됨 |
| why_this_one {fact_ids, note, missing_reason} | 근거 없으면 [], null, 이유 |
| scene {kind, fact_ids, note} | seller / product_state(근거 필요) / customer_imagined(상식 수준) |
| mood | 담백·다정·유쾌·설렘·차분 중 하나 |
| ending {type, fact_ids} | 아래 유형 |
| meta_instructions, scenario_mode, story_readiness, questions | v1 재사용. 질문은 1개 |
- **판정:** READY = 유효한 seller_scene + 상품명. NEED_MORE_INFO = seller_scene 없음 → 질문 1개(만들거나 고르면서 실제로 한 일·바꾼 것·본 것). NO_STORY_FOUND = 상품 메모 아님/판매 불가.
- **DEMO_SELLER:** v1 seller_voice_exclusions를 kind=`buyer_action` + `convertible_to`로 합쳤다. 페이지 기본 REAL_SELLER, `mode=demo`만 DEMO(현행 유지).
- **v1에서 뺀 필드:** output_conditions, product.facts/photo_facts, conflicts, experiences, explicit_emotions, seller_intent, seller_additions_applied, functional/personal_reason, purchase_meaning, interpretations, strongest_material, story_core, unknowns.
- 짧은 예는 테스트 9(아메리카노: 가격+맛)와 구조가 겹치지 않게 '스펙만 있는 메모'(린넨 앞치마)로 바꿨다.

**끝맺음 유형** (조사 1절 끝맺음 분포 기준. 기본값 promise 또는 greeting. 바람형은 유형에서 뺐다)
| type | 형태 | 조건 |
|---|---|---|
| promise | 응대 약속 한 줄 | "보여/챙겨/알려 드릴게요" 같은 일반 동사만 말투. 포장·배송·굽기·예약·일정은 SERVICE 검사로 fact 필요 |
| greeting | 계절·날씨·하루 인사 한 줄 | 없음 |
| info | 구매 방법·기간 안내 | cited에 how_to_buy/price fact 필수(코드 확인) |
| invite | "~하셨다면 ~해 보세요" | 메모에 손님에게 권하는 마음·손님 상황이 있을 때만 |
| fact | 마지막 사실 문장 | 재료가 적은 글 |

## 3. Writer (draft/writer.md, writer.schema.json)
- 출력: `product_card {name, price_display}` → `sentences[] {paragraph, text, fact_ids, interpretation, is_ending}` → `headline` → `headline_fact_ids`. `source`, `source_type`, `headline_candidates` 삭제.
- 흐름: seller_scene → why_this_one → scene 하나 → ending. 1~4문단, 재료가 분량을 정한다. 가격은 카드, 본문은 역할이 있을 때만.
- 경계 표(금지/허용/조건부)에 재료·서비스·일정·구매 결과 재진술을 명시. 비율, 권유 내용 근거, 제목 근거, buyer_action은 convertible_to로만.
- 구조 예시 2개(도자기 머그, 아기 모자), `<!-- EXAMPLES:START/END -->`. 예시 A 끝맺음은 흔한 "보여 드릴게요" 대신 덜 흔한 문구로 바꿨다.

## 4. 코드 검사 (check_sentences 확장, 4단계 구현 명세)
**텍스트 형태.** `O(s)` = NFC + 연속 공백을 한 칸으로(정규식은 모두 O에서 돈다. 패턴의 ` ?`는 공백 선택). `N(s)` = NFC → 소문자 → `[\s\W_]` 제거(포함 여부 비교와 n-gram에만 씀). `MEMO` = raw_input과 각 seller_addition의 N 목록. `cited` = 문장 fact_ids가 가리키는 유효 fact quote들의 N(buyer_action fact는 quote 대신 convertible_to의 N). `stems(s)` = O의 어절에서 조사·어미 접미사(이에요|예요|입니다|습니다|합니다|했어요|었어요|았어요|해요|어요|아요|네요|거든요|더라고요|죠|요|에서|으로|로|에게|한테|까지|부터|처럼|보다|이랑|랑|하고|이나|은|는|이|가|을|를|에|의|도|만|와|과)를 긴 것부터 한 번 떼고 2음절 이상이면 앞 2음절. 불용 어간: 있어 없어 하는 하고 해서 같아 같은 그래 그런 이런 저런 저희 우리 정말 너무 조금 살짝 그냥 한번 이번 지금 오늘 그때 때문 그리 이렇 그렇. 어간 포함 비교는 N 기준.

**A. 근거 검사**
1. fact quote: N(quote)가 MEMO 하나의 부분 문자열 + 길이 ≥2 + **O 원문에서 양끝이 어절 경계**(공백·문장부호·문자열 끝, 조사 앞은 허용) + 원문에서 quote 바로 앞 어절이 `안|못|않|없|별로`가 아님 → 아니면 fact 버림.
2. 내용 겹침: 사실 문장(interpretation:false), **A4에 걸린 모든 문장**, 제목에 적용. 내용 어간 중 ≥1개가 cited에 있고, MEMO에 없는 어간은 **문장당 1개까지**이며 그 1개도 B 표·MATERIAL에 걸리지 않아야 한다 → 아니면 삭제(UNGROUNDED), 제목이면 재작성.
3. fact_ids: 무효 id는 떼고, 남은 id가 0개인 사실 문장 → 삭제(NO_FACT).
4. 판매자 장면·느낌 표지 `출근|퇴근|야근|새벽|시장에|작업|만들었|구웠|굽고|들여왔|고민|결정|다녀왔|더라고요|더라구요|더군요|저는|저도|제가|개인적으로` → **걸린 표지의 어간이 cited 또는 MEMO에 있어야** 통과, 아니면 삭제(SELLER_UNGROUNDED). interpretation 값과 무관하게 A2도 적용. `저희`는 말투라 제외.
5. buyer_action fact를 단 문장: `샀|뽑았|뽑혔|구매했|데려왔|구했`가 있으면 삭제(BUYER_RESTATE). 겹침은 convertible_to와만 본다.
6. 끝맺음 구조: is_ending은 마지막 문장 하나로 코드가 맞춘다. ending=info인데 cited에 how_to_buy/price가 없으면 그 문장 삭제.
7. 비율: 끝맺음 제외 본문 n문장, 감성 i개, i > max(1, n//3) → 재작성(RATIO). 끝맺음은 **type이 promise/greeting이고 B·SERVICE를 통과했을 때만** 비율에서 뺀다(그 밖이면 본문으로 셈, 확정). 사실 문장 0개 → 재작성(NO_FACT_BODY).
8. 제목: headline_fact_ids ≥1·유효 + A2 + B → 아니면 재작성.
9. product_card: name 어간이 모두 MEMO에 없으면 analysis.product.name으로 교체. price_display 금액이 메모 숫자 집합에 없으면 null.

**B. 금지 항목** (O에서 정규식, 면제 비교는 N. 제목·감성·권유·끝맺음 포함 모든 문장. 걸리면 삭제, 제목이면 재작성)
| 코드 | 탐지 (O) | 면제 |
|---|---|---|
| NUMBER | `\d[\d,.]*`(만·천·백 단위 파싱: "2만2천"=22000, "만원"=10000), 고유어 수+단위 `(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무) ?(개|번|가지|시간|일|주|달|개월|년|분|송이|단|명|살|배|잔)`, `%` | 값이 메모 숫자 집합에 있음. 관용 허용: `한 ?번|하나|한 ?입|한 ?잔|한 ?주|한 ?해|한 ?일|하루`(기간 뜻은 PERIOD가 봄) |
| PERIOD | `평생|영원히|오래 ?(가|간|유지|쓸|써|두)|하루|이틀|사흘|며칠|일주일|반나절|몇 ?(주|달|년)` + (`면|만에|동안|이상|넘게|지나`가 뒤따름) | 같은 어간이 cited에 |
| SERVICE | `포장|배송|택배|보내 ?드|예약|주문|구워 ?(둘|드|놓)|구울|들여 ?(둘|놓|올)|내일|다음 ?(주|달|번)|주말` | 같은 어간이 cited 또는 MEMO에. `보여|챙겨|알려 ?드` 약속은 대상 아님 |
| EXCLUSIVE | `(에서|으?로)만 ?(팔|판매|구할|살 수)|유일|한정|단독|오직|단 ?하나|하나뿐|마지막 ?(수량|하나|재고|기회|입고)|소량|희귀|구하기 ?(힘|어려)|품절 ?임박|곧 ?(품절|마감)|놓치` | cited에 `밖에|만|뿐|유일|한정|단독|마지막|오직` |
| EFFICACY | `효과|효능|개선|완화|치유|치료|예방|면역|해독|디톡스|숙면|미백|보습|진정|피부가|살 ?빠|건강해|건강에 좋|액운|액땜|재물운|금전운|운이 ?(좋아|트|들|올)|행운이 ?(와|찾|들)|이루어(져|집|진)|이뤄(져|집)|합격(하게|시켜)|대박|보장|무조건|반드시|틀림없이`; `막아|지켜`는 같은 문장에 `액|운|부정|나쁜 기운`이 있을 때만; `좋아져|나아져`는 `피부|몸|건강|컨디션`과 함께일 때만 | 일치 문자열 자체(N)가 cited에 있을 때만 |
| SOCIAL | `완판|품절|매진|소진|조기 ?마감|인기|베스트|입소문|재구매|재주문|단골|손님들?(이|께서|도)|많이들? ?(찾|사|고르|하|좋아|오)|후기|리뷰|사랑받|웨이팅|줄 ?서|팔렸|팔린|빨리 ?나가|다 ?나갔|금방 ?나가|동났|찾는 분(들)?이 많|추천받|손님 반응`; `다들`은 `좋아|찾|사|샀`과 함께일 때만 | 같은 앞 2음절이 cited에 |
| ORIGIN | `국내산|국산|수입|산지|직송|유기농|무농약|무첨가|천연|친환경|비건|인증(?!샷)|수상|특허|1등|1위|haccp|수제(?!비)|핸드메이드|100 ?%` | 같은 어간이 cited에. 수제/핸드메이드는 cited seller_scene에 `만들|떴|구웠|빚|직접|손으로` |
| MATERIAL | 조사 뗀 어절이 `원목|가죽|린넨|리넨|실크|캐시미어|스테인리스|도자|유리|실리콘|버터|생크림|우유|꿀|순금`을 포함, 또는 `면|울|은`과 **완전히 같음** | 같은 말이 MEMO에 |
| COMPARE | `제일|가장|최고|보다 ?(더|훨씬)|다른 \S+(와|과|랑|이랑)는? 달|남다른` | cited에 `제일|가장|최고|보다|다른` |
| PROPER | (a) 영문 2자 이상 단어가 MEMO에 없음 (b) 조사 뗀 3음절 이상 어절이 2음절 이상 접미사 `시장|백화점|공원|해변|해수욕장|마을|거리|호텔|대학교|축제|팝업|마켓`으로 끝나고 MEMO에 없음 (c) O에서 어절 전체가 `[가-힣]{2,3}(씨|작가|선생님)`(+조사), 예외 `마음씨|솜씨|맵시|아가씨|아저씨|글씨|말씨|불씨` (d) 따옴표 안 말이 MEMO에 없음 (e) 지명 목록: 서울 부산 대구 인천 광주 대전 울산 세종 강원 충북 충남 전북 전남 경북 경남 제주 성수 홍대 연남 을지로 익선동 망원 합정 이태원 한남 압구정 가로수길 북촌 서촌 해운대 광안리 전주 경주 강릉 속초 여수 통영 양양 가평 춘천 파리 도쿄 교토 뉴욕 | MEMO에 있음 |
- **남는 위험:** 목록 밖의 지명·인명·브랜드와 지어낸 사건이 interpretation 문장에 섞이면 런타임에서 못 잡는다. 오프라인 채점(reviewer.md)으로 추적한다.

**C. 기계 같은 글 신호** (제목+본문, O에서. 조사 6절 기준: H는 1개만 걸려도, S는 2개 이상 걸리면 재작성. 재작성 후에도 걸리면 로그만 남기고 내보냄)
| 등급·코드 | 규칙 |
|---|---|
| H CLICHE | writer.md 4절 상투어 목록에서 2개 이상(N 비교, 메모에 있는 말은 면제). `만나 ?보(세요|실)`는 어디서든 1회로 H |
| H ABSTRACT_REPEAT | `소중|특별|정성|감성` 중 하나가 2회 이상 |
| H CTA | 끝맺음이 `체험해 ?보세요|느껴 ?보세요|경험해 ?보세요`, 또는 마지막 두 문장에 권유 `보세요|셨다면|데려가|맛보|가세요|오세요`와 바람 `바랍니다|바라요|좋겠|되시길|하시길`이 함께 |
| H LESSON | `가 아니라 .*(이니까|니까|입니다|이에요)`, `동안 배운 건` |
| H PLEDGE | `제대로 ?(달려|가) ?보|화이팅|파이팅|최선을 다하|고객님의 의견` |
| S CLICHE_ONE | 상투어 목록 1개 |
| S STEM_REPEAT | 같은 어간 3회 이상(상품명·distinctive·불용 어간·메모에서 2회 이상 나온 어간 제외) |
| S SAME_LAST | 이어진 두 문장의 마지막 어절이 같음, 또는 끝 3음절이 3연속 같음, 또는 4문장 이상에서 `니다.` 비율 ≥80% |
| S LIST3 | 한 문장에 쉼표 구획 ≥3이고 가운데 구획이 2어절 이하, 또는 `\S+(와|과|랑|이랑) \S+(와|과|랑|이랑) \S+` |
| S PASSIVE | `준비되어 있|만나보실 수|제공됩니다|구성되어` |
| S DEDICATION | `(당신|분)을 위해 ?(준비|소개)` |
| S CONNECTIVE | `특히|또한|게다가|뿐만 아니라|을 통해` 합계 2회 이상 |
| 규칙 NO_ADDRESS | 전체에 `저희|드릴게요|드려요|드립니다|둘게요|셨다면|보세요|하세요|세요` 0회 → 재작성(승인 규칙) |
| 규칙 COPY_EXAMPLE | 예시 블록 `>` 줄에서 `[F…]`·`[감성]`·`[끝맺음…]`·`제목:`·`N문단:` 표기와 `/`를 뗀 뒤 N 7글자 n-gram − 예시 밖 프롬프트 n-gram − MEMO n-gram. 출력과 겹치면 재작성 |
| 자동 EMOJI | `[\U0001F000-\U0001FAFF☀-➿️]`, `#\S+` 제거(재작성 없음) |
- 코드에 없는 조사 신호: 감각어 쌓기(12), 구체 명사 없는 감정문(13), 시간 표지 0개(6)는 프롬프트로만 다룬다(6은 seller_scene 필수로 대부분 해소).

**D. 재작성 판단.** 1차 결과에서 제목 실패, RATIO, NO_FACT_BODY, 삭제 ≥2문장, H 1개 이상, S 2개 이상, NO_ADDRESS, COPY_EXAMPLE 중 하나 → 남은 시간이 18초 이상이면 재작성. 입력: raw_input, seller_additions, 정리된 analysis, `previous`, `rewrite_reasons[{code, sentence_index, detail}]`(detail은 API로만 보냄). 2차는 A·B 삭제와 자동 수정만.

**E. 마무리 정리(모든 경로의 마지막).** (1) 비율을 넘는 interpretation 문장을 끝맺음 바로 앞에서부터 지운다. (2) 사실 문장 0개면 NO_STORY_FOUND. (3) 제목이 여전히 실패하면 제목을 product_card.name으로 바꾸고 본문은 그대로 둔다(확정). (4) 빈 문단 제거, 문단 번호 정렬.

## 5. 로그와 개인정보
- 지운다: `headline_candidates:`·`removed_sentences:` print, `print("Claude API 오류:", error)`.
- 남긴다(요청당 한 줄 `lepi_run {...}`): 무작위 rid, model, mode, memo_len, additions 수, readiness, facts 수/버린 수, 문장 수, 삭제 코드별 개수, 신호 코드 목록, rewrite 여부·건너뛴 이유(time), 호출별 input/output/cache 토큰·ms·stop_reason, 오류는 `type(e).__name__`와 HTTP 상태. 메모·quote·문장·제목·질문·어간 문자열은 남기지 않는다.
- 해외 이전 자체는 엔진 범위 밖: 입력칸 아래 "입력 내용은 글 생성을 위해 Anthropic(미국)으로 전송됩니다" 한 줄을 넣는 쪽으로 법무 확인(검토 권고 8).
- 4단계에서 api의 `questions[:2]`, `conflicts` 분기, `source/source_type/product.facts` 읽기, 두 print를 함께 지운다.

## 6. 비용·시간 (캐시 미적중, 한글 1자≈1토큰 근사)
| 호출 | 입력 | 출력(JSON+low thinking) |
|---|---|---|
| Analyzer | ≈4,300 | ≈1,300 |
| Writer | ≈6,100 | ≈1,300 |
| 재작성 | ≈6,900 | ≈1,300 |
- 재작성률 20% 가정(조사 기준 H/S 등급으로 낮춤) → 평균 2.2회.
| MODEL | NEED_MORE_INFO(1회) | 평균(2.2회) | 최대(3회) |
|---|---|---|---|
| Opus 5.5 ($4/$20) | $0.043 ≈ 61원 | $0.103 ≈ 144원 | $0.149 ≈ 209원 |
| Sonnet 5.5 ($2/$10) | $0.022 ≈ 30원 | $0.052 ≈ 72원 | $0.075 ≈ 104원 |
- 시간: 기준선 2회 평균 14.2초·최대 19.6초 → v2 평균 ≈16초, 재작성 포함 ≈25~35초, 상한 42초(1절).
- 4단계에서 같은 13개 메모를 MODEL=Opus, MODEL=Sonnet으로 한 번씩 돌려 통과 수·시간·원가를 비교한다.

## 7. 검토 반영 (review.md 항목 → 위치)
| 항목 | 위치 |
|---|---|
| 1·2·4·5·7 근거 구멍 | 4-A4, 4-A2, 4-A1, 1절 정리(2)·analyzer 4·5절, 1절 정리(5)·4-A5 |
| 3·6·9 서비스·재료·고유명사 | 4-B SERVICE, MATERIAL, PROPER (e) + 남는 위험 |
| 8·21 마무리·끝맺음 구조 | 4-E, 4-A6 |
| 10~18 오탐·신호 기준 | 4-B 각 행, 4-C (H/S 등급, 반복 3회, LIST3 `하고` 삭제, 코드에 없는 신호 명시) |
| 19·20 정규식 형태·베끼기 | 4절 머리 O/N, 4-C COPY_EXAMPLE, 예시 A 끝맺음 교체 |
| 22·23·24 시간·스키마·정합 | 1절, 스키마 변경 없음, 1절 정리(3)·5절 |
| 열린 쟁점 | 1·3~6·8·10 권고대로. 9는 사용자 결정(전체 Opus vs 전체 Sonnet, MODEL 하나) |

## 8. 확정과 남은 결정
- **확정(사용자 결정 2026-10-28):** 끝맺음의 비율 제외는 promise/greeting이고 B·SERVICE를 통과할 때만(본문 3문장 글에서 감성이 끝맺음 포함 2/4까지 갈 수 있음을 인지). 2차에도 제목 실패 시 상품명을 제목으로 쓰고 본문은 유지.
- **남은 결정 1 — 보정 세트:** RULES.md·확정본이 없다. 사용자가 확정본을 다시 고를 때까지 조사의 사람 글 59개를 '걸리면 안 되는' 오탐 세트로 B·C 정규식을 먼저 보정한다(raw 원문은 엔진 파일에 옮기지 않고 테스트에서만 읽음).
- **남은 결정 2 — MODEL:** 전체 Opus vs 전체 Sonnet 비교 결과로 정한다.
- **남은 결정 3 — 해외 이전 고지 문구:** 법무 확인.

## 9. run1 반영 (score.md, 2026-10-28) — 이제 라이브 `engine/analyzer.md`·`writer.md`가 원본, `draft/`는 지난 판
| 실패 | 프롬프트 수정 |
|---|---|
| DEMO가 방문·구매 일기(밀짚·잉어킹·선운사) | analyzer: 방문·발견·갖고 싶던 이유·구매 = buyer_action, convertible_to로 손님 상황·구하는 방법·권유로 바꿈. 산 뒤 곁에 두고 겪은 일만 seller_scene. writer: DEMO 흐름 = 상품 → "저도" 겪은 일 → 구하는 방법·가격 → 끝맺음, 구매·방문담 금지 |
| 불확실·부정(머그컵 "그럴리가요") | analyzer: 정도?·미정·준비 중·의심을 quote에 함께 담거나 손님 말을 빼기, 처음 생각한 값은 가격 아님. writer: 그 표지를 살리고, 손님 말을 맛·효과 근거로 쓰지 않기, 미정·준비 중이면 권유 금지 |
| "저희 가게" 지어냄(반려돌) | writer: 메모에 가게·공방이 있을 때만. 말투 예시에서 "저희 가게" 삭제 |
| 권유형 끝(네일·작약·쌀뜨물) | writer·analyzer: ~해/들여/누려 보세요·맛보세요·시작하세요 = invite. promise·greeting에는 쓰지 않음. 인사는 손님 사정 짐작 금지 |
| 제목이 독자를 좁힘(무화과 "어르신들 사가시라고") | writer: 독자 = 일반 인스타 팔로워. 메모 속 손님층은 본문의 판매자 이유로만, 제목·첫 문장은 상품과 판매자 결정으로(메모가 그 층 전용이라 할 때만 예외). rubric 3절 감점 1줄. 따라 했거나 덜 공들인 듯한 동기(유행이라서·싸게·대충·남은 재료)는 빼거나 중립 사실로, 더 나은 동기를 지어내지 않음, 좋은 반전 이야기는 유지. 반려돌 "주워서 넣을 거"처럼 값이 아깝게 읽히는 조달·원가 문장도 뺌(처음 장면은 유지, 손님이 받는 것으로 채움, 엄선 등 지어내기 금지)(analyzer·writer, rubric 1절 감점) |
| 상품·가격 빠짐(선운사) | writer: 상품 사실 문장 필수, price fact 있으면 본문에도 한 번(예시 A에 가격 문장 추가) |
**코드 요청 (api/index.py 담당에게. 스키마 변경 없음)**
1. NO_PRODUCT_BODY: 마무리 정리에서 본문에 product.name_fact_id를 단 사실 문장이 없거나, price_fact_id가 있는데 그 fact를 단 문장이 없으면 재작성(2차면 로그만). 그 fact를 단 유일한 문장은 삭제 대신 재작성 사유로.
2. ENDING_INVITE: 끝맺음이 `(해|어|아|여|려|겨) ?보세요|맛보세요|데려가세요|들이세요|시작하세요|누리세요`면 analysis 유형과 상관없이 invite로 보고 비율에 넣는다. analysis가 promise/greeting인데 걸리면 S 신호.
3. SHOP_INVENT (B 표에 추가): `저희 ?(가게|매장|샵|숍|공방|떡집|꽃집|카페|빵집)`·`(가게|매장|공방)에서` → MEMO에 같은 명사가 없으면 삭제.
4. DEMO_BUYER: DEMO 모드의 모든 문장에서 `발견했|놀러 ?갔|간 김에|갖고 싶었|가지고 싶었|샀어|구매했|뽑았|뽑혔` → 삭제(A5를 cited와 무관하게 확장).
5. HEDGE: cited quote에 `\?|정도|쯤|같|미정|준비 ?중`이 있으면 문장에도 `정도|쯤|같|미정|준비|아마` 중 하나가 있어야 함, 아니면 삭제. MEMO에서 customer_fact quote 뒤 30자 안에 `그럴 ?리가|설마|글쎄`가 있으면 그 fact를 단 문장에 같은 말이 없을 때 삭제.
6. price_display 값은 price_fact quote의 금액과 같아야 함(메모 안 다른 금액, 예: 처음 생각한 값이면 null).

