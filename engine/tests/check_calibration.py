"""B·C 정규식 보정 (API 호출 없음).

(a) 조사의 사람 글(research/raw/captions.md, instagram.md, [제외] 빼고)을
    '걸리면 안 되는' 세트로 돌려 코드별로 몇 개 글에서 걸리는지 센다.
    - B 그대로: 메모·근거 없이 돌린 탐지 폭(정규식이 얼마나 넓은지)
    - B 근거 있음: 글 자체를 메모이자 근거로 두고 돌린 값(면제가 제대로 도는지, 0이어야 한다)
    - C: 메모 없이 돌린 값(H 등급은 5% 이하가 목표)
(b) review.md의 오탐·구멍 예시를 단위 사례로 돌린다.

    python engine/tests/check_calibration.py          # 요약 출력 + calibration.md 저장
    python engine/tests/check_calibration.py --show   # 걸린 조각을 터미널에만 출력(보정용)

calibration.md에는 개수와 코드만 쓴다. 사람 글 원문은 옮기지 않는다.
"""
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "api"))
# 검사 함수 자체를 보는 테스트라 지우기·다듬기를 실제로 적용하는 enforce로 둔다.
os.environ["LEPI_CHECK_MODE"] = "enforce"

import index  # noqa: E402

RAW = ROOT / "engine" / "research" / "raw"
OUT = Path(__file__).resolve().parent / "calibration.md"
EMPTY = index._memo_context("", [])


def load_captions(path):
    """'### ' 절마다 첫 코드 블록을 캡션으로 읽는다. [제외] 절은 따로 돌려준다."""
    text = path.read_text(encoding="utf-8")
    kept, excluded = [], []
    for section in re.split(r"^### ", text, flags=re.M)[1:]:
        block = re.search(r"```\n(.*?)```", section, re.S)
        if not block:
            continue
        (excluded if "[제외" in section else kept).append(block.group(1))
    return kept, excluded


def split_sentences(caption):
    parts = []
    for line in caption.splitlines():
        parts += re.split(r"(?<=[.!?。~])\s+", line)
    # 엔진처럼 이모지·해시태그를 먼저 지운다. 한 어절짜리 줄("꽃다발", "주세요")은
    # 품목 표기라 Writer 문장과 비교할 대상이 아니어서 뺀다.
    cleaned = (index._O(index.EMOJI.sub("", p)) for p in parts)
    return [p for p in cleaned if len(index._words(p)) >= 2]


def run_captions(captions, show=False):
    raw_b, grounded_b, c_codes = Counter(), Counter(), Counter()
    h_any = s_two = 0
    for caption in captions:
        sentences = split_sentences(caption)
        memo = index._memo_context(caption, [])
        cited = [index._N(caption)]
        raw_codes, grounded_codes = set(), set()
        for sentence in sentences:
            hits = index.check_banned(sentence, [], EMPTY)
            raw_codes |= {code for code, _ in hits}
            if show and hits:
                print("  B", hits)
            grounded = index.check_banned(sentence, cited, memo, cited)
            grounded_codes |= {code for code, _ in grounded}
            if show and grounded:
                print("  B근거", grounded)
        signals = index.machine_signals(sentences, EMPTY)
        if show and signals:
            print("  C", signals)
        raw_b.update(raw_codes)
        grounded_b.update(grounded_codes)
        c_codes.update({code for _, code in signals})
        grades = [g for g, _ in signals]
        h_any += "H" in grades
        s_two += grades.count("S") >= 2
    return raw_b, grounded_b, c_codes, h_any, s_two


# ── 단위 사례 (review.md) ──
def banned(text, memo_text="", cited_texts=()):
    memo = index._memo_context(memo_text, [])
    return {code for code, _ in index.check_banned(
        text, [index._N(c) for c in cited_texts], memo, [index._N(c) for c in cited_texts]
    )}


def signals(sentences):
    return {code for _, code in index.machine_signals(sentences, EMPTY)}


def story_codes(memo_text, facts, sentences, ending="promise", mode="REAL_SELLER",
                product=None, price_display=None, full=False, extra=None, headline_ids=()):
    """facts: [(id, quote, kind[, convertible_to])], sentences: [(text, ids, interpretation)]

    analysis 정리(clean_analysis)를 거친 뒤 검사한다. full이면 check_story 결과 전체.
    """
    memo = index._memo_context(memo_text, [], mode)
    analysis = {
        "facts": [{"id": i, "quote": q, "kind": k, "convertible_to": c}
                  for i, q, k, *rest in facts for c in [rest[0] if rest else None]],
        "ending": {"type": ending, "fact_ids": []},
        "product": product or {"name": "상품", "name_fact_id": None, "price_fact_id": None},
        "distinctive_phrases": [], "sensory_hook": None,
        "seller_scene": None, "story_readiness": "NO_STORY_FOUND", "questions": [],
        "charm": None, "common_knowledge": [], "season": None,
        **(extra or {})
    }
    analysis, _ = index.clean_analysis(analysis, memo, {})
    story = {
        "product_card": {"name": "상품", "price_display": price_display},
        "sentences": [
            {"paragraph": 1, "text": t, "fact_ids": ids, "interpretation": interp,
             "is_ending": n == len(sentences) - 1, **({"role": rest[0]} if rest else {})}
            for n, (t, ids, interp, *rest) in enumerate(sentences)
        ],
        "headline": "",
        "headline_fact_ids": list(headline_ids)
    }
    checked = index.check_story(story, analysis, memo)
    return checked if full else checked["deleted"]


def gate(memo_text, facts, scene_ids, readiness="READY", name="상품"):
    memo = index._memo_context(memo_text, [])
    analysis = {
        "facts": [{"id": i, "quote": q, "kind": k, "convertible_to": None} for i, q, k in facts],
        "product": {"name": name, "name_fact_id": None, "price_fact_id": None},
        "seller_scene": {"fact_ids": scene_ids, "note": ""} if scene_ids is not None else None,
        "distinctive_phrases": [], "sensory_hook": None,
        "story_readiness": readiness, "questions": []
    }
    _, stop = index.clean_analysis(analysis, memo, {})
    return (stop or {}).get("status", "READY")


SOAP = "쌀뜨물 비누. 엄마가 예전에 쌀뜨물로 세수하던 게 생각나서 만들어봤어요. 거품이 크진 않은데 뽀득하게 씻겨요"
HAT = "아기 모자. 겉실을 면으로 해서 안 따가워요. 저희 애가 귀 시려워해서 귀까지 덮이게 길게 떴어요. 색은 회색, 겨자색"
MUG = """상품 칸: 유약 흘림 머그컵 / 32,000원

용량은 350정도? 손잡이는 좀 두껍게 만들었어요 제가 손이 작아서 얇으면 불안하더라구요

아 그리고 지난주에 단골분이 하나 미리 가져가셨는데 이거에 커피마시면 맛이 다른거 같다고 하셔서 웃었어요 ㅋㅋ 그럴리가요..

전자렌지 식세기 되고요 주문하면 같은 모양은 절대 안나와요 그건 감안해주세요!!"""
NAIL = "이번 달 시즌 네일은 단풍 그라데이션이에요. 저도 지금 하고 있는데 손 볼 때마다 기분 좋아요"
RICE = "무화과가 비싸서 첨엔 6천원 받으려다가 동네 어르신들 사가시라고 4500원으로 맞췄음."
BELL = "선운사 종은 만원인데 소원나무에 저렇게 대부분 가족의 건강과 성공을 기원하는 거라 나도 시댁어른이랑 남편이랑 간 김에 구매했어."
ROCK = "아직 판매는 안하고 준비중임. 한탄강 갔을때 주운 돌이 동글동글해서 눈 붙여서 책상에 뒀는데"

