from http.server import BaseHTTPRequestHandler
import json
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path

import anthropic


# 남용 상한. 이 엔드포인트는 페이지를 거치지 않고 직접 호출할 수 있으므로
# 프런트의 입력 제한만으로는 비용이 보호되지 않는다. 체험 한 번이 곧 Claude
# API 호출 두세 번(분석 + 작성 + 재작성)이라, 긴 글 한 번이 짧은 글 수십 번보다 비싸다.
# 레피는 짧은 상품 메모에 스토리를 입히는 도구다. 랜딩 사례의 메모가
# 100~300자 선이라 500자면 정상 사용에 지장이 없다.
MAX_TEXT_LENGTH = 500

# 한글은 UTF-8에서 글자당 3바이트다. 500자 = 1.5KB에 JSON 여유를 더한 값.
# 본문을 읽기 전에 막아야 큰 요청이 메모리에 올라오는 것을 방지할 수 있다.
MAX_BODY_BYTES = 8 * 1024

TOO_LONG_MESSAGE = "메모가 너무 깁니다. 500자 이내로 줄여 주세요."

# 사용자 결정(2026-10-29): 이야기 찾기(Analyzer)·글쓰기(Writer) 모두 Sonnet 5.5.
# 같은 메모 6개 비교에서 Writer Opus와 판정 점수가 같고(22.5 vs 22.7) 원가는 93원 → 38원, 시간은 18초 → 5초였다.
# LEPI_MODEL을 주면 두 단계 모두 그 모델을 쓴다(테스트 비교용).
MODEL = os.environ.get("LEPI_MODEL")
ANALYZER_MODEL = os.environ.get("LEPI_ANALYZER_MODEL") or MODEL or "claude-sonnet-5-5"
WRITER_MODEL = os.environ.get("LEPI_WRITER_MODEL") or MODEL or "claude-sonnet-5-5"

# thinking을 끌 수 없어서 effort로만 조절한다. 모델마다 기본값이 달라 늘 명시한다.
# 기본값은 Analyzer low, Writer medium. Writer는 품질 우선으로 medium(사용자 결정 2026-10-28).
ANALYZER_EFFORT = os.environ.get("LEPI_ANALYZER_EFFORT", "low")
WRITER_EFFORT = os.environ.get("LEPI_WRITER_EFFORT", "medium")

# 검사 방식. enforce = 지우기·다듬기·재작성·대체까지 적용. report = 검사는 모두 돌리되
# Writer 글을 그대로 내보내고 '했을 일'만 stats·로그에 남긴다(사용자 결정: 생성 먼저, 삭제는 나중).
# light = report에 더해, 메모 어디에도 없는 판매 사실(숫자·금액·기간·서비스·효능·실적·재료·원산지)과
# 원가·주운 물건 이야기가 든 문장만 지운다. 재작성은 하지 않는다(사용자 결정 2026-10-29: 아주 약하게).
CHECK_MODE = os.environ.get("LEPI_CHECK_MODE", "light")
LIGHT_CODES = {
    "NUMBER", "PERIOD", "SERVICE", "EXCLUSIVE", "EFFICACY", "SOCIAL",
    "MATERIAL", "ORIGIN", "SHOP_INVENT"
}
LIGHT_FOUND = re.compile(r"주워|주운|주웠")
# 제목에는 실패·불량으로 읽히는 말을 쓰지 않는다(사용자 결정 2026-10-29). 본문의 반전 이야기는 둔다.
HEADLINE_NEGATIVE = re.compile(r"망했|망친|망쳤|망한|실패|불량|하자가|하자 있|잘못 나온|흠집")

# 안전 분류기가 요청을 거절하면 서버가 알맞은 다른 모델로 다시 돌린다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


# ── Story Engine ──
# 프롬프트와 스키마의 원본은 engine/ 폴더다. 코드에 복사해 두지 않고
# 매번 파일에서 읽는다 — 원본이 둘이 되면 어느 쪽을 고쳐야 하는지 흐려진다.
# vercel.json의 @vercel/python 빌더는 프로젝트 폴더 전체를 상대 경로 그대로
# 함수에 담으므로(.git, node_modules, __pycache__ 등만 제외) engine/도 함께 간다.
# 체험판은 Analyzer → Writer(→ 조건부 재작성)만 쓰고 Reviewer는 채점 전용이다.
ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"


def _read_text(name):
    return (ENGINE_DIR / name).read_text(encoding="utf-8")


ANALYZER_PROMPT = _read_text("analyzer.md")
WRITER_PROMPT = _read_text("writer.md")


def _strip_array_bounds(schema):
    # Claude 구조화 출력은 배열 개수 제약(minItems 2 이상, maxItems)을 받지 않는다.
    # 스키마 파일은 설계 원본이라 그대로 두고, 보낼 때만 뺀다.
    # v2 스키마에는 개수 제약이 없지만 다시 생겨도 요청이 깨지지 않게 둔다.
    if isinstance(schema, dict):
        return {
            key: _strip_array_bounds(value)
            for key, value in schema.items()
            if key not in ("minItems", "maxItems")
        }
    if isinstance(schema, list):
        return [_strip_array_bounds(item) for item in schema]
    return schema


ANALYZER_SCHEMA = _strip_array_bounds(
    json.loads(_read_text("analyzer.schema.json"))
)
WRITER_SCHEMA = _strip_array_bounds(
    json.loads(_read_text("writer.schema.json"))
)

# 체험판 입력값은 고정이다. 랜딩에서 받는 건 메모 한 칸뿐이라
# 사진, 덧붙인 말, 상품 정보 입력이 없다.
SCENARIO_MODE = "REAL_SELLER"

# 테스트 모드(랜딩 주소 ?test)는 구매자로 쓴 메모를 판매자 글로 바꿔 본다.
# 방문자는 실제 판매자로 보고, 이 값이 올 때만 DEMO_SELLER로 돌린다.
SCENARIO_BY_MODE = {"demo": "DEMO_SELLER"}
# ── 시간과 호출 ──
# 페이지는 45초에 끊고 Vercel은 60초에 끊는다. 운영 기준은 요청 시작부터 42초, 호출당 25초.
# 테스트(run_tests.py)는 시간 때문에 결과가 잘리지 않게 크게 잡고, 운영 기준을 넘었는지만 기록한다.
PROD_DEADLINE_SECONDS = 42
PROD_CALL_TIMEOUT_SECONDS = 25
DEADLINE_SECONDS = float(os.environ.get("LEPI_DEADLINE_S", PROD_DEADLINE_SECONDS))
# 호출 하나가 마감 전체를 먹지 않게 한다. SDK 기본값(600초, 재시도 2회)은 쓰지 않는다.
# medium effort는 low보다 느려서 20초에서 25초로 올렸다.
CALL_TIMEOUT_SECONDS = float(os.environ.get("LEPI_CALL_TIMEOUT_S", PROD_CALL_TIMEOUT_SECONDS))
# 재작성 한 번에 10~18초가 든다. 이보다 적게 남으면 1차 결과를 정리해 내보낸다.
REWRITE_MIN_SECONDS = 18
# 가격·판매 방법·기간 fact가 통째로 지워졌으면 이 정도만 남아도 재작성한다.
# 이때는 출력을 줄여 시간 안에 끝나게 한다(run1 재작성 출력은 최대 약 1,100토큰).
REWRITE_LOST_FACT_SECONDS = 14
REWRITE_LOST_FACT_MAX_TOKENS = 2500
# 이보다 적게 남으면 호출해도 끝나지 않으니 부르지 않는다.
MIN_CALL_SECONDS = 3
MAX_TOKENS = 6000

# seller_scene이 없을 때 쓰는 고정 질문. Analyzer 질문이 비었을 때도 쓴다.
FIXED_QUESTION = "이 상품을 만들거나 고르면서 직접 하신 일을 한 줄로 알려 주세요."


def _usage_of(response):
    usage = getattr(response, "usage", None)
    return {
        "in": getattr(usage, "input_tokens", 0) or 0,
        "out": getattr(usage, "output_tokens", 0) or 0,
        "cache_w": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_r": getattr(usage, "cache_read_input_tokens", 0) or 0
    }


def call_structured(client, instructions, user_input, name, schema, deadline, stats,
                    max_tokens=MAX_TOKENS, effort=None, model=None):
    remaining = deadline - time.monotonic()
    if remaining < MIN_CALL_SECONDS:
        raise TimeoutError(f"{name}: 남은 시간이 없습니다.")

    call = {"name": name}
    stats.setdefault("calls", []).append(call)
    started = time.monotonic()
    try:
        response = client.with_options(
            timeout=min(CALL_TIMEOUT_SECONDS, remaining),
            max_retries=0
        ).beta.messages.create(
            model=model or WRITER_MODEL,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            # 시스템 프롬프트는 매번 같으므로 캐시해 둔다.
            system=[{
                "type": "text",
                "text": instructions,
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[{
                "role": "user",
                "content": json.dumps(user_input, ensure_ascii=False)
            }],
            output_config={
                # Sonnet은 기본 effort가 달라서 두 모델 모두 명시한다.
                "effort": effort or WRITER_EFFORT,
                "format": {"type": "json_schema", "schema": schema}
            }
        )
    except Exception as error:
        call.update(_error_info(error))
        if isinstance(error, (anthropic.APITimeoutError, TimeoutError)):
            stats["timeouts"] = stats.get("timeouts", 0) + 1
        raise
    finally:
        call["ms"] = int((time.monotonic() - started) * 1000)
        # 운영 호출 상한을 넘었는지(테스트에서 상한을 늘렸을 때 확인용).
        if call["ms"] > PROD_CALL_TIMEOUT_SECONDS * 1000:
            call["over_prod"] = True

    call.update(_usage_of(response))
    call["stop"] = response.stop_reason
    # fallback으로 다른 모델이 답했을 수 있다.
    call["served"] = getattr(response, "model", None)

    # 거절되거나 잘리면 출력이 스키마를 따르지 않을 수 있다.
    if response.stop_reason in ("refusal", "max_tokens"):
        raise ValueError(f"{name} 응답이 끝나지 않았습니다: {response.stop_reason}")

    # thinking 블록이 앞에 올 수 있으니 text 블록만 읽는다.
    output_text = next(
        (block.text for block in response.content if block.type == "text"),
        ""
    )

    # 모델 출력의 JSON 오류를 요청 JSON 오류(400)와 섞지 않는다.
    # 아래 핸들러는 JSONDecodeError를 사용자의 잘못된 요청으로 안내한다.
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} 출력이 JSON이 아닙니다.") from error


def _error_info(error):
    # 로그에는 오류 종류와 HTTP 상태만 남긴다. 메시지에 입력이 섞일 수 있다.
    return {
        "error": type(error).__name__,
        "status": getattr(error, "status_code", None)
    }


# ── 텍스트 형태 (설계 4절 머리) ──
# O: 정규식이 도는 원문 형태. N: 포함 비교와 n-gram에만 쓰는 형태.
def _O(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


# 메모와 Writer가 같은 말을 다르게 적는 경우. 비교 전에 한쪽으로 모은다.
# (run1 머그컵: 메모 "전자렌지 식세기" ↔ 문장 "전자레인지와 식세기")
SPELLING_VARIANTS = [
    ("전자렌지", "전자레인지"), ("전자랜지", "전자레인지"), ("식세기", "식기세척기"),
    ("이쁘", "예쁘"), ("이뻐", "예뻐"), ("이뻤", "예뻤"), ("첨엔", "처음엔"), ("첨에", "처음에")
]


def _N(text, canon=True):
    text = re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFC", text or "").lower())
    if canon:
        for variant, standard in SPELLING_VARIANTS:
            text = text.replace(variant, standard)
    return text


# 조사·어미. 긴 것부터 한 번만 뗀다. 연결어미(서·지·고 등)는 설계 목록에
# 없지만, 없으면 "떠서·따갑지" 같은 활용형이 전부 메모 밖 어간으로 잡혀
# 근거 있는 문장까지 지워진다(보정 결과, engine/tests/calibration.md).
SUFFIXES = sorted(
    "이에요 예요 입니다 습니다 합니다 했어요 었어요 았어요 해요 어요 아요 네요 "
    "거든요 더라고요 죠 요 에서 으로 로 에게 한테 까지 부터 처럼 보다 이랑 랑 "
    "하고 이나 은 는 이 가 을 를 에 의 도 만 와 과 "
    "어서 아서 해서 면서 으면 니까 는데 지만 지 서 고 "
    "이고 이라서 이라 이니까 이니 인데 이지만 니다 세요 으세요 께서".split(),
    key=len,
    reverse=True
)

STOP_STEMS = set(
    "있어 없어 하는 하고 해서 같아 같은 그래 그런 이런 저런 저희 우리 정말 너무 "
    "조금 살짝 그냥 한번 이번 지금 오늘 그때 때문 그리 이렇 그렇".split()
) | set(
    # 말 건네는 보조 용언. 메모에 없어도 내용이 아니다(보정에서 추가).
    "않아 않은 않게 않는 드릴 드려 드립 드리 보세 보시 하세 주세 있는 있고 있게 "
    "있을 있었 됐어 되어 되는 거예 거에 "
    # "하다"의 활용형은 내용어가 아니다.
    "하니 하면 하려 해야 했어 했는 하던 하지 해도 해서 하게 "
    # 지시어·부사·보조 표현. run1에서 근거 있는 문장을 지운 원인이었다.
    "거기 여기 저기 그거 이거 저거 모두 어느 그러 보니 테니 되실 됩니 될거 알게 "
    "솔직 언제 계속 바로 함께 같이 생각 가세 오세 "
    # 설계가 말투로 허용한 약속 동사(보여·챙겨·알려 드릴게요).
    "보여 챙겨 알려 되면".split()
)


def _strip_suffix(word):
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix):
            return word[:-len(suffix)]
    return word


def _words(text):
    # O의 어절을 N으로. 문장부호만 있는 어절은 버린다.
    return [w for w in (_N(part) for part in _O(text).split(" ")) if w]


def _stems(text):
    stems = []
    for word in _words(text):
        base = _strip_suffix(word)
        if len(base) >= 2:
            stem = base[:2]
            if stem not in STOP_STEMS:
                stems.append(stem)
    return stems


def _jamo(char):
    code = ord(char) - 0xAC00
    if 0 <= code < 11172:
        return code // 588, (code % 588) // 28
    return None


def _stem_in(stem, texts):
    """어간이 N 텍스트들 중 하나에 있는가.

    둘째 음절은 첫소리만 본다. "따갑"과 "따가워", "만들"과 "만드는",
    "돌렸"과 "돌린"처럼 활용으로 모음·받침이 바뀌어도 같은 어간으로 친다
    (스모크 테스트에서 근거 있는 사실 문장이 지워져 넓혔다).
    """
    second = _jamo(stem[1])[0] if len(stem) == 2 and _jamo(stem[1]) else None
    for text in texts:
        if stem in text:
            return True
        if second is None:
            continue
        index = text.find(stem[0])
        while index != -1:
            following = _jamo(text[index + 1]) if index + 1 < len(text) else None
            if following and following[0] == second:
                return True
            index = text.find(stem[0], index + 1)
    return False


def _contains(needle, texts):
    return bool(needle) and any(needle in text for text in texts)


# ── 숫자 ──
NUM_RUN = re.compile(
    r"\d[\d,.]*(?:\s?[만천백](?:\s?\d[\d,.]*)?)*|(?<![가-힣\d])만\s?원"
)


def _num_value(run):
    total = 0.0
    current = None
    for token in re.findall(r"\d[\d,.]*|[만천백]", run):
        if token[0].isdigit():
            try:
                current = float(token.replace(",", "").rstrip("."))
            except ValueError:
                current = None
        else:
            unit = {"만": 10000, "천": 1000, "백": 100}[token]
            total += (current if current is not None else 1) * unit
            current = None
    if current is not None:
        total += current
    return total


def _numbers(text):
    values = set()
    for match in NUM_RUN.finditer(text or ""):
        values.add(_num_value(match.group()))
        # "2만2천"의 2처럼 덩어리 안의 숫자도 메모 숫자로 본다.
        for digits in re.findall(r"\d[\d,.]*", match.group()):
            values.add(_num_value(digits))
    return values


NATIVE_VALUES = {
    "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7,
    "여덟": 8, "아홉": 9, "열": 10, "스무": 20
}
# 단위 뒤에 다른 낱말이 붙으면("한 단계", "세일해요") 수 표현이 아니다.
NATIVE_NUMBER = re.compile(
    r"(?<![가-힣])(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무) ?"
    r"(개월|개|번|가지|시간|일|주|달|년|분|송이|단|명|살|배|잔)"
    r"(?![^\s\W이가을를은는도만에의씩째쯤짜와과랑부께로요])"
)
NATIVE_IDIOM = re.compile(r"^(한 ?번|한 ?입|한 ?잔|한 ?주|한 ?해|한 ?일)$")
NATIVE_SKIP = {"세일", "열일"}


# ── B. 금지 항목 정규식 (O에서) ──
PERIOD_ALWAYS = re.compile(
    r"평생|영원히|오래 ?(?:가(?!만)|간(?!만)|유지|쓸|써|두)"
)
PERIOD_SPAN = re.compile(
    r"(?:하루|이틀|사흘|며칠|일주일|반나절|몇 ?(?:주|달|년)) ?"
    r"(?:이?면|만에|동안|이상|넘게|지나|정도면)"
)
SERVICE = re.compile(
    r"포장|배송|택배|보내 ?드|예약|주문|구워 ?(?:둘|드|놓)|구울|들여 ?(?:둘|놓|올)"
    r"|내일|다음 ?(?:주|달|번)|주말"
)
EXCLUSIVE = re.compile(
    r"(?:에서|서|으?로)만 ?(?:팔|판매|구할|살 수)|유일|한정|단독|오직|단 ?하나|하나뿐"
    r"|마지막 ?(?:수량|하나|재고|기회|입고)|소량|희귀|구하기 ?(?:힘|어려)"
    r"|품절 ?임박|곧 ?(?:품절|마감)|놓치"
)
# 설계의 면제어 `만`은 "만원·만들"에도 걸려 사실상 늘 면제가 된다.
# 한정의 뜻일 때(조사 뒤의 만)만 본다.
EXCLUSIVE_CITED = re.compile(
    r"밖에|뿐|유일|한정|단독|마지막|오직|(?:에서|서|으?로|에게|에)만(?![들드])"
)
EFFICACY = re.compile(
    r"효과|효능|개선|완화|치유|치료|예방|면역|해독|디톡스|숙면|미백|보습"
    r"|진정(?!한|성|으로|히)|피부가|살 ?빠|건강해|건강에 좋|액운|액땜|재물운|금전운"
    r"|운이 ?(?:좋아|트|들|올)|행운이 ?(?:와|찾|들)"
    # "~로 이루어진 세트"는 구성이라 뺀다.
    r"|(?<!로 )(?<!로)이루어(?:져|집|진)|(?<!로 )(?<!로)이뤄(?:져|집)"
    r"|합격(?:하게|시켜)|대박|보장|무조건|반드시|틀림없이"
)
EFFICACY_GUARD = re.compile(r"막아|지켜")
EFFICACY_GUARD_CONTEXT = re.compile(
    r"액(?:운|땜|막)|기운|(?<![가-힣])운(?:이|을|세)?(?![가-힣])|부정|나쁜"
)
EFFICACY_BODY = re.compile(r"좋아져|나아져")
EFFICACY_BODY_CONTEXT = re.compile(r"피부|몸|건강|컨디션")
SOCIAL = re.compile(
    r"완판|품절|매진|소진|조기 ?마감|인기|베스트|입소문|재구매|재주문|단골"
    r"|손님들?(?:이|께서|도)|많이들? ?(?:찾|사(?!랑)|고르|하|좋아|오)|후기|리뷰|사랑받"
    r"|웨이팅|줄 ?서|팔렸|팔린|빨리 ?나가|다 ?나갔|금방 ?나가|동났"
    r"|찾는 분(?:들)?이 많|추천받|손님 반응"
)
SOCIAL_ALL = re.compile(r"다들.*(?:좋아|찾|샀|사(?:가|요|세|셨|시|러))")
ORIGIN = re.compile(
    r"국내산|국산|수입|산지|직송|유기농|무농약|무첨가|천연|친환경|비건|인증(?!샷)"
    r"|수상(?!한|하|해)|특허|(?<!\d)1등|(?<!\d)1위|haccp|수제(?!비)|핸드메이드"
    r"|(?<!\d)100 ?(?:%|프로)",
    re.I
)
HANDMADE_SCENE = re.compile(r"만들|떴|구웠|빚|직접|손으로")
MATERIAL = re.compile(
    r"원목|가죽|린넨|리넨|실크|캐시미어|스테인리스|도자|유리(?!하|한|해)|실리콘"
    r"|버터|생크림|우유|꿀(?!팁|잠|조합|벌)|순금"
)
MATERIAL_EXACT = {"면", "울", "은"}
# 맛·식감·향 단정. 상품명 상식 문장이 "쫀득한 식감"처럼 판매 정보를 지어내지 않게 한다.
TASTE = re.compile(
    r"쫀득|쫄깃|촉촉|바삭|폭신|말랑|꾸덕|달콤|새콤|고소|향긋|식감|풍미|육즙|진한 ?맛|감칠맛"
)
COMPARE = re.compile(
    r"제일|가장|최고|보다 ?(?:더|훨씬)|다른 \S+(?:와|과|랑|이랑)는? 달|남다른"
)
COMPARE_CITED = re.compile(r"제일|가장|최고|보다|다른")
PLACE_SUFFIX = re.compile(
    r"(?:시장|백화점|공원|해변|해수욕장|마을|거리|호텔|대학교|축제|팝업|마켓)$"
)
PLACE_SUFFIX_SKIP = re.compile(r"(?:볼|먹|놀|살|즐길|읽을|이야깃|걱정|일|반찬|고민|웃음)거리$")
NAME_TITLE = re.compile(r"([가-힣]{2,3})(씨|작가|선생님)")
NAME_TITLE_SKIP = ("마음씨", "솜씨", "맵시", "아가씨", "아저씨", "글씨", "말씨", "불씨", "날씨", "꽃씨", "볍씨")
QUOTED = re.compile(r"[\"“]([^\"”]+)[\"”]|[‘']([^’']+)[’']")
PLACES = set(
    "서울 부산 대구 인천 광주 대전 울산 세종 강원 충북 충남 전북 전남 경북 경남 제주 "
    "성수 홍대 연남 을지로 익선동 망원 합정 이태원 한남 압구정 가로수길 북촌 서촌 해운대 "
    "광안리 전주 경주 강릉 속초 여수 통영 양양 가평 춘천 파리 도쿄 교토 뉴욕".split()
)

# 판매자 장면·느낌 표지(A4)와, 통과에 필요한 어간
SELLER_MARKER = re.compile(
    r"출근|퇴근|야근|새벽|시장에|작업|만들었|구웠|굽고|들여왔|고민|결정|다녀왔"
    r"|더라고요|더라구요|더군요|저는|저도|제가|개인적으로"
)
FIRST_PERSON = ["저는", "저도", "제가", "저한테", "나는", "나도", "내가"]
MARKER_STEMS = {
    "시장에": ["시장"],
    "만들었": ["만들", "만드"],
    "구웠": ["구워", "구웠", "굽"],
    "굽고": ["구워", "구웠", "굽"],
    "들여왔": ["들여", "들였", "들어오", "들어왔"],
    "다녀왔": ["다녀"],
    "개인적으로": ["개인적"],
    "저는": FIRST_PERSON,
    "저도": FIRST_PERSON,
    "제가": FIRST_PERSON
}
RECALL_ENDINGS = ("더라고요", "더라구요", "더군요")
BUYER_RESTATE = re.compile(r"샀|뽑았|뽑혔|구매했|데려왔|구했")


# 메모가 어림으로 적은 수("350정도?")는 문장에서도 어림말과 함께 써야 한다.
HEDGED_NUMBER = re.compile(
    r"(?:약|대략) ?(" + NUM_RUN.pattern + r")|(" + NUM_RUN.pattern + r") ?(?:정도|쯤|가량|내외|남짓|\?)"
)
HEDGE_WORD = re.compile(r"정도|쯤|약|가량|대략|내외|남짓|아마|\?")
# 설계 9절 HEDGE: 근거 quote의 어림·미정 표지는 문장에도 남아야 한다.
# `같`은 quote 끝의 짐작("~같아요")만 본다. "물방울 맺힌거같고"·"쥐꼬리 같은지"는
# 비유라 표지가 아니다(run1 머그컵 재검사에서 감성 문장이 지워졌다).
HEDGE_IN_QUOTE = re.compile(r"\?|정도|쯤|미정|준비 ?중|같(?:아요|아|다|네요|더라)\W*$")
HEDGE_IN_SENTENCE = re.compile(r"정도|쯤|같|미정|준비|아마|\?")
# 메모가 스스로 의심한 말("그럴리가요")은 문장에도 그 의심이 있어야 한다.
DOUBT = re.compile(r"그럴 ?리가?|설마|글쎄")
# 설계 9절 SHOP_INVENT: 메모에 없는 가게를 지어내지 않는다(run1 반려돌: 회사원 메모).
SHOP_INVENT = re.compile(
    r"저희 ?(가게|매장|샵|숍|공방|떡집|꽃집|카페|빵집)|(?<![가-힣])(가게|매장|공방)에서"
)
# 설계 9절 DEMO_BUYER: DEMO 글에서 구매·방문담은 근거와 상관없이 지운다.
DEMO_BUYER = re.compile(
    r"발견했|놀러 ?갔|간 김에|갖고 싶었|가지고 싶었|샀어|구매했|뽑았|뽑혔"
)


# 상품을 싸게·공짜로 얻었다는 말은 메모에 있어도 손님에게 보이지 않는다(사용자 결정).
COST_LOW = re.compile(r"공짜|무료로 ?(?:얻|받|구)|싸게 ?(?:떼|구|샀|들여)|원가|남은 재료")
# "주운 돌"처럼 상품이 주워 온 물건이라는 말. 상품을 가리키는 문장·제목에서만 본다:
# 상품명·상품 fact를 단 문장, 또는 이 말이 든 fact를 단 문장(메모가 그 상품을 주웠다고 한 것).
COST_LOW_FOUND = re.compile(r"주워|주운|주웠|데려온|가져온")


def _memo_context(raw_input, seller_additions, scenario_mode=SCENARIO_MODE):
    texts = [raw_input, *seller_additions]
    hedged = set()
    for text in texts:
        for match in HEDGED_NUMBER.finditer(text or ""):
            hedged.add(_num_value(match.group(1) or match.group(2)))
    return {
        "o": [_O(text) for text in texts],
        "n": [_N(text) for text in texts],
        "nums": set().union(*(_numbers(text) for text in texts)),
        "hedged": hedged,
        "mode": scenario_mode,
        # clean_analysis가 채운다. 어림·의심 표지를 문장에 남겨야 하는 fact.
        "hedge_ids": set(),
        "doubt_ids": set()
    }


def check_banned(text, cited, memo, cited_scene=()):
    """B 표. 걸린 (코드, 일치 문자열) 목록을 돌려준다.

    cited: 문장이 단 fact들의 N 목록. memo: _memo_context 결과.
    cited_scene: cited 중 seller_scene fact의 N 목록(수제·핸드메이드 면제용).
    """
    o_text = _O(text)
    hits = []
    known = list(cited) + memo["n"]

    for match in NUM_RUN.finditer(o_text):
        value = _num_value(match.group())
        if value not in memo["nums"]:
            hits.append(("NUMBER", match.group()))
        elif value in memo.get("hedged", ()) and not HEDGE_WORD.search(o_text):
            # 메모의 "350정도?"를 "350"으로 단정하지 않는다.
            hits.append(("HEDGE", match.group()))
    for match in NATIVE_NUMBER.finditer(o_text):
        phrase = match.group()
        if NATIVE_IDIOM.match(phrase) or _N(phrase) in NATIVE_SKIP:
            continue
        if NATIVE_VALUES[match.group(1)] in memo["nums"] or _contains(_N(phrase), memo["n"]):
            continue
        hits.append(("NUMBER", phrase))

    for match in [*PERIOD_ALWAYS.finditer(o_text), *PERIOD_SPAN.finditer(o_text)]:
        if not _stem_in(_N(match.group())[:2], cited):
            hits.append(("PERIOD", match.group()))

    for match in SERVICE.finditer(o_text):
        if not _stem_in(_N(match.group())[:2], known):
            hits.append(("SERVICE", match.group()))

    match = EXCLUSIVE.search(o_text)
    # 메모에 같은 말("소량")이 있으면 지어낸 말이 아니다.
    if match and not _contains(_N(match.group()), cited) and not any(
        EXCLUSIVE_CITED.search(c) for c in cited
    ):
        hits.append(("EXCLUSIVE", match.group()))

    efficacy = list(EFFICACY.finditer(o_text))
    if EFFICACY_GUARD_CONTEXT.search(o_text):
        efficacy += list(EFFICACY_GUARD.finditer(o_text))
    if EFFICACY_BODY_CONTEXT.search(o_text):
        efficacy += list(EFFICACY_BODY.finditer(o_text))
    for match in efficacy:
        if not _contains(_N(match.group()), cited):
            hits.append(("EFFICACY", match.group()))

    social = list(SOCIAL.finditer(o_text)) + list(SOCIAL_ALL.finditer(o_text))
    for match in social:
        if not _stem_in(_N(match.group())[:2], cited):
            hits.append(("SOCIAL", match.group()))

    for match in ORIGIN.finditer(o_text):
        word = match.group()
        if _N(word) in ("수제", "핸드메이드"):
            if any(HANDMADE_SCENE.search(c) for c in cited_scene):
                continue
        if not _stem_in(_N(word)[:2], cited):
            hits.append(("ORIGIN", word))

    for word in _words(o_text):
        base = _strip_suffix(word)
        match = MATERIAL.search(base)
        material = match.group() if match else (base if base in MATERIAL_EXACT else None)
        if material and not _contains(material, memo["n"]):
            hits.append(("MATERIAL", material))

    for match in TASTE.finditer(o_text):
        if not _stem_in(_N(match.group())[:2], known):
            hits.append(("TASTE", match.group()))

    match = COMPARE.search(o_text)
    if match and not any(COMPARE_CITED.search(c) for c in cited):
        hits.append(("COMPARE", match.group()))

    for match in SHOP_INVENT.finditer(o_text):
        if not _contains(_N(match.group(1) or match.group(2)), memo["n"]):
            hits.append(("SHOP_INVENT", match.group()))

    for name in _proper_nouns(o_text):
        if not _contains(_N(name), memo["n"]):
            hits.append(("PROPER", name))

    return hits


def _proper_nouns(o_text):
    found = re.findall(r"[A-Za-z]{2,}", o_text)
    for raw_word in o_text.split(" "):
        word = _N(raw_word)
        if not word:
            continue
        base = _strip_suffix(word)
        if len(base) >= 3 and PLACE_SUFFIX.search(base) and not PLACE_SUFFIX_SKIP.search(base):
            found.append(base)
        # 어절 전체가 "이름+씨/작가/선생님(+조사)"일 때만 본다.
        title = NAME_TITLE.fullmatch(base) or NAME_TITLE.fullmatch(word)
        if title and not word.endswith(NAME_TITLE_SKIP) and not base.endswith(NAME_TITLE_SKIP):
            found.append(title.group())
        for place in PLACES:
            if base == place or (base.startswith(place) and base[len(place):] in ("시", "역", "점", "도", "동")):
                found.append(place)
    for match in QUOTED.finditer(o_text):
        found.append(match.group(1) or match.group(2))
    return found


# 감성 문장에서 판매자 표지로 보는 것: 구체적 행동·회상·1인칭. "고민·결정"은
# "어떤 이름을 붙여 줄지 고민하는 시간"처럼 손님 장면에도 쓰여 감성 문장에서는 뺀다.
SELLER_ACTION = re.compile(
    r"출근|퇴근|야근|새벽|시장에|작업|만들었|구웠|굽고|들여왔|다녀왔"
    r"|더라고요|더라구요|더군요|저는|저도|제가|개인적으로"
)
# 손님이 주어인 장면(높임 "-시-", 손님에게 하는 말). 1인칭이 없으면 판매자 표지를 보지 않는다.
CUSTOMER_SCENE = re.compile(r"[가-힣]실 |[가-힣]시는|[가-힣]시면|[가-힣]셔서|세요|손님|고객")
FIRST_PERSON_TEXT = re.compile(r"저는|저도|제가|저희|제 ")


def _seller_markers_apply(o_text, is_fact):
    if is_fact:
        return bool(SELLER_MARKER.search(o_text))
    if CUSTOMER_SCENE.search(o_text) and not FIRST_PERSON_TEXT.search(o_text):
        return False
    return bool(SELLER_ACTION.search(o_text))


def _seller_ungrounded(o_text, cited, memo, kinds=(), is_fact=True):
    if not _seller_markers_apply(o_text, is_fact):
        return None
    known = list(cited) + memo["n"]
    for match in (SELLER_MARKER if is_fact else SELLER_ACTION).finditer(o_text):
        marker = match.group()
        # 1인칭 대명사는 말투일 뿐 내용이 없다. 판매자 fact를 단 문장이면 통과시키고
        # 내용은 A2가 본다(메모가 "직접 주워서"처럼 주어 없이 쓰여도 지우지 않게).
        if marker in ("저는", "저도", "제가") and kinds & {"seller_scene", "seller_feeling"}:
            continue
        if marker in RECALL_ENDINGS:
            # 판매자 fact를 단 문장의 회상 어미는 말투다. 내용은 A2가 본다.
            if kinds & {"seller_scene", "seller_feeling"}:
                continue
            # "예쁘더라고요"면 앞말 "예쁘"가, "좋더라고요"면 "좋"이 근거에 있어야 한다.
            start = o_text.rfind(" ", 0, match.start()) + 1
            prefix = _N(o_text[start:match.start()])
            if (len(prefix) >= 2 and _stem_in(prefix[:2], known)) or (
                len(prefix) == 1 and _contains(prefix, cited)
            ) or _contains("더라", memo["n"]):
                continue
            return marker
        if not any(_stem_in(stem, known) if len(stem) == 2 else _contains(stem, known)
                   for stem in MARKER_STEMS.get(marker, [marker])):
            return marker
    return None


def _ungrounded(text, cited, memo, allowance=1):
    """A2. 내용 어간이 cited에 하나 이상, 메모 밖 어간은 allowance개까지(그것도 B 불가).

    allowance는 상품명 상식 문장(상품 fact를 달고 상품명을 쓴 문장)에서만 3이다.
    """
    stems = _stems(text)
    if not any(_stem_in(stem, cited) for stem in stems):
        return "cited 어간 없음"
    known = list(cited) + memo["n"]
    outside = [stem for stem in stems if not _stem_in(stem, known)]
    if len(outside) > allowance:
        return "메모 밖 어간 " + str(len(outside))
    for stem in outside:
        for word in _words(text):
            if word.startswith(stem) and check_banned(word, [], {"n": [], "nums": memo["nums"]}):
                return "메모 밖 어간이 금지 항목"
    return None


# 메모 밖 4음절 이상 명사는 고유명사로 본다("갸라도스"). 상품명 상식 문장에만 쓴다.
# 활용 어미로 끝나는 말("돌아다니며")은 빼고, 남는 위험(크리스마스 같은 일반어)은 문서에 둔다.
# 용언 어간으로 끝나는 말("들여다보는"→"들여다보")도 뺀다(run1 머그컵 재검사).
LONG_WORD_VERBAL_END = re.compile(r"[며면던을는은게지다요니까서도해했한할된될운보하되주내르]$")


def _unknown_long_words(text, memo):
    found = []
    for word in _words(text):
        base = _strip_suffix(word)
        if (
            re.fullmatch(r"[가-힣]{4,}", base)
            and not LONG_WORD_VERBAL_END.search(base)
            and not _contains(base, memo["n"])
        ):
            found.append(base)
    return found


# ── C. 기계 같은 글 신호 ──
def _cliche_patterns(prompt):
    line = next(
        (l for l in prompt.splitlines() if l.startswith("- 상투어:")),
        ""
    )
    items = [item.strip() for item in line.split(":", 1)[-1].split(",") if item.strip()]
    # "일상에 ~을 더하는"은 앞뒤 조각이 차례로 나오면 걸린다.
    return [
        (item, [_N(part.lstrip("을를")) for part in item.split("~")])
        for item in items
    ]


CLICHES = _cliche_patterns(WRITER_PROMPT)
MEET_CTA = re.compile(r"만나 ?보(?:세요|실)")
ABSTRACT = re.compile(r"소중|특별|정성|감성")
CTA_END = re.compile(r"체험해 ?보세요|느껴 ?보세요|경험해 ?보세요")
CTA_INVITE = re.compile(r"보세요|셨다면|데려가|맛보|가세요|오세요")
CTA_WISH = re.compile(r"바랍니다|바라요|좋겠|되시길|하시길")
LESSON = re.compile(r"가 아니라 .*(?:이니까|니까|입니다|이에요)|동안 배운 건")
PLEDGE = re.compile(r"제대로 ?(?:달려|가) ?보|화이팅|파이팅|최선을 다하|고객님의 의견")
PASSIVE = re.compile(r"준비되어 있|만나보실 수|제공됩니다|구성되어")
DEDICATION = re.compile(r"(?:당신|분)을 위해 ?(?:준비|소개)")
CONNECTIVE = re.compile(r"특히|또한|게다가|뿐만 아니라|[을를] 통해")
LIST_PAIR = re.compile(r"\S+(?:와|과|랑|이랑) \S+(?:와|과|랑|이랑) \S+")
ADDRESS = re.compile(
    r"저희|드릴게요|드려요|드립니다|둘게요|셨다면|보세요|하세요|세요|실 ?거예요|실 수 있|주세요"
    r"|셔도 (?:좋|돼)"
)
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️]|#\S+")