FIG = "우리 떡집은 원래 팥찹쌀떡만 했는데 딸이 요즘 과일찹쌀떡 유행이라고 해보자고 해서 시작함. 무화과가 비싸서 첨엔 6천원 받으려다가 동네 어르신들 사가시라고 4500원으로 맞췄음. 대신 무화과 철 끝나는 11월 중순까지만 함. 줄 서서 사는 그런 데 아니고 그냥 아침에 만들어서 다 팔리면 끝"
ROCK_FULL = "상품 칸: 이름 지어주는 반려돌 키트 (판매 준비 중)  가격 미정\n\n아직 판매는 안하고 준비중임. 한탄강 갔을때 주운 돌이 동글동글해서 눈 붙여서 책상에 뒀는데 회사에서 힘들때 쳐다보면 웃겨서 좀 나아짐. 그래서 돌이랑 눈스티커랑 이름표 넣어서 키트로 팔아볼까 생각중. 돌은 직접 주워서 씻어서 넣을거"
KARP = "남편이랑 포켓몬팝업이 있다고 해서 놀러갔더니 잉어킹액막이가 있더라고 그런데 가챠로밖에 안팔아서 만원이라는 큰 금액이어도 한번 도전해봤더니 성공해서 한번에 뽑았어"
FIG_FACTS = [("F1", "무화과 철 끝나는 11월 중순까지만 함.", "how_to_buy"),
             ("F2", "아침에 만들어서 다 팔리면 끝", "how_to_buy")]
FIG_PRODUCT = {"name": "무화과 찹쌀떡", "name_fact_id": "P1", "price_fact_id": None}


def kept_texts(memo_text, facts, sentences, product=None, mode="REAL_SELLER"):
    checked = story_codes(memo_text, facts, sentences, product=product, mode=mode, full=True)
    return [k["text"] for k in checked["kept"]]


MUG_SCENE = "이번에 가마 새로 돌린거 나왔는데요 ㅠㅠ 유약이 생각보다 많이 흘러내려서 첨엔 망했다 싶었는데 꺼내놓고 보니까 컵마다 흐른 모양이 다 달라요.."
MUG_SCENE_FACTS = [("F1", "이번에 가마 새로 돌린거 나왔는데요", "seller_scene"),
                   ("F2", "유약이 생각보다 많이 흘러내려서", "seller_scene"),
                   ("F3", "꺼내놓고 보니까 컵마다 흐른 모양이 다 달라요..", "product")]

BERRY = "우리 가게 딸기 케이크는 제철 딸기만 써요. 겨울에만 나와서 그런지 단골분들이 겨울 되면 먼저 물어보세요."
BERRY_FACTS = [("F1", "우리 가게 딸기 케이크는 제철 딸기만 써요.", "seller_scene"),
               ("F2", "겨울에만 나와서 그런지 단골분들이 겨울 되면 먼저 물어보세요.", "customer_fact")]


def cleaned(memo_text, extra, facts):
    memo = index._memo_context(memo_text, [])
    analysis = {
        "facts": [{"id": i, "quote": q, "kind": k, "convertible_to": None} for i, q, k in facts],
        "product": {"name": "상품", "name_fact_id": None, "price_fact_id": None},
        "distinctive_phrases": [], "sensory_hook": None, "seller_scene": None,
        "story_readiness": "NO_STORY_FOUND", "questions": [],
        "charm": None, "common_knowledge": [], "season": None, **extra
    }
    stats = {}
    analysis, _ = index.clean_analysis(analysis, memo, stats)
    return analysis, stats


def headline_ok(memo_text, headline):
    facts = [("F1", "무화과 철 끝나는 11월 중순까지만 함.", "how_to_buy"),
             ("F2", "첨엔 6천원 받으려다가 동네 어르신들 사가시라고 4500원으로 맞췄음.", "seller_scene"),
             ("P1", "과일찹쌀떡", "product")]
    memo = index._memo_context(memo_text, [])
    analysis = {
        "facts": [{"id": i, "quote": q, "kind": k, "convertible_to": None} for i, q, k in facts],
        "product": {"name": "무화과 찹쌀떡", "name_fact_id": "P1", "price_fact_id": None},
        "distinctive_phrases": [], "sensory_hook": None, "seller_scene": None,
        "story_readiness": "NO_STORY_FOUND", "questions": [],
        "charm": None, "common_knowledge": [], "season": None, "ending": {"type": "promise", "fact_ids": []}
    }
    analysis, _ = index.clean_analysis(analysis, memo, {})
    story = {"product_card": {"name": "무화과 찹쌀떡", "price_display": None},
             "sentences": [{"paragraph": 1, "text": "무화과 철 끝나는 11월 중순까지만 해요.", "fact_ids": ["F1"],
                            "interpretation": False, "is_ending": True, "role": "fact"}],
             "headline": headline, "headline_fact_ids": ["F1", "F2", "P1"]}
    return index.check_story(story, analysis, memo)["headline_ok"]


FIG_INFO_FACTS = FIG_FACTS + [("F3", "동네 어르신들 사가시라고 4500원으로 맞췄음.", "price"),
                              ("P1", "과일찹쌀떡", "product")]
FIG_INFO_PRODUCT = {"name": "무화과 찹쌀떡", "name_fact_id": "P1", "price_fact_id": "F3"}

def gate_v2(memo_text, mode, facts, product, charm=None, knowledge=(), readiness="READY"):
    memo = index._memo_context(memo_text, [], mode)
    analysis = {
        "facts": [{"id": i, "quote": q, "kind": k, "convertible_to": c} for i, q, k, c in facts],
        "product": product, "seller_scene": None,
        "distinctive_phrases": [], "sensory_hook": None,
        "charm": charm, "common_knowledge": list(knowledge), "season": None,
        "story_readiness": readiness, "questions": []
    }
    _, stop = index.clean_analysis(analysis, memo, {})
    return (stop or {}).get("status", "READY")