def _ngrams(text, size=7):
    return {text[i:i + size] for i in range(len(text) - size + 1)}


def _example_ngrams(prompt):
    # 예시 블록의 `>` 줄에서 표기를 뗀 7글자 n-gram − 예시 밖 프롬프트의 n-gram.
    start, end = "<!-- EXAMPLES:START -->", "<!-- EXAMPLES:END -->"
    if start not in prompt or end not in prompt:
        return set()
    head, rest = prompt.split(start, 1)
    block, tail = rest.split(end, 1)
    example = set()
    for line in block.splitlines():
        if not line.startswith(">"):
            continue
        line = re.sub(r"\[[^\]]*\]|제목:|\d+문단:|/", " ", line[1:])
        example |= _ngrams(_N(line))
    return example - _ngrams(_N(head + tail))


EXAMPLE_NGRAMS = _example_ngrams(WRITER_PROMPT)


def machine_signals(texts, memo, keep_stems=()):
    """C 표. texts = [제목, 본문 문장...]. (등급, 코드) 목록을 돌려준다."""
    hits = []
    sentences = [_O(t) for t in texts if _O(t)]
    whole = " ".join(sentences)
    whole_n = _N(whole)

    matched = []
    for item, parts in CLICHES:
        pattern = ".*?".join(re.escape(p) for p in parts if p)
        if pattern and re.search(pattern, whole_n) and not _contains(_N(item), memo["n"]):
            matched.append(_N(item))
    # "특별한 순간"이 "특별한"까지 두 번 세지 않게 한다.
    matched = [m for m in matched if not any(m != o and m in o for o in matched)]
    if len(matched) >= 2 or MEET_CTA.search(whole):
        hits.append(("H", "CLICHE"))
    elif len(matched) == 1:
        hits.append(("S", "CLICHE_ONE"))

    if any(len(re.findall(word, whole)) >= 2 for word in ABSTRACT.pattern.split("|")):
        hits.append(("H", "ABSTRACT_REPEAT"))

    last_two = " ".join(sentences[-2:])
    if (sentences and CTA_END.search(sentences[-1])) or (
        CTA_INVITE.search(last_two) and CTA_WISH.search(last_two)
    ):
        hits.append(("H", "CTA"))
    if any(LESSON.search(s) for s in sentences):
        hits.append(("H", "LESSON"))
    if PLEDGE.search(whole):
        hits.append(("H", "PLEDGE"))

    memo_counts = {}
    for text in memo["o"]:
        for stem in _stems(text):
            memo_counts[stem] = memo_counts.get(stem, 0) + 1
    counts = {}
    for stem in _stems(whole):
        # 숫자·영문 조각("80", "or")은 낱말 반복으로 보지 않는다.
        if re.fullmatch(r"[가-힣]+", stem):
            counts[stem] = counts.get(stem, 0) + 1
    if any(
        n >= 3 and stem not in keep_stems and memo_counts.get(stem, 0) < 2
        for stem, n in counts.items()
    ):
        hits.append(("S", "STEM_REPEAT"))

    lasts = [_words(s)[-1] if _words(s) else "" for s in sentences]
    tails = [re.sub(r"[^가-힣]", "", s)[-3:] for s in sentences]
    same_last = any(lasts[i] and lasts[i] == lasts[i + 1] for i in range(len(lasts) - 1))
    same_tail = any(
        tails[i] and tails[i] == tails[i + 1] == tails[i + 2]
        for i in range(len(tails) - 2)
    )
    formal = len(sentences) >= 4 and sum(
        re.sub(r"[^가-힣]", "", s).endswith("니다") for s in sentences
    ) >= 0.8 * len(sentences)
    if same_last or same_tail or formal:
        hits.append(("S", "SAME_LAST"))

    for s in sentences:
        # 숫자 안의 쉼표(18,600원)는 구획이 아니다. "꽃다발, 꽃바구니, … 등"처럼
        # 넷 이상이거나 '등'으로 맺는 품목 안내는 사람 글에 흔해 뺀다(보정 결과).
        parts = [p.strip() for p in re.split(r"(?<!\d),|,(?!\d)", s)]
        listed = len(parts) == 3 and not re.search(r"(?:^|\s)등(?:\W|$)", parts[-1])
        if (listed and all(len(p.split()) <= 2 for p in parts[1:-1])) or LIST_PAIR.search(s):
            hits.append(("S", "LIST3"))
            break
    if PASSIVE.search(whole):
        hits.append(("S", "PASSIVE"))
    if DEDICATION.search(whole):
        hits.append(("S", "DEDICATION"))
    if len(CONNECTIVE.findall(whole)) >= 2:
        hits.append(("S", "CONNECTIVE"))

    if not ADDRESS.search(whole):
        hits.append(("R", "NO_ADDRESS"))
    memo_grams = set().union(*(_ngrams(n) for n in memo["n"]))
    if (EXAMPLE_NGRAMS - memo_grams) & _ngrams(whole_n):
        hits.append(("R", "COPY_EXAMPLE"))
    return hits


# ── analysis 정리 (설계 1절, LLM 없음) ──
def _quote_ok(quote, memo):
    return _quote_span(quote, memo) is not None


def _quote_span(quote, memo):
    """A1. quote가 메모의 어절 경계에 맞고, 부정어를 떼어 내지 않았는가.

    맞으면 (원문, 끝 위치)를 돌려준다. 표기 변형은 모으지 않고 글자 그대로 본다.
    """
    target = _N(quote, canon=False)
    if len(target) < 2:
        return None
    pattern = re.compile(r"[\s\W_]*".join(re.escape(c) for c in target), re.I)
    for source in memo["o"]:
        if target not in _N(source, canon=False):
            continue
        for match in pattern.finditer(source):
            start, end = match.start(), match.end()
            if start > 0 and source[start - 1].isalnum():
                continue
            tail = re.match(r"\w*", source[end:]).group()
            # 어절 끝이거나, 남은 부분이 조사·어미뿐이면 경계로 본다.
            if tail and tail not in SUFFIXES:
                continue
            before = re.findall(r"\w+", source[:start])
            if before and before[-1] in ("안", "못", "않", "없", "별로"):
                continue
            # "효과는 없지만"에서 "효과"만 자르는 것도 뜻이 뒤집힌다.
            after = re.findall(r"\w+", source[end + len(tail):])
            if after and re.match(r"(?:않|없|못하|아니)", after[0]):
                continue
            return source, end + len(tail)
    return None