UNIT_CASES = [
    # (설명, 통과 조건 람다)
    ("NUMBER 관용: 이번 한 주도 따뜻하게 보내세요", lambda: not banned("이번 한 주도 따뜻하게 보내세요")),
    ("NUMBER 관용: 제가 한 일이에요", lambda: "NUMBER" not in banned("제가 한 일이에요")),
    ("NUMBER 탐지: 두 가지 색이 있어요", lambda: "NUMBER" in banned("두 가지 색이 있어요")),
    ("NUMBER 메모 금액: 2만2천원 / 메모 22,000원", lambda: "NUMBER" not in banned("2만2천원이에요", "머그 22,000원")),
    ("NUMBER 메모에 없는 금액: 6천원", lambda: "NUMBER" in banned("6천원이에요", "4500원으로 맞췄음")),
    ("PERIOD 탐지: 하루면 펴요", lambda: "PERIOD" in banned("하루면 펴요")),
    ("PERIOD 근거 있음: 하루이틀이면 펴요", lambda: "PERIOD" not in banned("하루이틀이면 확 펴요", "하루이틀이면 확 펴요", ["하루이틀이면 확 펴요"])),
    ("PERIOD 인사 통과: 좋은 하루 보내세요", lambda: not banned("좋은 하루 보내세요")),
    ("ORIGIN: 10,000원은 100%가 아니다", lambda: "ORIGIN" not in banned("10,000원이에요", "10,000원")),
    ("ORIGIN: 인증샷 통과", lambda: "ORIGIN" not in banned("인증샷 남겨 주세요")),
    ("ORIGIN: 수제비 통과", lambda: "ORIGIN" not in banned("수제비 생각나는 날씨예요")),
    ("ORIGIN 탐지: 100% 국내산", lambda: "ORIGIN" in banned("100% 국내산이에요")),
    ("EFFICACY: 햇볕 막아 줘요 통과", lambda: "EFFICACY" not in banned("햇볕 막아 줘요")),
    ("EFFICACY: 폰을 지켜 줘요 통과", lambda: "EFFICACY" not in banned("폰을 지켜 줘요")),
    ("EFFICACY: 기분이 좋아져요 통과", lambda: "EFFICACY" not in banned("기분이 좋아져요")),
    ("EFFICACY: 탄력 있는 쿠션 통과", lambda: "EFFICACY" not in banned("탄력 있는 쿠션이에요")),
    ("EFFICACY 탐지: 액운을 막아 줘요", lambda: "EFFICACY" in banned("액운을 막아 줘요")),
    ("EFFICACY 탐지: 피부가 좋아져요", lambda: "EFFICACY" in banned("피부가 좋아져요")),
    ("EFFICACY 근거 있음: 소원이 이루어진것 같더라(메모)", lambda: "EFFICACY" not in banned(
        "소원이 이루어진 것 같더라고요", "꼭 소원이 이루어진것 같더라", ["꼭 소원이 이루어진것 같더라"])),
    ("SOCIAL: 다들 감기 조심하세요 통과", lambda: "SOCIAL" not in banned("다들 감기 조심하세요")),
    ("SOCIAL: 냥이 반응이 달라요 통과", lambda: "SOCIAL" not in banned("냥이 반응이 달라요")),
    ("SOCIAL 탐지: 다들 좋아하세요", lambda: "SOCIAL" in banned("다들 좋아하세요")),
    ("SOCIAL 탐지: 금방 다 나갔어요", lambda: "SOCIAL" in banned("금방 다 나갔어요")),
    ("SOCIAL 탐지: 줄 서는 떡집 (메모는 '줄 서서 사는 그런 데 아니고')", lambda: "SOCIAL" in banned(
        "줄 서는 떡집이에요", "줄 서서 사는 그런 데 아니고")),
    ("SOCIAL 탐지: 완판", lambda: "SOCIAL" in banned("어제 완판됐어요")),
    ("EXCLUSIVE: 눈으로만 봐도 예뻐요 통과", lambda: "EXCLUSIVE" not in banned("눈으로만 봐도 예뻐요")),
    ("EXCLUSIVE: 집에서만 쓰기 아까워요 통과", lambda: "EXCLUSIVE" not in banned("집에서만 쓰기 아까워요")),
    ("EXCLUSIVE: 마지막 한 입까지 통과", lambda: "EXCLUSIVE" not in banned("마지막 한 입까지 맛있어요")),
    ("EXCLUSIVE 탐지: 여기서만 팔아요", lambda: "EXCLUSIVE" in banned("여기서만 팔아요")),
    ("EXCLUSIVE 탐지: 마지막 수량이에요", lambda: "EXCLUSIVE" in banned("마지막 수량이에요")),
    ("EXCLUSIVE 탐지: 단 하나뿐인 머그 (메모 '같은 모양은 절대 안나와요')", lambda: "EXCLUSIVE" in banned(
        "단 하나뿐인 머그예요", "같은 모양은 절대 안나와요", ["같은 모양은 절대 안나와요"])),
    ("PROPER: 좋아하시는·앞접시·문방구·놀이기구·양우산·사용시 통과", lambda: "PROPER" not in banned(
        "좋아하시는 앞접시 문방구 놀이기구 양우산 사용시")),
    ("PROPER: 마음씨·아가씨·아저씨·추운날씨 통과", lambda: "PROPER" not in banned("마음씨 아가씨 아저씨 추운날씨")),
    ("PROPER 탐지: 제주 감귤처럼 맛있어요", lambda: "PROPER" in banned("제주 감귤처럼 맛있어요", "귤 맛있어요")),
    ("PROPER 탐지: 성수 팝업에서", lambda: "PROPER" in banned("성수 팝업에서 만났어요")),
    ("PROPER 메모에 있음: 한탄강", lambda: "PROPER" not in banned("한탄강에서 주운 돌이에요", "한탄강 갔을때 주운 돌")),
    ("PROPER 탐지: 350ml (메모 '350정도?')", lambda: "PROPER" in banned("용량은 350ml예요", "용량은 350정도?")),
    ("SERVICE 탐지: 내일 또 구워 둘게요", lambda: "SERVICE" in banned("내일 또 구워 둘게요")),
    ("SERVICE 탐지: 포장해서 보내 드려요", lambda: "SERVICE" in banned("포장해서 보내 드려요")),
    ("SERVICE: 보여/챙겨/알려 드릴게요 통과", lambda: not banned("보여 드릴게요 챙겨 둘게요 알려 드릴게요")),
    ("SERVICE 탐지: 지금 주문하세요 (메모 '판매 준비 중')", lambda: "SERVICE" in banned("지금 주문하세요", "판매 준비 중")),
    ("MATERIAL 탐지: 원목이라 따뜻해요", lambda: "MATERIAL" in banned("원목이라 따뜻해요")),
    ("MATERIAL 탐지: 버터 향이 나요", lambda: "MATERIAL" in banned("버터 향이 나요")),
    ("MATERIAL 메모에 있음: 면으로 떠서", lambda: "MATERIAL" not in banned("면으로 떠서 따갑지 않아요", HAT)),
    ("C STEM_REPEAT: 좋아요…좋아하는 통과", lambda: "STEM_REPEAT" not in signals(["좋아요.", "고양이가 좋아하는 장난감이에요."])),
    ("C SAME_LAST: 만들었어요. 써 봤어요. 좋았어요. 통과", lambda: "SAME_LAST" not in signals(["만들었어요.", "써 봤어요.", "좋았어요."])),
    ("C LIST3: 확인하고 포장하고 보내요 통과", lambda: "LIST3" not in signals(["확인하고 포장하고 보내요."])),
    ("C 만나보세요 → H CLICHE", lambda: "CLICHE" in signals(["새 머그를 만나보세요."])),
    ("C ABSTRACT_REPEAT: 특별 2회", lambda: "ABSTRACT_REPEAT" in signals(["특별한 날에.", "특별하게 드려요."])),
    ("A1 탐지: '안 따가워요'에서 '따가워요'만 자른 quote", lambda: not index._quote_ok("따가워요", index._memo_context(HAT, []))),
    ("A1: '안 따가워요' 통째 quote 통과", lambda: index._quote_ok("안 따가워요", index._memo_context(HAT, []))),
    ("A1 탐지: '효과는 없지만'에서 '효과'", lambda: not index._quote_ok("효과", index._memo_context("효과는 없지만 향이 좋아요", [])))
    ,
    ("A1 탐지: '줄 서서 사는'만 자른 quote", lambda: not index._quote_ok(
        "줄 서서 사는 그런 데", index._memo_context("줄 서서 사는 그런 데 아니고 그냥", []))),
    ("A1: 띄어쓰기 다른 quote 통과", lambda: index._quote_ok("쌀뜨물 비누", index._memo_context(SOAP, []))),
    ("A1 탐지: 어절 중간에서 자른 quote", lambda: not index._quote_ok("뜨물 비누", index._memo_context(SOAP, []))),
    ("A4 탐지: 새벽에 작업하다 만들었어요 (메모 '만들어봤어요')", lambda: "SELLER_UNGROUNDED" in story_codes(
        SOAP, [("F1", "만들어봤어요", "seller_scene")], [("새벽에 작업하다 만들었어요.", ["F1"], True)])),
    ("A4 통과: 엄마 생각이 나서 만들어 봤어요", lambda: not story_codes(
        SOAP, [("F1", "엄마가 예전에 쌀뜨물로 세수하던 게 생각나서 만들어봤어요", "seller_scene")],
        [("엄마가 쌀뜨물로 세수하던 게 생각나서 만들어 봤어요.", ["F1"], False)])),
    ("A2 탐지: 제주 감귤처럼 맛있어요 (메모엔 '맛있어요'만)", lambda: story_codes(
        "아메리카노 4500원 맛있어요", [("F1", "맛있어요", "seller_feeling")],
        [("제주 감귤처럼 맛있어요.", ["F1"], False)])),
    ("A2 통과: 예시 B '겉실을 면으로 떠서 따갑지 않아요'", lambda: not story_codes(
        HAT, [("F2", "겉실을 면으로 해서 안 따가워요", "product")],
        [("겉실을 면으로 떠서 따갑지 않아요.", ["F2"], False)])),
    ("A2 통과: 활용형 차이(돌린→돌렸, 첨→처음 1개)", lambda: not story_codes(
        "이번에 가마 새로 돌린거 나왔는데요 ㅠㅠ 유약이 생각보다 많이 흘러내려서 첨엔 망했다 싶었는데",
        [("F1", "이번에 가마 새로 돌린거 나왔는데요", "seller_scene"),
         ("F2", "유약이 생각보다 많이 흘러내려서 첨엔 망했다 싶었는데", "seller_scene")],
        [("이번에 가마를 새로 돌렸는데, 유약이 생각보다 많이 흘러내려서 처음엔 망했다 싶었는데요.", ["F1", "F2"], False)])),
    ("A2 통과: '끝이고·하니'는 내용 어간이 아니다", lambda: not story_codes(
        "대신 무화과 철 끝나는 11월 중순까지만 함. 그냥 아침에 만들어서 다 팔리면 끝",
        [("F1", "아침에 만들어서 다 팔리면 끝", "how_to_buy"), ("F2", "무화과 철 끝나는 11월 중순까지만 함.", "how_to_buy")],
        [("아침에 만들어서 다 팔리면 끝이고, 무화과 철이 끝나는 11월 중순까지만 하니 그 전에 들러 주세요.", ["F1", "F2"], False)])),
    ("A3 탐지: 사실 문장에 fact 없음", lambda: "NO_FACT" in story_codes(
        SOAP, [], [("거품이 커요.", [], False)])),
    ("A5 탐지: 가챠로 한 번에 뽑혔어요", lambda: "BUYER_RESTATE" in story_codes(
        "가챠로밖에 안팔아서 한번 도전해봤더니 성공해서 한번에 뽑았어",
        [("F1", "한번 도전해봤더니 성공해서 한번에 뽑았어", "buyer_action", "한 번 도전해 보셔도 좋아요")],
        [("가챠로 한 번에 뽑혔어요.", ["F1"], False)])),
    ("A6 탐지: info 끝맺음에 구매 fact 없음", lambda: "ENDING_INFO" in story_codes(
        SOAP, [("F1", "쌀뜨물 비누", "product")],
        [("쌀뜨물 비누예요.", ["F1"], False), ("언제든 찾아 주세요.", [], True)], ending="info")),
    # ── run1 반영 (score.md, 설계 9절) ──
    ("A4 통과: 저도…기분이 좋더라고요 (seller_feeling)", lambda: not story_codes(
        NAIL, [("F1", "저도 지금 하고 있는데 손 볼 때마다 기분 좋아요", "seller_feeling")],
        [("저도 지금 하고 있는데, 손 볼 때마다 기분이 좋더라고요.", ["F1"], False)])),
    ("표기 변형 통과: 전자레인지와 식세기 모두 됩니다 (메모 '전자렌지 식세기')", lambda: not story_codes(
        MUG, [("F1", "전자렌지 식세기 되고요", "product")], [("전자레인지와 식세기 모두 됩니다.", ["F1"], False)])),
    ("SHOP_INVENT 탐지: 저희 가게에서 알려 드릴게요 (메모에 가게 없음)", lambda: "SHOP_INVENT" in story_codes(
        ROCK, [("F1", "한탄강 갔을때 주운 돌이", "seller_scene")],
        [("한탄강에서 주운 돌이에요.", ["F1"], False), ("준비가 끝나면 저희 가게에서 알려 드릴게요.", [], True)])),
    ("SHOP_INVENT 통과: 메모에 떡집 → 저희 떡집", lambda: "SHOP_INVENT" not in banned(
        "저희 떡집에서 아침에 만들어요", "우리 떡집은 원래 팥찹쌀떡만 했는데")),
    ("DEMO_BUYER 탐지: 간 김에 하나 구매했어요 (DEMO)", lambda: "DEMO_BUYER" in story_codes(
        BELL, [("F1", "선운사 종은 만원인데", "price")], [("가족과 간 김에 선운사 종을 하나 들였어요.", ["F1"], False)],
        mode="DEMO_SELLER")),
    ("HEDGE 탐지: 용량은 350이에요 (메모 '350정도?')", lambda: "HEDGE" in story_codes(
        MUG, [("F1", "용량은 350정도?", "product")], [("용량은 350이에요.", ["F1"], False)])),
    ("HEDGE 통과: 용량은 350 정도예요", lambda: not story_codes(
        MUG, [("F1", "용량은 350정도?", "product")], [("용량은 350 정도예요.", ["F1"], False)])),
    ("HEDGE 탐지: 단골분은 커피 맛이 다르대요 ('그럴리가요' 빠짐)", lambda: "HEDGE" in story_codes(
        MUG, [("F1", "이거에 커피마시면 맛이 다른거 같다고 하셔서 웃었어요", "customer_fact")],
        [("이 컵에 커피를 마시면 맛이 다른 것 같다고 하셔서 웃었어요.", ["F1"], False)])),
    ("HEDGE 통과: '그럴리가요'까지 같이 쓴 문장", lambda: not story_codes(
        MUG, [("F1", "이거에 커피마시면 맛이 다른거 같다고 하셔서 웃었어요 ㅋㅋ 그럴리가요", "customer_fact")],
        [("이 컵에 커피를 마시면 맛이 다른 것 같다고 하셔서 웃었어요. 그럴리가요.", ["F1"], False)])),
    ("가격 카드: 처음 생각한 6천원은 가격이 아니다", lambda: story_codes(
        RICE, [("F1", "4500원으로 맞췄음", "price"), ("F2", "첨엔 6천원 받으려다가", "seller_scene")],
        [("4500원으로 맞췄어요.", ["F1"], False)],
        product={"name": "무화과 찹쌀떡", "name_fact_id": None, "price_fact_id": "F1"},
        price_display="6천원", full=True)["price"] == ""),
    ("가격 카드: 가격 fact 금액은 통과", lambda: story_codes(
        RICE, [("F1", "4500원으로 맞췄음", "price")], [("4500원으로 맞췄어요.", ["F1"], False)],
        product={"name": "무화과 찹쌀떡", "name_fact_id": None, "price_fact_id": "F1"},
        price_display="4500원", full=True)["price"] == "4500원"),
    ("NO_PRODUCT_BODY: 상품·가격 문장이 지워지면 재작성", lambda: "NO_PRODUCT_BODY" in index.needs_rewrite(story_codes(
        BELL, [("F1", "선운사 종은 만원인데", "price"), ("F2", "가족의 건강과 성공을 기원하는", "product")],
        [("정말 효과가 좋은 선운사 종은 만원이에요.", ["F1", "F2"], False),
         ("가족의 건강과 성공을 기원하는 마음이 모여 있어요.", ["F2"], False)],
        product={"name": "선운사 소원의 종", "name_fact_id": "F1", "price_fact_id": "F1"}, full=True))),
    ("ENDING_INVITE: 들여 보세요로 끝나면 비율에 넣는다(기록만, 재작성 사유 아님)", lambda: (lambda c: index._ratio_state(c)[2]
        and "RATIO" not in index.needs_rewrite(c))(story_codes(
        NAIL, [("F1", "이번 달 시즌 네일은 단풍 그라데이션이에요", "product"),
               ("F2", "저도 지금 하고 있는데 손 볼 때마다 기분 좋아요", "seller_feeling")],
        [("이번 달 시즌 네일은 단풍 그라데이션이에요.", ["F1"], False),
         ("저도 지금 하고 있는데 손 볼 때마다 기분이 좋아요.", ["F2"], False),
         ("손끝에 가을이 조금 내려앉은 느낌이에요.", [], True),
         ("이번 가을엔 손끝에 단풍 하나 들여 보세요.", [], True)],
        ending="greeting", full=True))),
    # ── 절 다듬기·COST_LOW·상품명 상식 (rerun1) ──
    ("절 다듬기: 무화과 판매 기간 문장 (rerun1 원문)", lambda: any(
        "11월 중순" in t for t in kept_texts(FIG, FIG_FACTS, [(
            "무화과 철 끝나는 11월 중순까지만 하고, 아침에 만들어서 다 팔리면 끝이니 일찍 들러 주세요.",
            ["F1", "F2"], False)]))),
    ("절 다듬기: 뒤 절 위반(포장)만 떼고 '…끝이에요.'로 맺음", lambda: kept_texts(FIG, FIG_FACTS, [(
        "무화과 철 끝나는 11월 중순까지만 하고, 아침에 만들어서 다 팔리면 끝이니 포장해서 보내 드려요.",
        ["F1", "F2"], False)]) == ["무화과 철 끝나는 11월 중순까지만 하고, 아침에 만들어서 다 팔리면 끝이에요."]),
    ("절 다듬기: 맺을 수 없으면 예전처럼 삭제", lambda: kept_texts(FIG, FIG_FACTS, [(
        "포장해서 보내 드려요.", ["F1"], False)]) == []),
    ("절 다듬기 안 함: '~있다고 해서'는 '있다고 해요'로 맺지 않는다", lambda: index._close_clause("팝업이 있다고 해서") is None),
    ("절 다듬기 안 함: DEMO 구매담은 앞 절을 살리지 않는다", lambda: kept_texts(
        KARP, [],
        [("몇 달 뒤에 이사가 예정되어 있어서 꼭 가지고 싶었거든요.", [], True)], mode="DEMO_SELLER") == []),
    ("COST_LOW 탐지: 돌은 제가 직접 주워서 씻어 넣을 거고요", lambda: "COST_LOW" in story_codes(
        ROCK_FULL, [("F1", "돌은 직접 주워서 씻어서 넣을거", "seller_scene")],
        [("돌은 제가 직접 주워서 씻어 넣을 거고요.", ["F1"], False)])),
    ("COST_LOW 통과: 한탄강에 놀러 갔을 때 동글동글한 돌을 봤어요", lambda: "COST_LOW" not in story_codes(
        ROCK_FULL, [("F1", "한탄강 갔을때 주운 돌이 동글동글해서", "seller_scene")],
        [("한탄강에 놀러 갔을 때 동글동글한 돌을 봤어요.", ["F1"], False)])),
    ("COST_LOW 탐지: 공짜로 얻은 (메모 면제 없음)", lambda: "COST_LOW" in story_codes(
        "공짜로 얻은 천", [("F1", "공짜로 얻은 천", "seller_scene")], [("공짜로 얻은 천이에요.", ["F1"], False)])),
    ("상품명 상식 통과: 찹쌀떡 안에 무화과가 든 떡", lambda: not story_codes(
        FIG, [("P1", "과일찹쌀떡", "product")], [("무화과 찹쌀떡은 찹쌀떡 안에 무화과가 든 떡이에요.", ["P1"], True)],
        product=FIG_PRODUCT)),
    ("상품명 상식 통과: 머그컵은 커피나 차를 담아 마시는 컵", lambda: not story_codes(
        MUG, [("P1", "유약 흘림 머그컵", "product")], [("머그컵은 커피나 차를 담아 마시는 컵이죠.", ["P1"], True)],
        product={"name": "유약 흘림 머그컵", "name_fact_id": "P1", "price_fact_id": None})),
    ("상품명 상식 탐지: 쫀득한 식감 (메모에 없음)", lambda: "TASTE" in story_codes(
        FIG, [("P1", "과일찹쌀떡", "product")], [("무화과 찹쌀떡은 쫀득한 식감이 좋아요.", ["P1"], True)],
        product=FIG_PRODUCT)),
    ("상품명 상식 탐지: 350ml (사실 문장, 허용치 3이어도)", lambda: story_codes(
        MUG, [("P1", "유약 흘림 머그컵", "product")], [("머그컵 용량은 350ml예요.", ["P1"], False)],
        product={"name": "유약 흘림 머그컵", "name_fact_id": "P1", "price_fact_id": None})),
    ("상품명 상식 통과: 잉어킹은 원래 힘없는 캐릭터지만", lambda: not story_codes(
        KARP, [("P1", "잉어킹액막이가 있더라고", "product")],
        [("잉어킹은 원래 힘없는 캐릭터지만 버티다 보면 아주 센 캐릭터가 돼요.", ["P1"], True)],
        product={"name": "잉어킹액막이", "name_fact_id": "P1", "price_fact_id": None}, mode="DEMO_SELLER")),
    ("상품명 상식 탐지: 메모에 없는 '갸라도스'", lambda: "PROPER" in story_codes(
        KARP, [("P1", "잉어킹액막이가 있더라고", "product")],
        [("잉어킹은 버티다 보면 갸라도스가 돼요.", ["P1"], True)],
        product={"name": "잉어킹액막이", "name_fact_id": "P1", "price_fact_id": None}, mode="DEMO_SELLER")),
    # ── 이야기 문장 보호 (gap-audit A, prompt-plan) ──
    ("A4 감성 통과: 어떤 이름을 붙여 줄지 고민하는 시간도 재밌을 거예요", lambda: not story_codes(
        ROCK_FULL, [], [("어떤 이름을 붙여 줄지 고민하는 시간도 꽤 재밌을 거예요.", [], True)])),
    ("A4 감성 통과: 손님 장면의 '작업' (작업하시다 쉬실 때)", lambda: not story_codes(
        ROCK_FULL, [], [("작업하시다가 잠깐 쉬실 때 한 번 쳐다보세요.", [], True)])),
    ("A4 감성 탐지: 저는 새벽에 작업했어요 (1인칭이면 손님 높임이 있어도 봄)", lambda: "SELLER_UNGROUNDED" in story_codes(
        SOAP, [], [("저는 새벽에 작업하면서 손님들 생각을 하세요.", [], True)])),
    ("끝맺음: 물어보세요·문의 주세요는 invite가 아니다", lambda: not index._is_invite("궁금한 건 편하게 물어보세요.")
        and not index._is_invite("색상은 DM으로 문의 주세요.") and index._is_invite("손끝에 단풍 하나 들여 보세요.")),
    ("끝맺음 약속 통과: fact를 단 '준비가 끝나면 먼저 알려 드릴게요'", lambda: not story_codes(
        ROCK_FULL, [("F1", "아직 판매는 안하고 준비중임.", "how_to_buy")],
        [("준비가 끝나면 여기서 먼저 알려 드릴게요.", ["F1"], False)])),
    ("끝맺음 약속 탐지: 내일 포장해서 보내 드릴게요 (SERVICE는 그대로)", lambda: "SERVICE" in story_codes(
        ROCK_FULL, [("F1", "아직 판매는 안하고 준비중임.", "how_to_buy")],
        [("준비되면 내일 포장해서 보내 드릴게요.", ["F1"], False)])),
    ("NO_ADDRESS 통과: ~실 거예요 / ~주세요", lambda: "NO_ADDRESS" not in signals(["좋은 하루 되실 거예요."])
        and "NO_ADDRESS" not in signals(["편하게 연락 주세요."])),
    ("A2 허용치: fact 3개를 합친 문장은 메모 밖 어간 2개까지", lambda: not story_codes(
        MUG_SCENE, MUG_SCENE_FACTS, [("이번 가마에서 유약이 흘러내려 컵마다 무늬가 제각각이에요.", ["F1", "F2", "F3"], False)])),
    ("A2 허용치: fact 1개면 메모 밖 어간 1개까지", lambda: "UNGROUNDED" in story_codes(
        MUG_SCENE, MUG_SCENE_FACTS, [("이번 가마에서 유약이 흘러내려 컵마다 무늬가 제각각이에요.", ["F2"], False)])),
    ("재작성 사유: 다른 문장에 없는 fact id를 LOST_FACT로 넘김", lambda: any(
        r["code"] == "LOST_FACT" and r["fact_ids"] == ["F1"] and "facts=F1" in r["detail"] for r in story_codes(
            FIG, FIG_FACTS, [("포장해서 보내 드려요.", ["F1"], False), ("아침에 만들어서 다 팔리면 끝이에요.", ["F2"], False)],
            full=True)["reasons"])),
    # ── 스키마 개편 (code-requests.md) ──
    ("정리: charm fact가 모두 무효면 charm=None, season 무효면 None", lambda: (lambda a: a["charm"] is None and a["season"] is None)(
        cleaned(SOAP, {"charm": {"fact_ids": ["F9"], "note": ""}, "season": {"fact_id": "F9", "note": ""}},
                [("F1", "쌀뜨물 비누", "product")])[0])),
    ("정리: common_knowledge — 메모 밖 대상·수치·새 이름은 버리고 3개까지", lambda: (lambda r: len(r[0]["common_knowledge"]) == 1 and r[1]["ck_dropped"] == 3)(
        cleaned(KARP, {"common_knowledge": [
            {"about": "잉어킹", "note": "잉어킹은 힘이 약한 캐릭터지만 버티면 센 캐릭터가 된다"},
            {"about": "피카츄", "note": "피카츄는 전기 캐릭터다"},
            {"about": "잉어킹", "note": "잉어킹은 20레벨에 진화한다"},
            {"about": "잉어킹", "note": "잉어킹은 버티면 갸라도스가 된다"}]}, [])),
    ),
    ("charm 감성 문장: common_knowledge 설명을 근거로 통과", lambda: not story_codes(
        KARP, [("P1", "잉어킹액막이가 있더라고", "product")],
        [("잉어킹은 원래 힘없는 캐릭터지만 버티다 보면 아주 센 캐릭터가 돼요.", [], True, "charm")],
        mode="DEMO_SELLER", extra={"common_knowledge": [
            {"about": "잉어킹", "note": "잉어킹은 힘이 약한 캐릭터지만 버티면 센 캐릭터가 된다"}]})),
    ("charm 사실 문장: fact 3개면 메모 밖 어간 3개까지", lambda: not story_codes(
        MUG_SCENE, MUG_SCENE_FACTS,
        [("이번 가마에서 유약이 흘러내려 컵마다 무늬가 신기하게 제각각이에요.", ["F1", "F2", "F3"], False, "charm")])),
    ("일반 사실 문장: 같은 문장이 fact 3개여도 2개까지라 삭제", lambda: "UNGROUNDED" in story_codes(
        MUG_SCENE, MUG_SCENE_FACTS,
        [("이번 가마에서 유약이 흘러내려 컵마다 무늬가 신기하게 제각각이에요.", ["F1", "F2", "F3"], False, "fact")])),
    ("scene 문장이 사실로 오면 감성으로 바로잡음(딸기 '찬 바람이…' 살아남음)", lambda: (lambda c: c["fixes"]["role_fix"] == 1 and len(c["kept"]) == 2)(
        story_codes(BERRY, BERRY_FACTS,
                    [("우리 가게 딸기 케이크는 제철 딸기만 써요.", ["F1"], False, "fact"),
                     ("찬 바람이 불기 시작하면 단골분들이 먼저 물어보세요.", ["F2"], False, "scene")], full=True))),
    ("약속 끝맺음이 사실로 오면 감성으로 바로잡음(ending_fix)", lambda: (lambda c: c["fixes"]["ending_fix"] == 1 and len(c["kept"]) == 2)(
        story_codes(ROCK_FULL, [("F1", "아직 판매는 안하고 준비중임.", "seller_scene"), ("F2", "한탄강 갔을때 주운 돌이 동글동글해서", "seller_scene")],
                    [("돌이 동글동글해서 눈을 붙여 뒀어요.", ["F2"], False, "fact"),
                     ("준비가 끝나면 여기서 먼저 알려 드릴게요.", ["F1"], False, "ending")], full=True))),
    ("NO_CHARM: charm이 있는데 charm 문장이 없으면 재작성", lambda: "NO_CHARM" in index.needs_rewrite(story_codes(
        SOAP, [("F1", "엄마가 예전에 쌀뜨물로 세수하던 게 생각나서 만들어봤어요", "seller_scene")],
        [("엄마가 쌀뜨물로 세수하던 게 생각나서 만들어 봤어요.", ["F1"], False, "fact")],
        extra={"charm": {"fact_ids": ["F1"], "note": "엄마 기억"}}, full=True))),
    ("NO_CHARM: role이 없는 옛 출력은 보지 않음", lambda: "NO_CHARM" not in index.needs_rewrite(story_codes(
        SOAP, [("F1", "엄마가 예전에 쌀뜨물로 세수하던 게 생각나서 만들어봤어요", "seller_scene")],
        [("엄마가 쌀뜨물로 세수하던 게 생각나서 만들어 봤어요.", ["F1"], False)],
        extra={"charm": {"fact_ids": ["F1"], "note": "엄마 기억"}}, full=True))),
    ("NO_SEASON_OPEN: 계절 fact가 제목·첫 문장에 없으면 S", lambda: ("S", "NO_SEASON_OPEN") in story_codes(
        BERRY, BERRY_FACTS,
        [("우리 가게 딸기 케이크는 제철 딸기만 써요.", ["F1"], False, "fact"),
         ("겨울에만 나와서 단골분들이 먼저 물어보세요.", ["F2"], False, "fact")],
        extra={"season": {"fact_id": "F2", "note": "겨울"}}, full=True)["signals"]),
    ("NO_SEASON_OPEN: 첫 문장이 계절 fact면 통과", lambda: ("S", "NO_SEASON_OPEN") not in story_codes(
        BERRY, BERRY_FACTS,
        [("겨울에만 나와서 단골분들이 먼저 물어보세요.", ["F2"], False, "fact"),
         ("우리 가게 딸기 케이크는 제철 딸기만 써요.", ["F1"], False, "fact")],
        extra={"season": {"fact_id": "F2", "note": "겨울"}}, full=True)["signals"]),
    ("NO_SCENE: 끝맺음 뺀 본문 4문장이 모두 사실이면 S", lambda: ("S", "NO_SCENE") in story_codes(
        MUG_SCENE, MUG_SCENE_FACTS,
        [("이번에 가마 새로 돌린 게 나왔어요.", ["F1"], False, "fact"),
         ("유약이 생각보다 많이 흘러내렸어요.", ["F2"], False, "fact"),
         ("유약이 흘러내려서 처음엔 망했다 싶었어요.", ["F2"], False, "fact"),
         ("꺼내 놓고 보니 컵마다 흐른 모양이 다 달라요.", ["F3"], False, "fact"),
         ("하나씩 보여 드릴게요.", [], True, "ending")], full=True)["signals"]),
    ("비율 초과여도 감성 문장을 지우지 않음(RATIO_TRIM 없음, ratio_over만 기록)", lambda: (lambda c: (index.finalize(c), [k["role"] for k in c["kept"]])[1] == ["fact", "scene", "charm", "ending"]
        and c["ratio_over"] and "RATIO_TRIM" not in c["deleted"])(
        story_codes(MUG_SCENE, MUG_SCENE_FACTS,
                    [("꺼내 놓고 보니 컵마다 흐른 모양이 다 달라요.", ["F3"], False, "fact"),
                     ("커피를 따르면 그 무늬가 먼저 눈에 들어올 거예요.", [], True, "scene"),
                     ("같은 무늬는 하나도 없어요.", [], True, "charm"),
                     ("하나씩 보여 드릴게요.", [], True, "ending")], full=True))),
    ("ADDRESS: ~셔도 좋아요는 말 건넴", lambda: "NO_ADDRESS" not in signals(["편하게 골라 보셔도 좋아요."])),
    ("HEADLINE_PRICE: '6천원 받으려다 4500원으로 맞춘 무화과 찹쌀떡' 실패", lambda: bool(
        index.HEADLINE_PRICE.search("6천원 받으려다 4500원으로 맞춘 무화과 찹쌀떡"))
        and not headline_ok(FIG, "6천원 받으려다 4500원으로 맞춘 무화과 찹쌀떡")),
    ("HEADLINE_PRICE: '11월 중순까지만 만드는 무화과 찹쌀떡' 통과(11월은 금액 아님)", lambda: not
        index.HEADLINE_PRICE.search("11월 중순까지만 만드는 무화과 찹쌀떡")
        and headline_ok(FIG, "11월 중순까지만 만드는 무화과 찹쌀떡")),
    ("HEADLINE_PRICE: 만원·₩8,000·32,000원 잡고 350정도·한 번은 통과", lambda: all(
        index.HEADLINE_PRICE.search(t) for t in ("만원의 행복", "₩8,000 키링", "32,000원 머그"))
        and not any(index.HEADLINE_PRICE.search(t) for t in ("350정도 머그", "한 번 도전", "보름만 원래대로"))),
    # ── 실무 정보 한 줄 (옵션 B) ──
    ("MONEY: 이야기 문장의 '4500원으로 맞췄어요'는 금액 없이 다듬거나 삭제", lambda: not any(
        index.MONEY.search(t) for t in kept_texts(FIG, FIG_INFO_FACTS, [
            ("그래도 동네 어르신들 사 가시라고 4500원으로 맞췄어요.", ["F3"], False, "fact")], product=FIG_INFO_PRODUCT))),
    ("info 줄 통과: 무화과 찹쌀떡 4500원 · 11월 중순까지 · 아침에 만들어 다 팔리면 끝 (마지막 문단)", lambda: (lambda c: c["info"] is not None
        and index.finalize(c)["body"][-1] == "무화과 찹쌀떡 4500원 · 11월 중순까지 · 아침에 만들어 다 팔리면 끝"
        and "price" not in index._product_gaps(c))(story_codes(FIG, FIG_INFO_FACTS, [
            ("무화과 철 끝나는 11월 중순까지만 해요.", ["F1"], False, "fact"),
            ("동네 어르신들 사 가시라고 값을 낮췄어요.", ["F3"], False, "fact"),
            ("오늘도 따뜻하게 보내세요.", [], True, "ending"),
            ("무화과 찹쌀떡 4500원 · 11월 중순까지 · 아침에 만들어 다 팔리면 끝", ["F3", "F1", "F2"], False, "info")],
            product=FIG_INFO_PRODUCT, ending="greeting", full=True))),
    ("info 줄 탐지: 지어낸 항목 '택배 가능'", lambda: "INFO_UNGROUNDED" in story_codes(FIG, FIG_INFO_FACTS, [
            ("무화과 철 끝나는 11월 중순까지만 해요.", ["F1"], False, "fact"),
            ("무화과 찹쌀떡 4500원 · 11월 중순까지 · 택배 가능", ["F3", "F1"], False, "info")],
            product=FIG_INFO_PRODUCT)),
    ("info 줄 탐지: 권유가 섞인 줄", lambda: "INFO_UNGROUNDED" in story_codes(FIG, FIG_INFO_FACTS, [
            ("무화과 철 끝나는 11월 중순까지만 해요.", ["F1"], False, "fact"),
            ("무화과 찹쌀떡 4500원 · 11월 중순까지 들러 주세요", ["F3", "F1"], False, "info")],
            product=FIG_INFO_PRODUCT)),
    ("절 다듬기 안 함: '사 가시라고'는 '가시라요'로 맺지 않는다", lambda: index._close_clause("사 가시라고") is None),
    # ── 감성 개편 (2026-10-29) ──
    ("판정: 판매자 장면 없어도 charm·상식 + 살 방법이면 READY (잉어킹, DEMO)", lambda: gate_v2(
        KARP + " 몇달뒤에 이사 예정이어서 가지고 싶었는데", "DEMO_SELLER",
        [("F2", "잉어킹액막이가 있더라고", "product", None),
         ("F3", "가챠로밖에 안팔아서", "how_to_buy", None),
         ("F4", "만원이라는 큰 금액이어도", "price", None),
         ("F5", "한번 도전해봤더니 성공해서 한번에 뽑았어", "buyer_action", "한 번 도전해 보셔도 좋아요")],
        {"name": "잉어킹액막이", "name_fact_id": "F2", "price_fact_id": "F4"},
        charm={"fact_ids": ["F2"], "note": "잉어킹 모양 액막이"},
        knowledge=[{"about": "잉어킹", "note": "잉어킹은 힘없는 캐릭터지만 버티다 보면 아주 센 캐릭터가 된다"}]) == "READY"),
    ("판정: 이야깃거리만 있고 살 방법이 없으면 NEED_MORE_INFO", lambda: gate_v2(
        SOAP, "REAL_SELLER", [("F1", "쌀뜨물 비누", "product", None)],
        {"name": "쌀뜨물 비누", "name_fact_id": "F1", "price_fact_id": None},
        charm={"fact_ids": ["F1"], "note": "쌀뜨물"}) == "NEED_MORE_INFO"),
    ("판정: 살 방법만 있고 이야깃거리 없으면 NEED_MORE_INFO (아메리카노)", lambda: gate_v2(
        "아메리카노 4500원 맛있어요", "REAL_SELLER", [("F1", "아메리카노 4500원", "price", None)],
        {"name": "아메리카노", "name_fact_id": "F1", "price_fact_id": "F1"}) == "NEED_MORE_INFO"),
    ("판정: Analyzer가 NEED_MORE_INFO면 코드가 올리지 않는다", lambda: gate_v2(
        KARP, "DEMO_SELLER", [("F2", "잉어킹액막이가 있더라고", "product", None), ("F4", "만원이라는 큰 금액이어도", "price", None)],
        {"name": "잉어킹액막이", "name_fact_id": "F2", "price_fact_id": "F4"},
        charm={"fact_ids": ["F2"], "note": ""}, readiness="NEED_MORE_INFO") == "NEED_MORE_INFO"),
    ("끝맺음: 여쭤보세요·말씀해 주세요·문의 주세요는 invite가 아니다", lambda: not any(index._is_invite(t) for t in (
        "궁금하시면 편하게 여쭤보세요.", "원하시는 색은 말씀해 주세요.", "언제든 문의 주세요.", "편하게 물어보세요."))),
    ("NO_SCENE: 짧은 글이어도 scene 문장이 없으면 S", lambda: ("S", "NO_SCENE") in story_codes(
        SOAP, [("F1", "엄마가 예전에 쌀뜨물로 세수하던 게 생각나서 만들어봤어요", "seller_scene")],
        [("엄마가 쌀뜨물로 세수하던 게 생각나서 만들어 봤어요.", ["F1"], False, "fact"),
         ("하나씩 보여 드릴게요.", [], True, "ending")], full=True)["signals"]),
    ("판정: seller_feeling만 있으면 NEED_MORE_INFO", lambda: gate(
        "아메리카노 4500원 맛있어요", [("F1", "맛있어요", "seller_feeling")], ["F1"]) == "NEED_MORE_INFO"),
    ("판정: READY인데 상품명 null이면 NEED_MORE_INFO", lambda: gate(
        SOAP, [("F1", "만들어봤어요", "seller_scene")], ["F1"], name=None) == "NEED_MORE_INFO"),
    ("판정: seller_scene fact 있으면 READY", lambda: gate(
        SOAP, [("F1", "만들어봤어요", "seller_scene")], ["F1"]) == "READY"),
    ("판정: 잘린 quote뿐인 seller_scene은 NEED_MORE_INFO", lambda: gate(
        HAT, [("F1", "따가워요", "seller_scene")], ["F1"]) == "NEED_MORE_INFO"),
]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    show = "--show" in sys.argv

    human, machine = [], []
    for name in ("captions.md", "instagram.md"):
        kept, excluded = load_captions(RAW / name)
        human += kept
        machine += excluded

    raw_b, grounded_b, c_codes, h_any, s_two = run_captions(human, show)
    _, _, c_machine, h_machine, s_machine = run_captions(machine)
    total = len(human)

    grades = {
        "CLICHE": "H", "ABSTRACT_REPEAT": "H", "CTA": "H", "LESSON": "H", "PLEDGE": "H",
        "CLICHE_ONE": "S", "STEM_REPEAT": "S", "SAME_LAST": "S", "LIST3": "S",
        "PASSIVE": "S", "DEDICATION": "S", "CONNECTIVE": "S",
        "ENDING_INVITE": "S",
        "NO_ADDRESS": "규칙", "COPY_EXAMPLE": "규칙"
    }
    b_codes = ["NUMBER", "HEDGE", "PERIOD", "SERVICE", "EXCLUSIVE", "EFFICACY", "SOCIAL",
               "ORIGIN", "MATERIAL", "TASTE", "COMPARE", "SHOP_INVENT", "PROPER"]

    def pct(n, d):
        return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"

    unit_results = []
    for label, case in UNIT_CASES:
        try:
            ok = bool(case())
        except Exception as error:  # noqa: BLE001
            ok = False
            label += f" — 예외 {type(error).__name__}"
        unit_results.append((label, ok))

    lines = [
        "# B·C 검사 보정 결과",
        "",
        "`python engine/tests/check_calibration.py`로 다시 만든다. API 호출 없음.",
        f"사람 글 {total}개(captions.md·instagram.md에서 [제외] 뺀 것), AI로 보인 [제외] 글 {len(machine)}개.",
        "사람 글 원문은 옮기지 않고 개수와 코드만 적는다.",
        "",
        "## C. 기계 같은 글 신호 (메모 없이, 걸린 글 수)",
        "",
        "| 코드 | 등급 | 사람 글 | [제외] 글 |",
        "|---|---|---|---|"
    ]
    for code, grade in grades.items():
        lines.append(f"| {code} | {grade} | {pct(c_codes[code], total)} | {pct(c_machine[code], len(machine))} |")
    lines += [
        f"| H 하나 이상 (재작성) | | {pct(h_any, total)} | {pct(h_machine, len(machine))} |",
        f"| S 두 개 이상 (재작성) | | {pct(s_two, total)} | {pct(s_machine, len(machine))} |",
        "",
        "NO_ADDRESS는 사람 글의 말투 분포를 보여 줄 뿐이다. 엔진은 Writer에게 말 건네는 표현을 요구하므로 재작성 사유로 둔다.",
        "",
        "## B. 금지 항목 (문장 단위, 걸린 글 수)",
        "",
        "'그대로'는 메모·근거 없이 돌린 탐지 폭이다. 사람 글에는 실제 가격·포장·인기 같은 말이 들어 있어서 높게 나오는 게 정상이다(엔진에서는 메모에 있으면 면제).",
        "'근거 있음'은 글 자체를 메모이자 근거로 둔 값으로, 면제가 제대로 돌면 0이어야 한다.",
        "",
        "| 코드 | 그대로 | 근거 있음 |",
        "|---|---|---|"
    ]
    for code in b_codes:
        lines.append(f"| {code} | {pct(raw_b[code], total)} | {pct(grounded_b[code], total)} |")
    cost_low = sum(bool(index.COST_LOW.search(c)) for c in human)
    lines += [
        "",
        f"COST_LOW(공짜·원가 등, 메모 면제 없음)는 사람 글 {pct(cost_low, total)}에서 걸린다. "
        "주워·주운 등은 상품을 가리키는 문장에서만 보므로 이 표에 넣지 않았다."
    ]
    passed = sum(ok for _, ok in unit_results)
    lines += [
        "",
        f"## 단위 사례 (review.md 예시와 새 테스트 메모의 경계 사례): {passed}/{len(unit_results)} 통과",
        ""
    ]
    lines += [f"- {'통과' if ok else '실패'} — {label}" for label, ok in unit_results]
    lines += [
        "",
        "## 보정에서 설계와 다르게 둔 것",
        "",
        "- 어간 떼기에 연결어미(어서·아서·해서·면서·으면·니까·는데·지만·지·서·고)와 서술격(이고·이라·이니·인데 등)을 더했다. 없으면 '떠서·따갑지'가 메모 밖 어간으로 잡혀 writer.md 예시 B의 사실 문장도 지워진다.",
        "- 어간 비교에서 둘째 음절은 첫소리만 본다(따갑↔따가워, 만들↔만드는, 돌렸↔돌린). 불용 어간에 말 건네는 보조 용언(않아·드릴·보세 등)과 '하다' 활용형(하니·하면 등)을 더했다. 스모크 테스트에서 근거 있는 사실 문장 2개가 이 때문에 지워졌다.",
        "- A1은 뒤 부정어도 본다(quote 다음 어절이 않·없·못하·아니로 시작하면 버림). 앞 부정어만으로는 review.md의 '효과는 없지만'→'효과'를 못 막는다.",
        "- EXCLUSIVE 면제의 `만`은 조사 뒤의 한정 `만`만 본다(설계대로면 '만원·만들'이 든 근거는 모두 면제된다). 같은 말(예: 소량)이 근거에 있어도 면제.",
        "- NUMBER 고유어는 단위 뒤에 다른 낱말이 붙으면 세지 않고(한 단계, 세일), 세일·열일은 뺐다. ORIGIN 수상한, EFFICACY 진정한·진정성·'~로 이루어진'(구성), MATERIAL 유리하다·꿀팁, PERIOD 오래간만, PROPER (b) 볼거리·먹거리 류를 뺐다.",
        "- LIST3 쉼표 구획은 정확히 3개일 때만 보고, 숫자 안 쉼표와 '등'으로 맺는 품목 안내는 뺐다(사람 글 23%→8%).",
        "- A4의 1인칭 표지(저는·저도·제가)는 seller_scene·seller_feeling fact를 단 문장이면 통과시킨다(내용은 A2가 본다). 메모가 주어 없이 쓰인 경우 근거 있는 문장이 지워졌다(스모크 테스트 반려돌 키트).",
        "- STEM_REPEAT은 숫자·영문 조각을 세지 않는다. 보정 세트는 엔진처럼 이모지·해시태그를 먼저 지우고, 한 어절짜리 줄(품목 표기)은 문장에서 뺐다.",
        "",
        "- run1 반영(설계 9절): 표기 변형 사전(전자렌지·식세기·이쁘·첨엔), 지시어·부사 불용 어간(거기·모두·생각 등)과 어미 `니다·세요`, 회상 어미는 판매자 fact를 단 문장이면 통과, SHOP_INVENT·DEMO_BUYER·HEDGE·NO_PRODUCT_BODY·ENDING_INVITE 추가, 카드 가격은 price fact 금액만.",
        "- HEDGE의 quote 표지 `같`은 quote 끝의 짐작(~같아요)만 본다. 설계대로 `같` 전체를 보면 \"물방울 맺힌거같고\" 같은 비유를 단 문장도 지워졌다. quote 표지 HEDGE는 사실 문장에만, 의심(그럴리가·설마·글쎄)은 모든 문장에 적용한다. NO_PRODUCT_BODY는 2차에서 로그만 남긴다(설계 9절 1).",
        "",
        "- rerun1 반영: 절 다듬기(뒤 절 때문에 지울 문장은 앞 절이 모든 검사를 통과하면 '~해요/~이에요/~어요'로 맺어 살림, ㄷ·ㅂ·ㅅ 불규칙과 받침 없는 ㅏ·ㅓ·ㅕ 밖의 어간은 맺지 않고 삭제), 가격·판매 방법 fact를 잃으면 LOST_FACT로 14초 이상 남았을 때 max_tokens 2500 재작성, COST_LOW, TASTE(맛·식감·향 단정), 상품명 상식 문장(상품 fact를 달고 상품명을 쓴 문장)은 메모 밖 어간 3개까지 허용하되 메모 밖 4음절 이상 명사는 PROPER.",
        "- 이야기 문장 보호: 감성 문장에서는 판매자 표지 중 구체적 행동·회상·1인칭만 보고(고민·결정 제외), 손님 높임 장면(1인칭 없음)은 보지 않는다. 약속·인사 끝맺음은 메모 밖 낱말 수(A2)를 보지 않는다(B·SERVICE는 본다). A2 허용치는 1 + cited fact 수//2(최대 3). 문의 안내(물어보세요·문의·연락 주세요)는 invite가 아니다. ADDRESS에 '실 거예요·실 수 있·주세요'를 더했다. 재작성 사유에 지운 문장의 fact_ids와 RESTORE_FACTS(다른 문장에 없는 fact)를 넘긴다.",
        "- 스키마 개편(code-requests.md): charm·season fact 검증, common_knowledge는 메모에 있는 대상·B표·새 이름 검사를 거쳐 3개까지, 상식 문장(charm 감성·상품명 문장)은 그 설명을 근거에 더함, charm 사실 문장 허용치는 fact 수(최대 3), scene이 사실로 오면 감성으로(role_fix), 약속·인사 끝맺음이 사실로 오면 감성으로(ending_fix, 단 '~게요·~보내세요' 같은 말투일 때만 — 마지막 사실 문장까지 풀지 않으려고 문서보다 좁혔다), 제목 허용치 2, NO_CHARM 재작성 사유, NO_SEASON_OPEN·NO_SCENE S 신호, RATIO_TRIM은 fact→scene→charm 순, 재작성 사유 detail에 facts=…, RESTORE_FACTS는 사전 코드 LOST_FACT로.",
        "- 문서 5.1(감성 문장에는 판매자 표지 검사를 아예 안 함)은 따르지 않았다. review.md 1번의 '새벽에 작업하다 만들었어요'(interpretation:true)가 다시 통과하기 때문이다. 대신 감성 문장에서는 구체적 행동·회상·1인칭만 보고, 고민·결정과 손님 높임 장면은 보지 않는다.",
        "- 감성 개편(2026-10-29): READY는 판매자 장면이 있거나, 이야깃거리(charm·common_knowledge)와 살 방법(가격·구매 방법 fact, DEMO면 권유로 바꾼 buyer_action)이 함께 있을 때. Analyzer의 NEED_MORE_INFO를 코드가 올리지는 않는다. 감성 비율은 재작성 사유도 RATIO_TRIM도 아니고 ratio_over로 기록만 한다. NO_SCENE은 길이와 상관없이 scene 문장이 없으면 S.",
        "- 메모 밖 4음절 명사 판정은 휴리스틱이다. '크리스마스' 같은 일반어도 상품명 상식 문장에서는 지워질 수 있다.",
        "",
        "## 남은 것",
        "",
        "- H CLICHE가 사람 글 4/74(5.4%)에서 걸린다. 4개 모두 '만나보세요'다. 승인 규칙상 금지어라 그대로 두었다(이것을 빼면 H는 0%).",
        "- S STEM_REPEAT이 사람 글 41%에서 걸린다. 대부분 상품·품목 명사의 반복이고, 사람 글이 Writer 출력보다 길다. 런타임은 상품명·distinctive·메모에서 2회 이상 나온 어간을 빼므로 실제 비율은 더 낮다. S는 2개 이상일 때만 재작성이고, 그 기준으로 사람 글 20%다.",
        "- SAME_LAST는 사람 글에도 실제 끝말 반복이 있어 16%다. 손대지 않았다.",
        "- 사람 글의 B '그대로' 비율은 실제 가격·포장·예약·지명이 든 글이라 높다. 엔진에서는 메모 면제로 통과하는 값이다('근거 있음' 열이 모두 0%)."
    ]

    report = "\n".join(lines) + "\n"
    print(report)
    if "--no-write" not in sys.argv:
        OUT.write_text(report, encoding="utf-8")
        print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