def clean_analysis(analysis, memo, stats):
    """quote가 메모와 맞지 않는 fact를 버리고, READY 조건을 코드로 다시 본다.

    (정리된 analysis, 질문/중단 응답 또는 None)을 돌려준다.
    """
    facts = analysis.get("facts") or []
    valid = {}
    for fact in facts:
        span = _quote_span(fact.get("quote"), memo)
        if not span:
            continue
        fact_id = fact.get("id")
        valid[fact_id] = dict(fact)
        source, end = span
        quote = _O(fact.get("quote"))
        # 어림·미정 표지가 quote에 있거나 바로 뒤에 "?"가 붙으면 문장에도 남겨야 한다.
        if HEDGE_IN_QUOTE.search(quote) or "?" in source[end:end + 2]:
            memo["hedge_ids"].add(fact_id)
        # "맛이 다른거 같다고 … 그럴리가요"처럼 메모가 의심한 말. quote 안이든
        # 뒤 30자 안이든 같다. Writer 입력에는 넣지 않는다.
        if DOUBT.search(quote) or DOUBT.search(source[end:end + 30]):
            memo["doubt_ids"].add(fact_id)
    stats["facts"] = len(facts)
    stats["facts_dropped"] = len(facts) - len(valid)

    for fact in valid.values():
        if fact.get("kind") != "buyer_action":
            fact["convertible_to"] = None
            continue
        converted = fact.get("convertible_to")
        cited = [_N(fact.get("quote"))]
        if converted and (
            _ungrounded(converted, cited, memo)
            or check_banned(converted, cited, memo)
        ):
            fact["convertible_to"] = None

    def keep_ids(ids):
        return [i for i in ids or [] if i in valid]

    analysis["facts"] = list(valid.values())
    product = analysis.get("product") or {}
    for key in ("name_fact_id", "price_fact_id"):
        if product.get(key) not in valid:
            product[key] = None
    analysis["product"] = product

    phrases = [
        p for p in analysis.get("distinctive_phrases") or []
        if p.get("fact_id") in valid and _contains(_N(p.get("phrase")), memo["n"])
    ]
    analysis["distinctive_phrases"] = phrases
    if analysis.get("sensory_hook") not in {p.get("id") for p in phrases}:
        analysis["sensory_hook"] = None
    for key in ("seller_scene", "why_this_one", "scene", "ending", "charm"):
        part = analysis.get(key)
        if isinstance(part, dict):
            part["fact_ids"] = keep_ids(part.get("fact_ids"))

    # 매력 각도는 근거 fact가 하나도 안 남으면 없앤다.
    charm = analysis.get("charm")
    if not isinstance(charm, dict) or not charm.get("fact_ids"):
        analysis["charm"] = None
    season = analysis.get("season")
    if not isinstance(season, dict) or season.get("fact_id") not in valid:
        analysis["season"] = None

    # 상식은 메모에 나온 대상에 대해서만, 수치·효능·재료·새 이름 없이 3개까지.
    knowledge = []
    raw_knowledge = analysis.get("common_knowledge") or []
    for item in raw_knowledge:
        if not isinstance(item, dict):
            continue
        about, note = item.get("about") or "", item.get("note") or ""
        if not _contains(_N(about), memo["n"]):
            continue
        if check_banned(note, [], memo) or _unknown_long_words(note, memo):
            continue
        knowledge.append({"about": about, "note": note})
    analysis["common_knowledge"] = knowledge[:3]
    # 상식 문장의 근거로 쓴다. Writer 입력에는 analysis 그대로 간다.
    memo["ck_n"] = [_N(item["note"]) for item in analysis["common_knowledge"]]
    stats["charm"] = analysis["charm"] is not None
    stats["season"] = analysis["season"] is not None
    stats["ck"] = len(analysis["common_knowledge"])
    stats["ck_dropped"] = len(raw_knowledge) - stats["ck"]

    readiness = analysis.get("story_readiness")
    stats["readiness"] = readiness
    if readiness == "NO_STORY_FOUND":
        return analysis, {"status": "NO_STORY_FOUND"}

    scene = analysis.get("seller_scene") or {}
    has_scene = any(
        valid[i].get("kind") == "seller_scene" for i in scene.get("fact_ids") or []
    )
    # 판매자 장면이 없어도 이야깃거리(매력·상식)와 살 방법(가격·구매 방법, DEMO면 권유로
    # 바꾼 구매 fact)이 함께 있으면 글을 쓴다(감성 개편 2026-10-29, 잉어킹 메모).
    has_story = analysis.get("charm") is not None or bool(analysis.get("common_knowledge"))
    has_buy = bool(product.get("price_fact_id")) or any(
        f.get("kind") in ("price", "how_to_buy") for f in valid.values()
    ) or (
        memo.get("mode") == "DEMO_SELLER" and any(
            f.get("kind") == "buyer_action" and f.get("convertible_to") for f in valid.values()
        )
    )
    stats["gate"] = "scene" if has_scene else ("story_buy" if has_story and has_buy else "none")
    if readiness != "READY" or not (has_scene or (has_story and has_buy)) or not product.get("name"):
        questions = (analysis.get("questions") or [])[:1] if readiness == "NEED_MORE_INFO" else []
        questions = [q for q in questions if isinstance(q, str) and q.strip()]
        return analysis, {
            "status": "NEED_MORE_INFO",
            "questions": questions or [FIXED_QUESTION]
        }
    return analysis, None


# ── 절 단위 다듬기 ──
# 문장 끝 절 하나 때문에 앞의 사실까지 지워지지 않게 한다(rerun1 무화과: "…까지만 하고,
# …끝이니 일찍 들러 주세요"가 통째로 지워져 판매 기간이 사라졌다).
CLAUSE_BREAK = re.compile(r"(?:으니까|니까|으니|니|고|서),? |, ")


def _polite_end(stem):
    """연결어미를 뗀 어간을 해요체로 맺는다. 자신 없는 활용이면 None."""
    if not stem or not re.search(r"[가-힣]$", stem):
        return None
    if stem.endswith("하"):
        return stem[:-1] + "해요."
    if stem.endswith("되"):
        return stem[:-1] + "돼요."
    if stem.endswith("이") and len(stem) >= 2:
        return stem + "에요."
    code = ord(stem[-1]) - 0xAC00
    vowel, final = (code % 588) // 28, code % 28
    if final:
        # ㄷ·ㅂ·ㅅ 받침은 불규칙(걸어요·따가워요·나아요)이 섞여 맺지 않는다.
        if final in (7, 17, 19):
            return None
        return stem + ("아요." if vowel in (0, 8) else "어요.")
    # 받침 없는 ㅏ·ㅓ·ㅕ는 "요"만 붙인다(끝나요·서요·켜요).
    if vowel in (0, 4, 6):
        return stem + "요."
    return None


def _close_clause(prefix):
    prefix = prefix.rstrip(" ,")
    if re.search(r"(?:요|다|죠)$", prefix):
        return prefix + "."
    match = re.search(r"(으니까|니까|으니|니|고|서)$", prefix)
    if not match:
        return None
    stem = prefix[:match.start()]
    # "~있다고 해서"를 "~있다고 해요"로 맺으면 남의 말 전하기로 뜻이 바뀐다.
    if re.search(r"[다라]고 ?하$|[다라]고 ?해$", stem):
        return None
    # "사 가시라고", "좋다고"의 "고"는 인용·목적이라 "~라요"로 맺을 수 없다.
    if match.group(1) == "고" and stem.endswith(("라", "다")):
        return None
    if match.group(1) == "서":
        # "만들어서"→"만들어요", "해서"→"해요". "~라서"는 맺지 않는다.
        if re.search(r"(?:어|아|해|여|워|와|려|져|쳐|켜|봐)$", stem):
            return stem + "요."
        return None
    return _polite_end(stem)


def _clause_candidates(text):
    """뒤 절을 하나씩 뗀 앞부분을 긴 것부터 돌려준다(맺음을 고친 문장)."""
    ends = [m.start() + len(m.group().rstrip(" ,")) for m in CLAUSE_BREAK.finditer(text)]
    for end in reversed(ends):
        closed = _close_clause(text[:end])
        if closed and len(_words(closed)) >= 2:
            yield closed


# ── Writer 결과 검사 (설계 4절) ──
def check_story(story, analysis, memo):
    """문장별 A·B 검사로 지울 문장을 고르고, 제목·비율·C 신호를 본다.

    화면에 쓰는 문장과 재작성 사유를 함께 돌려준다. 사유의 detail에는
    문장 조각이 들어가므로 API로만 보내고 로그에는 남기지 않는다.
    """
    facts = {f["id"]: f for f in analysis.get("facts") or []}
    ending_type = (analysis.get("ending") or {}).get("type")

    def cited_of(ids):
        texts, kinds, scenes = [], set(), []
        for fact_id in ids:
            fact = facts[fact_id]
            kinds.add(fact.get("kind"))
            if fact.get("kind") == "buyer_action":
                # 구매 행위는 권유로 바꾼 문장과만 겹침을 본다.
                if fact.get("convertible_to"):
                    texts.append(_N(fact["convertible_to"]))
                continue
            texts.append(_N(fact.get("quote")))
            if fact.get("kind") == "seller_scene":
                scenes.append(_N(fact.get("quote")))
        return texts, kinds, scenes

    product = analysis.get("product") or {}
    product_fact_ids = {product.get("name_fact_id")} | {
        f["id"] for f in facts.values() if f.get("kind") == "product"
    }

    def cost_low(text, ids, is_headline=False):
        match = COST_LOW.search(text)
        if match:
            return match.group()
        match = COST_LOW_FOUND.search(text)
        if match and (
            is_headline
            or set(ids) & product_fact_ids
            or any(COST_LOW_FOUND.search(facts[i].get("quote") or "") for i in ids)
        ):
            return match.group()
        return None

    name_stems = _stems(product.get("name") or "")

    def product_sentence(text, ids):
        # writer.md 1절 "상품명으로 알 수 있는 것": 상품 fact를 달고 상품명 낱말을 쓴 문장.
        return bool(set(ids) & product_fact_ids) and any(
            _stem_in(stem, [_N(text)]) for stem in name_stems
        )

    def problem(text, ids, is_fact, is_ending=False, role=None):
        """A·B 검사. 걸리면 (코드, detail), 아니면 (None, None)."""
        cited, kinds, scenes = cited_of(ids)
        # 상식 문장: 감성 charm 문장, 또는 상품 fact를 달고 상품명을 쓴 문장.
        # 살아남은 common_knowledge 설명을 근거에 더해 상식 낱말이 메모 밖으로 세어지지 않게 한다.
        common = (role == "charm" and not is_fact) or product_sentence(text, ids)
        if common:
            cited = cited + memo.get("ck_n", [])
        if common:
            allowance = 3
        elif role == "charm":
            # charm 사실 문장은 charm fact를 전부 다는 일이 많다: fact 수에 비례.
            allowance = min(3, max(1, len(set(ids))))
        else:
            # fact를 여럿 합친 문장일수록 이음말이 늘어난다(gap-audit A-5): 1 + fact 수//2, 최대 3.
            allowance = min(3, 1 + len(set(ids)) // 2)
        # 약속·인사 끝맺음은 말투라 메모 밖 낱말 수를 보지 않는다. B·SERVICE는 그대로 본다.
        courtesy_end = (
            is_ending and ending_type in ("promise", "greeting")
            and COURTESY_END.search(text) and not _is_invite(text)
        )
        code, detail = None, None
        if is_fact and not ids:
            code = "NO_FACT"
        elif "buyer_action" in kinds and BUYER_RESTATE.search(text):
            code, detail = "BUYER_RESTATE", BUYER_RESTATE.search(text).group()
        elif memo.get("mode") == "DEMO_SELLER" and DEMO_BUYER.search(text):
            code, detail = "DEMO_BUYER", DEMO_BUYER.search(text).group()
        elif is_fact and set(ids) & memo.get("hedge_ids", set()) and not HEDGE_IN_SENTENCE.search(text):
            # 감성 문장은 그 fact를 상상의 바탕으로만 단다. 단정은 사실 문장에서 생긴다.
            code = "HEDGE"
        elif set(ids) & memo.get("doubt_ids", set()) and not DOUBT.search(text):
            code = "HEDGE"
        else:
            marker = _seller_ungrounded(text, cited, memo, kinds, is_fact)
            if marker:
                code, detail = "SELLER_UNGROUNDED", marker
            elif (is_fact or _seller_markers_apply(text, is_fact)) and not courtesy_end:
                why = _ungrounded(text, cited, memo, allowance)
                if why:
                    code, detail = "UNGROUNDED", why
            if not code and common:
                # 상식은 더할 수 있어도 메모에 없는 이름은 안 된다(진화형 이름 등).
                unknown = _unknown_long_words(text, memo)
                if unknown:
                    code, detail = "PROPER", unknown[0]
            if not code:
                hits = check_banned(text, cited, memo, scenes)
                if hits:
                    code, detail = hits[0]
        if not code and cost_low(text, ids):
            code, detail = "COST_LOW", cost_low(text, ids)
        # 이야기 문장에는 금액을 쓰지 않는다(사용자 결정: 실무 정보 한 줄). 가격은 info 줄과 카드에.
        if not code and MONEY.search(text):
            code, detail = "MONEY", MONEY.search(text).group()
        return code, detail

    def info_problem(text, ids):
        """info 줄: " · "로 이은 항목이 모두 fact 말이고, 권유·새 정보가 없는가."""
        if not ids:
            return "INFO_UNGROUNDED", "fact_ids 없음"
        if _is_invite(text) or INFO_ADDRESS.search(text):
            return "INFO_UNGROUNDED", "권유·말 건넴"
        cited = cited_of(ids)[0] + [_N(product.get("name") or "")]
        for item in re.split(r"\s*[·•|/]\s*", text):
            outside = [st for st in _stems(item) if not _stem_in(st, cited)]
            if outside:
                return "INFO_UNGROUNDED", "fact에 없는 항목"
        hits = check_banned(text, cited, memo)
        if hits:
            return hits[0]
        return None, None

    def ids_in(text, ids):
        # 다듬은 문장에 내용이 남은 fact만 단다.
        stems = _stems(text)
        return [i for i in ids if any(_stem_in(st, cited_of([i])[0]) for st in stems)]

    raw = [s for s in story.get("sentences") or [] if isinstance(s, dict)]
    kept, deleted, reasons = [], {}, []
    fixes = {"role_fix": 0, "ending_fix": 0}
    lost_ids = set()
    last_index = None
    info = None
    # 끝맺음은 info 줄을 뺀 이야기의 마지막 문장이다.
    final_index = max(
        (
            i for i, s in enumerate(raw)
            if _O(EMOJI.sub("", s.get("text") or "")) and s.get("role") != "info"
        ),
        default=None
    )
    for index, sentence in enumerate(raw):
        text = _O(EMOJI.sub("", sentence.get("text") or ""))
        if not text:
            continue
        if sentence.get("role") == "info":
            # 실무 정보 한 줄(가격·기간·구매 방법·판매 상태). 이야기 검사 대신 info 검사.
            ids = [i for i in sentence.get("fact_ids") or [] if i in facts]
            code, detail = info_problem(text, ids)
            if code or info is not None:
                code = code or "INFO_EXTRA"
                deleted[code] = deleted.get(code, 0) + 1
                reasons.append(_reason(code, index, detail or "info 줄은 하나만", ids))
                lost_ids.update(ids)
                continue
            info = {"index": index, "text": text, "ids": set(ids), "role": "info"}
            continue
        last_index = index
        ids = [i for i in sentence.get("fact_ids") or [] if i in facts]
        is_fact = not sentence.get("interpretation")
        is_ending = index == final_index or bool(sentence.get("is_ending"))
        # 옛 출력에는 role이 없다.
        role = sentence.get("role")
        if role == "scene" and is_fact and (
            not ids or problem(text, ids, True, is_ending, role)[0] in ("UNGROUNDED", "NO_FACT")
        ):
            # 장면 문장은 감성이다. 사실로 왔는데 사실 검사(A2)를 못 넘으면 감성으로 바로잡는다.
            # fact로 통과하는 판매자 장면("흔들면 냥이가 흥분해요")은 사실 문장으로 둔다 —
            # 모두 감성으로 돌리면 비율이 넘쳐 진짜 장면·끝맺음이 잘린다(스모크 쥐꼬리).
            is_fact = False
            fixes["role_fix"] += 1
        if (
            is_fact and is_ending and ending_type in ("promise", "greeting")
            and not cited_of(ids)[1] & {"how_to_buy", "price"}
            # 약속·인사 말투로 끝날 때만. 마지막 사실 문장("색은 두 가지예요")까지 풀어 주지 않는다.
            and COURTESY_END.search(text)
        ):
            # 약속·인사 끝맺음은 말투다. 사실 문장 검사로 지우지 않는다(B표는 그대로).
            is_fact = False
            fixes["ending_fix"] += 1
        code, detail = problem(text, ids, is_fact, is_ending, role)
        # 구매·방문담과 의심 누락은 문장 전체의 성격이라 앞 절만 살려도 고쳐지지 않는다.
        if code and code not in ("NO_FACT", "DEMO_BUYER", "BUYER_RESTATE", "HEDGE"):
            # 뒤 절만 문제면 앞 절을 살린다. 다듬은 문장도 모든 검사를 다시 통과해야 한다.
            for candidate in _clause_candidates(text):
                candidate_ids = ids_in(candidate, ids)
                if (candidate_ids or not is_fact) and problem(
                    candidate, candidate_ids, is_fact, is_ending, role
                )[0] is None:
                    deleted["TRIM_" + code] = deleted.get("TRIM_" + code, 0) + 1
                    # 떼어 낸 절이 담던 fact를 Writer가 되살릴 수 있게 넘긴다.
                    reasons.append(_reason(
                        code, index, detail, sorted(set(ids) - set(candidate_ids))
                    ))
                    lost_ids.update(set(ids) - set(candidate_ids))
                    text, ids, code = candidate, candidate_ids, None
                    break
        if code:
            deleted[code] = deleted.get(code, 0) + 1
            # 지운 문장이 담던 fact id. 재작성에서 근거 있는 문장으로 되살리게 한다.
            reasons.append(_reason(code, index, detail, ids))
            lost_ids.update(ids)
            continue
        kinds = cited_of(ids)[1]
        kept.append({
            "index": index,
            "paragraph": sentence.get("paragraph") or 1,
            "text": text,
            "interpretation": not is_fact,
            "kinds": kinds,
            "ids": set(ids),
            "role": role
        })

    # A6. 끝맺음은 마지막 문장 하나다. info면 구매 방법·가격 fact가 있어야 한다.
    if kept and ending_type == "info" and kept[-1]["index"] == last_index and not (
        kept[-1]["kinds"] & {"how_to_buy", "price"}
    ):
        dropped = kept.pop()
        deleted["ENDING_INFO"] = deleted.get("ENDING_INFO", 0) + 1
        reasons.append(_reason(
            "ENDING_INFO", dropped["index"], "끝맺음이 info인데 구매 방법·가격 fact가 없음",
            sorted(dropped["ids"])
        ))

    # 가격·판매 방법(기간 포함) fact가 남은 문장 어디에도 없으면 재작성할 이유가 된다.
    still_cited = set().union(*(s["ids"] for s in kept)) if kept else set()
    if info:
        still_cited |= info["ids"]
    lost_key = any(
        facts[i].get("kind") in ("price", "how_to_buy") for i in lost_ids - still_cited
    )
    if lost_ids - still_cited:
        # Writer 9절 코드 사전의 LOST_FACT로 보낸다.
        reasons.append(_reason(
            "LOST_FACT", None, "지운 문장에만 있던 fact. 메모 말로 다시 담아 주세요",
            sorted(lost_ids - still_cited)
        ))

    # 제목 (A8)
    headline = _O(EMOJI.sub("", story.get("headline") or ""))
    headline_ids = [i for i in story.get("headline_fact_ids") or [] if i in facts]
    head_cited, _, head_scenes = cited_of(headline_ids)
    head_problem = None
    if not headline:
        head_problem = "제목 없음"
    elif not headline_ids:
        head_problem = "headline_fact_ids 없음"
    elif memo.get("mode") == "DEMO_SELLER" and DEMO_BUYER.search(headline):
        head_problem = "DEMO_BUYER"
    else:
        # 프롬프트는 "하나까지"지만 코드는 하나 여유를 둔다(code-requests 5.4).
        head_problem = _ungrounded(headline, head_cited, memo, 2)
        if not head_problem:
            hits = check_banned(headline, head_cited, memo, head_scenes)
            head_problem = hits[0][0] if hits else None
        if not head_problem and cost_low(headline, headline_ids, is_headline=True):
            head_problem = "COST_LOW"
    # 제목에는 금액을 쓰지 않는다(사용자 결정, writer.md 6절). 판매가·처음 생각한 값·할인 모두.
    if headline and not head_problem and HEADLINE_PRICE.search(headline):
        head_problem = "HEADLINE_PRICE"
    if head_problem:
        reasons.append({"code": "HEADLINE", "sentence_index": None, "detail": head_problem})

    # A9. 카드는 메모의 이름·금액만 쓴다.
    card = story.get("product_card") or {}
    product = analysis.get("product") or {}
    name = _O(card.get("name"))
    if not name or not any(_stem_in(s, memo["n"]) for s in _stems(name) or [_N(name)]):
        name = product.get("name") or name
    price = _O(card.get("price_display"))
    price_fact = facts.get(product.get("price_fact_id")) or {}
    # 메모 안의 다른 금액(처음 생각한 값 등)이 아니라 가격 fact의 금액이어야 한다.
    price_values = _numbers(price_fact.get("quote"))
    if not price_fact or not price or not NUM_RUN.search(price) or any(
        _num_value(m.group()) not in price_values for m in NUM_RUN.finditer(price)
    ):
        price = ""

    # C 신호
    keep_stems = set(_stems(name)) | {
        s for p in analysis.get("distinctive_phrases") or [] for s in _stems(p.get("phrase"))
    }
    signals = machine_signals([headline] + [s["text"] for s in kept], memo, keep_stems)
    # 약속·인사로 골랐는데 권유형으로 끝나면 기계 글 신호로 본다(설계 9절 2).
    if kept and ending_type in ("promise", "greeting") and _is_invite(kept[-1]["text"]):
        signals.append(("S", "ENDING_INVITE"))
    # 계절 메모면 제목이나 첫 문장이 그 계절로 열려야 한다(S).
    season = analysis.get("season") or {}
    if season.get("fact_id") and season["fact_id"] not in headline_ids and not (
        kept and season["fact_id"] in kept[0]["ids"]
    ):
        signals.append(("S", "NO_SEASON_OPEN"))
    # 손님 장면(role scene) 문장이 하나도 없으면 메모 받아쓰기에 가깝다(S). 길이와 상관없다.
    # role이 없는 옛 출력은 보지 않는다.
    if any(s.get("role") for s in raw) and not any(s["role"] == "scene" for s in kept):
        signals.append(("S", "NO_SCENE"))
    for grade, code in signals:
        reasons.append({
            "code": code, "sentence_index": None, "detail": SIGNAL_DETAIL.get(code, grade)
        })

    # 매력 각도가 있는데 charm 문장이 하나도 안 남음(옛 출력처럼 role이 없으면 보지 않음).
    has_roles = any(s.get("role") for s in raw)
    no_charm = has_roles and bool(analysis.get("charm") or analysis.get("common_knowledge")) and not any(
        s["role"] == "charm" for s in kept
    )
    if no_charm:
        reasons.append({
            "code": "NO_CHARM", "sentence_index": None,
            "detail": "charm·common_knowledge가 있는데 charm 문장이 없음"
        })

    return {
        "kept": kept,
        "info": info,
        "no_charm": no_charm,
        "fixes": fixes,
        "lost_key_fact": lost_key,
        "name_fact_id": product.get("name_fact_id"),
        "price_fact_id": product.get("price_fact_id"),
        "product_name": _N(product.get("name") or name),
        "product_head": (_stems((product.get("name") or name or "").split(" ")[-1]) or [None])[0],
        "last_index": last_index,
        "ending_type": ending_type,
        "deleted": deleted,
        "reasons": reasons,
        "headline": headline,
        "headline_ok": head_problem is None,
        "name": name,
        "price": price,
        "signals": signals
    }


# 설계 9절 2: 권유형 끝맺음.
ENDING_INVITE = re.compile(
    r"(?:해|어|아|여|려|겨) ?보세요|맛보세요|데려가세요|들이세요|시작하세요|누리세요"
)
# 약속·인사 말투로 끝나는 문장("~드릴게요", "~보내세요"). 마지막 사실 문장은 해당하지 않는다.
COURTESY_END = re.compile(r"게요\W*$|드려요\W*$|보내세요|되세요|조심하세요|건강하세요")
# 문의 안내("물어보세요·문의 주세요·연락 주세요")는 권유가 아니라 안내·약속 쪽이다.
INQUIRY_END = re.compile(r"물어 ?보세요|문의|연락 ?주세요|말씀해 ?주세요|여쭤 ?보세요|DM", re.I)


def _is_invite(text):
    return bool(ENDING_INVITE.search(text)) and not INQUIRY_END.search(text)


# Writer 9절 코드 사전에 없는 코드는 detail에 한국어 한 줄을 넣는다.
SIGNAL_DETAIL = {
    "ENDING_INVITE": "약속·인사로 골랐는데 권유형(~해 보세요)으로 끝남",
    "NO_SEASON_OPEN": "계절 fact가 있는데 제목·첫 문장에 없음",
    "NO_SCENE": "손님 장면(role scene) 문장이 없음"
}


# 금액: 숫자·한글 수 + (만|천|백)? + 원, ₩. "11월"·"350"처럼 원이 없으면 금액이 아니다.
HEADLINE_PRICE = re.compile(
    r"₩ ?\d|\d[\d,.]*\s?(?:[만천백]\s?(?:\d[\d,.]*\s?)?)*원"
    r"|(?<![가-힣])(?:[일이삼사오육칠팔구십]|한|두|세|네|다섯|열)?\s?(?:만|천|백)\s?(?:[일이삼사오육칠팔구]?천)?\s?원"
)


# 이야기 문장의 금액도 같은 패턴으로 본다.
MONEY = HEADLINE_PRICE
# info 줄에는 말 건넴·권유가 없어야 한다(명사구 나열).
INFO_ADDRESS = re.compile(r"세요|드려요|드릴게요|둘게요|주세요|보세요")


def _reason(code, index, detail, fact_ids):
    # 지운 문장이 달고 있던 fact id를 detail과 필드 둘 다에 둔다(Writer 9절이 읽는다).
    fact_ids = list(fact_ids or [])
    if fact_ids:
        detail = (f"{detail}; " if detail else "") + "facts=" + ",".join(fact_ids)
    return {"code": code, "sentence_index": index, "detail": detail, "fact_ids": fact_ids}


def _ratio_state(checked):
    kept = checked["kept"]
    # 끝맺음은 promise·greeting일 때만, 그리고 Writer의 마지막 문장이 남았을 때만 뺀다.
    # 권유형으로 끝났으면 analysis 유형과 상관없이 invite로 보고 비율에 넣는다.
    ending_out = bool(kept) and checked["ending_type"] in ("promise", "greeting") and (
        kept[-1]["index"] == checked["last_index"]
    ) and not _is_invite(kept[-1]["text"])
    body = kept[:-1] if ending_out else kept
    interpretations = sum(s["interpretation"] for s in body)
    return body, interpretations, interpretations > max(1, len(body) // 3)


def _product_gaps(checked):
    """본문 사실 문장에 상품·가격이 없는가(설계 9절 1, run1 선운사).

    상품은 name_fact_id를 단 사실 문장이나 상품명을 쓴 사실 문장, 가격은 price_fact_id를
    단 문장이 있어야 한다. 빠진 쪽의 이름 목록을 돌려준다.
    """
    facts_only = [s for s in checked["kept"] if not s["interpretation"]]
    name = checked["product_name"]
    # 상품명 마지막 낱말의 어간("유약 흘림 머그컵"→"머그")만 써도 상품을 말한 것으로 본다.
    head = checked["product_head"]
    gaps = []
    if not any(
        checked["name_fact_id"] in s["ids"]
        or (len(name) >= 2 and name in _N(s["text"]))
        or (head and _stem_in(head, [_N(s["text"])]))
        for s in facts_only
    ):
        gaps.append("product")
    price_id = checked["price_fact_id"]
    info_ids = (checked.get("info") or {}).get("ids") or set()
    if price_id and price_id not in info_ids and not any(price_id in s["ids"] for s in checked["kept"]):
        gaps.append("price")
    return gaps


def needs_rewrite(checked):
    """D. 1차 결과를 다시 쓰게 할 사유 코드 목록."""
    codes = []
    if not checked["headline_ok"]:
        codes.append("HEADLINE")
    if not any(not s["interpretation"] for s in checked["kept"]):
        codes.append("NO_FACT_BODY")
    if _product_gaps(checked):
        codes.append("NO_PRODUCT_BODY")
    if sum(checked["deleted"].values()) >= 2:
        codes.append("DELETED")
    if checked.get("lost_key_fact"):
        codes.append("LOST_FACT")
    if checked.get("no_charm"):
        codes.append("NO_CHARM")
    grades = [g for g, _ in checked["signals"]]
    if "H" in grades:
        codes.append("H")
    if grades.count("S") >= 2:
        codes.append("S")
    codes += [c for g, c in checked["signals"] if g == "R"]
    return codes


def finalize(checked):
    """E. 모든 경로의 마지막 정리. 화면 응답을 돌려준다."""
    kept = checked["kept"]
    # (1) 감성 비율 상한(1/3)은 없앴다(Writer 프롬프트 감성 개편). 넘었는지는 기록만 한다.
    checked["ratio_over"] = _ratio_state(checked)[2]

    # (2) 사실 문장이 하나도 없으면 글을 내보내지 않는다.
    if not any(not s["interpretation"] for s in kept):
        return {"status": "NO_STORY_FOUND"}
    # 2차에도 상품·가격 문장이 빠졌으면 로그만 남긴다(설계 9절 1). 가격은 카드에 있다.
    checked["product_gaps"] = _product_gaps(checked)

    # (3) 제목이 끝까지 실패하면 상품명을 제목으로 쓴다(본문은 유지).
    headline = checked["headline"] if checked["headline_ok"] else checked["name"]

    # (4) 문단으로 묶는다. 빈 문단은 생기지 않고 번호는 순서대로 다시 매긴다.
    paragraphs = {}
    for sentence in kept:
        paragraphs.setdefault(sentence["paragraph"], []).append(sentence["text"])
    body = [" ".join(paragraphs[number]) for number in sorted(paragraphs)]
    # 실무 정보 한 줄은 이야기와 섞지 않고 따로 마지막 문단으로 둔다.
    if body and checked.get("info"):
        body.append(checked["info"]["text"])

    if not headline or not body:
        return {"status": "NO_STORY_FOUND"}
    return {
        "status": "READY",
        "product_card": {"name": checked["name"] or "", "price": checked["price"] or ""},
        "headline": headline,
        "body": body
    }


def run_story_engine(
    client,
    raw_input,
    scenario_mode=SCENARIO_MODE,
    seller_additions=(),
    stats=None
):
    """Analyzer → 정리 → Writer → 검사 → [재작성 1회] → 마무리.

    stats에 dict를 넘기면 호출별 토큰·시간과 삭제 코드가 채워진다(테스트용).
    같은 내용이 요청당 한 줄 `lepi_run` 로그로 남는다. 메모·문장은 남기지 않는다.
    """
    # 체험판(handler)은 기본값으로만 부른다. 두 인자는 기준 샘플처럼
    # DEMO_SELLER나 덧붙인 말이 있는 입력을 테스트할 때만 바꾼다.
    seller_additions = list(seller_additions)
    stats = {} if stats is None else stats
    started = time.monotonic()
    stats.update({
        "rid": uuid.uuid4().hex[:8],
        "model": [ANALYZER_MODEL, WRITER_MODEL],
        "check_mode": CHECK_MODE,
        "effort": [ANALYZER_EFFORT, WRITER_EFFORT],
        "mode": scenario_mode,
        "memo_len": len(raw_input),
        "additions": len(seller_additions),
        "calls": []
    })
    try:
        result = _run_engine(
            client, raw_input, scenario_mode, seller_additions,
            started + DEADLINE_SECONDS, stats
        )
        stats["status"] = result["status"]
        return result
    except Exception as error:
        stats.update(_error_info(error))
        raise
    finally:
        stats["ms"] = int((time.monotonic() - started) * 1000)
        # 운영 기준(42초·호출당 25초)이었다면 시간 초과였을지.
        stats["over_prod"] = stats["ms"] > PROD_DEADLINE_SECONDS * 1000 or any(
            c.get("over_prod") for c in stats.get("calls") or []
        )
        print("lepi_run", json.dumps(stats, ensure_ascii=False))


def _report_only(story, analysis, checked, stats):
    """report 모드: 검사 결과로 바꾸지 않고 Writer 글을 그대로 화면 모양으로 옮긴다.

    구조만 맞춘다(문단 묶기, info 줄은 마지막 문단). 했을 일은 stats["would"]에
    코드·개수로만 남긴다(문장·제목 문자열은 남기지 않는다).
    """
    import copy
    would_finalize = finalize(copy.deepcopy(checked))
    stats["would"] = {
        "delete": dict(checked["deleted"]),
        "rewrite_reasons": needs_rewrite(checked),
        "ratio_over": _ratio_state(checked)[2],
        "headline_fail": [] if checked["headline_ok"] else ["HEADLINE"] + [
            r["detail"] for r in checked["reasons"]
            if r["code"] == "HEADLINE" and re.fullmatch(r"[A-Z_]+", r["detail"] or "")
        ],
        "product_gaps": _product_gaps(checked),
        "status": would_finalize["status"],
        "price_card_fix": (story.get("product_card") or {}).get("price_display") not in (None, "", checked["price"])
    }

    sentences = [x for x in story.get("sentences") or [] if isinstance(x, dict) and _O(x.get("text"))]
    story_part = [x for x in sentences if x.get("role") != "info"]
    info_part = [x for x in sentences if x.get("role") == "info"]
    paragraphs = {}
    for sentence in story_part:
        paragraphs.setdefault(sentence.get("paragraph") or 1, []).append(_O(sentence["text"]))
    body = [" ".join(paragraphs[number]) for number in sorted(paragraphs)]
    # 실무 정보 줄은 이야기와 섞지 않고 마지막 문단으로(구조 규칙).
    body += [_O(x["text"]) for x in info_part]

    card = story.get("product_card") or {}
    headline = _O(story.get("headline"))
    stats["sentences"] = len(sentences)
    stats["roles"] = {
        role: sum(x.get("role") == role for x in sentences)
        for role in ("fact", "charm", "scene", "ending", "info")
    }
    if not headline or not body:
        return {"status": "NO_STORY_FOUND"}
    return {
        "status": "READY",
        "product_card": {
            "name": _O(card.get("name")) or (analysis.get("product") or {}).get("name") or "",
            "price": _O(card.get("price_display"))
        },
        "headline": headline,
        "body": body
    }


def _light_check(story, analysis, memo, stats):
    """light 모드: 메모 어디에도 없는 판매 사실과 원가·주운 물건 이야기가 든 문장만 뺀다.

    근거는 문장이 단 fact가 아니라 메모 전체로 넓게 본다. 감성·장면 문장은 건드리지 않는다.
    """
    facts = analysis.get("facts") or []
    cited = [_N(f.get("quote")) for f in facts] + memo["n"]
    scenes = [_N(f.get("quote")) for f in facts if f.get("kind") == "seller_scene"]

    def hits(text, is_info=False):
        found = [code for code, _ in check_banned(text, cited, memo, scenes) if code in LIGHT_CODES]
        if is_info:
            # 실무 정보 줄에는 금액이 들어가야 하므로 지어낸 숫자만 본다.
            return [code for code in found if code == "NUMBER"]
        if MONEY.search(text):
            found.append("MONEY")
        if COST_LOW.search(text) or LIGHT_FOUND.search(text):
            found.append("COST_LOW")
        return found

    removed = {}
    kept = []
    for sentence in story.get("sentences") or []:
        if not isinstance(sentence, dict):
            continue
        codes = hits(_O(sentence.get("text")), sentence.get("role") == "info")
        if codes:
            removed[codes[0]] = removed.get(codes[0], 0) + 1
            continue
        kept.append(sentence)
    story = dict(story, sentences=kept)

    headline = _O(story.get("headline"))
    if headline and (hits(headline) or HEADLINE_NEGATIVE.search(headline)):
        # 제목이 걸리면 상품명으로 바꾼다.
        story["headline"] = (analysis.get("product") or {}).get("name") or headline
        removed["HEADLINE"] = 1
    stats["light_deleted"] = removed
    return story


def _run_engine(client, raw_input, scenario_mode, seller_additions, deadline, stats):
    memo = _memo_context(raw_input, seller_additions, scenario_mode)
    analysis = call_structured(
        client,
        ANALYZER_PROMPT,
        {
            "scenario_mode": scenario_mode,
            "raw_input": raw_input,
            "seller_additions": seller_additions
        },
        "analyzer",
        ANALYZER_SCHEMA,
        deadline,
        stats,
        effort=ANALYZER_EFFORT,
        model=ANALYZER_MODEL
    )

    analysis, stop = clean_analysis(analysis, memo, stats)
    if stop:
        return stop

    writer_input = {
        "raw_input": raw_input,
        "seller_additions": seller_additions,
        "analysis": analysis
    }
    story = call_structured(
        client, WRITER_PROMPT, writer_input, "writer", WRITER_SCHEMA, deadline, stats
    )
    checked = check_story(story, analysis, memo)
    stats["deleted"] = dict(checked["deleted"])
    stats["signals"] = [code for _, code in checked["signals"]] + (
        ["NO_CHARM"] if checked["no_charm"] else []
    )
    stats["rewrite"] = False

    if CHECK_MODE == "report":
        return _report_only(story, analysis, checked, stats)
    if CHECK_MODE == "light":
        return _report_only(_light_check(story, analysis, memo, stats), analysis, checked, stats)

    codes = needs_rewrite(checked)
    if codes:
        stats["rewrite_codes"] = codes
        remaining = deadline - time.monotonic()
        max_tokens = MAX_TOKENS
        if remaining < REWRITE_MIN_SECONDS and "LOST_FACT" in codes and (
            remaining >= REWRITE_LOST_FACT_SECONDS
        ):
            # 판매 기간·가격이 사라진 글보다 짧은 재작성이 낫다.
            max_tokens = REWRITE_LOST_FACT_MAX_TOKENS
            stats["rewrite_short"] = True
        elif remaining < REWRITE_MIN_SECONDS:
            max_tokens = None
        if max_tokens is None:
            stats["rewrite_skipped"] = "time"
        else:
            try:
                second = call_structured(
                    client,
                    WRITER_PROMPT,
                    {
                        **writer_input,
                        "previous": story,
                        "rewrite_reasons": checked["reasons"]
                    },
                    "rewrite",
                    WRITER_SCHEMA,
                    deadline,
                    stats,
                    max_tokens
                )
                stats["rewrite"] = True
                # 2차는 A·B 삭제와 자동 수정만 적용한다. C 신호는 로그로만 남긴다.
                checked = check_story(second, analysis, memo)
                stats["deleted_2"] = dict(checked["deleted"])
                stats["signals_2"] = [code for _, code in checked["signals"]] + (
                    ["NO_CHARM"] if checked["no_charm"] else []
                )
            except Exception as error:
                # 재작성이 실패하면 1차 결과를 정리해 내보낸다.
                stats["rewrite_error"] = _error_info(error)

    result = finalize(checked)
    stats["deleted_final"] = dict(checked["deleted"])
    stats["ratio_over"] = bool(checked.get("ratio_over"))
    stats["sentences"] = len(checked["kept"])
    stats["headline_fallback"] = not checked["headline_ok"]
    stats["product_gaps"] = checked.get("product_gaps") or []
    stats["roles"] = {
        role: sum(s.get("role") == role for s in checked["kept"])
        for role in ("fact", "charm", "scene", "ending")
    }
    stats["roles"]["info"] = int(bool(checked.get("info")))
    stats.update(checked["fixes"])
    return result


# 앱인토스 미니앱(appName lepi)은 토스 도메인에서 이 API를 부른다. 그 출처만 허용한다.
ALLOWED_ORIGINS = {
    "https://lepi.apps.tossmini.com",
    "https://lepi.private-apps.tossmini.com"
}


class handler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(
                self.headers.get("Content-Length", 0)
            )

            if content_length > MAX_BODY_BYTES:
                self.send_json(
                    413,
                    {
                        "error": TOO_LONG_MESSAGE
                    }
                )
                return

            request_body = self.rfile.read(content_length)
            request_data = json.loads(request_body)

            original_text = request_data.get("text", "").strip()

            if not original_text:
                self.send_json(
                    400,
                    {
                        "error": "상품 메모를 입력해 주세요."
                    }
                )
                return

            if len(original_text) > MAX_TEXT_LENGTH:
                self.send_json(
                    413,
                    {
                        "error": TOO_LONG_MESSAGE
                    }
                )
                return

            api_key = os.environ.get("ANTHROPIC_API_KEY")

            if not api_key:
                self.send_json(
                    500,
                    {
                        "error": "Claude API 키가 설정되지 않았습니다."
                    }
                )
                return

            client = anthropic.Anthropic(api_key=api_key)

            mode = request_data.get("mode")
            scenario_mode = (
                SCENARIO_BY_MODE.get(mode, SCENARIO_MODE)
                if isinstance(mode, str)
                else SCENARIO_MODE
            )

            self.send_json(
                200,
                run_story_engine(client, original_text, scenario_mode)
            )

        # UTF-8이 아닌 본문(예: 윈도우 터미널의 CP949)은 json.loads에서
        # UnicodeDecodeError가 난다. 이것도 요청 쪽 잘못이라 400으로 돌린다.
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(
                400,
                {
                    "error": "요청 데이터 형식이 올바르지 않습니다."
                }
            )

        # 오류 종류는 run_story_engine의 lepi_run 로그에 남는다.
        # 오류 메시지에는 입력이 섞일 수 있어 따로 찍지 않는다.
        except Exception:

            self.send_json(
                500,
                {
                    "error": "이야기를 입히는 중 오류가 발생했습니다."
                }
            )

    def send_json(self, status_code, data):
        response_body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status_code)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(response_body))
        )
        self.send_cors_headers()

        self.end_headers()
        self.wfile.write(response_body)
