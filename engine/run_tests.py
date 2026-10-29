"""레피 Story Engine v2 테스트 메모를 돌린다.

api/index.py의 run_story_engine을 그대로 부르므로 화면에 나가는 결과와 같다.
테스트마다 상태, 걸린 시간, 호출 수, 재작성 여부, 지운 문장 수(코드별),
토큰(입력/출력/캐시)을 보여 주고, 끝에 변환 한 번당 평균과 원가(원)를 낸다.

    python engine/run_tests.py                          # 전체, 모델은 LEPI_MODEL(기본 Opus 5.5)
    python engine/run_tests.py --model claude-sonnet-5-5
    python engine/run_tests.py --only 아메리카노,작약     # 이름으로 골라 돌리기
    python engine/run_tests.py engine/tests/v2_opus.json # 결과 저장 경로

ANTHROPIC_API_KEY는 환경 변수나 레포 루트의 .env에서 읽는다.
결과 전체(화면 응답, 로그 통계, Analyzer·Writer 원본 출력)는 기본으로
engine/test_results.json에 저장한다. 이 파일은 로컬 확인용이라 메모와 문장이 들어 있다.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

# 원가 계산(원). USD/MTok, 캐시 쓰기는 입력의 1.25배, 캐시 읽기는 0.1배.
KRW_PER_USD = 1400
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0)
}


TESTS = [
    # 기준 샘플 (v1 writer.md에 답이 있던 메모)
    {
        "name": "쥐꼬리 낚시대",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": "오늘은 우리집 고양이가 제일 좋아하는 쥐꼬리 낚시대를 홍보해볼까해. 실리콘이라서 엄청 부드러워서 진짜 쥐꼬리 같은지 흔들면 우리집냥이가 흥분하면서 좋아하는게 보이는데 우리 고객님들의 고양이들도 한번 보면 엄청 좋아할꺼야. 이걸 보면 고양이가 진짜 사냥한다는게 무슨 의미인지 알껄"
    },
    {
        "name": "밀짚모자",
        "scenario_mode": "DEMO_SELLER",
        "seller_additions": [],
        "memo": "못생긴 밀짚모자인데 철원 주상절리입장료내면 한사람당 5천원 상품권주는데 그걸 이용하면 주변상점에서 살수 있거든 너무 햇볕이 뜨거워서 어쩔수 없이 샀는데 국내 여행갈때마다 필요할때 들고갔더니 추억템이 됐어"
    },
    {
        "name": "닉스고",
        "scenario_mode": "DEMO_SELLER",
        "seller_additions": [],
        "memo": "저는 현역 시절 닉스고를 응원했습니다. 세계적인 무대에서 좋은 성적을 거두던 한국마사회 소유의 말이라는 점도 특별하게 느껴졌고요. 지금은 경주에서 은퇴해 씨수말로 지내고 있지만, 마사회 공식 굿즈에서 실제 닉스고의 외형을 본떠 만든 인형을 발견했습니다. 여러 마사회 굿즈 중에서도 가장 실제 말처럼 생겼고, 무엇보다 귀여웠습니다. 가격은 8천 원. 그래서 하나 데려왔습니다."
    },
    {
        "name": "잉어킹",
        "scenario_mode": "DEMO_SELLER",
        "seller_additions": ["별일 없이 잘 지나가자는 마음을 걸어두는 작은 액막이 이런 글귀도 있으면 좋지"],
        "memo": "남편이랑 포켓몬팝업이 있다고 해서 놀러갔더니 잉어킹액막이가 있더라고 그런데 가챠로밖에 안팔아서 만원이라는 큰 금액이어도 한번 도전해봤더니 성공해서 한번에 뽑았어 몇달뒤에 이사 예정이어서 가지고 싶었는데 좋은 추억이었어"
    },
    # 새 메모 — 헤드라인과 일반화 평가용
    {
        "name": "딸기 케이크",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": "우리 가게 딸기 케이크는 제철 딸기만 써요. 겨울에만 나와서 그런지 단골분들이 겨울 되면 먼저 물어보세요."
    },
    {
        "name": "단풍 네일",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": "이번 달 시즌 네일은 단풍 그라데이션이에요. 손톱 끝만 살짝 물들인 느낌이라 회사 다니시는 분들도 부담 없이 많이 하세요. 저도 지금 하고 있는데 손 볼 때마다 기분 좋아요"
    },
    {
        "name": "작약",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": "인스타에 올릴 거니까 짧게 써줘. 작약 한 단 3만5천원. 봉오리로 와서 집에서 하루이틀이면 확 펴요. 피는 거 보는 재미가 있어서 저는 일부러 봉오리로 들여요"
    },
    {
        "name": "쌀뜨물 비누",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": "쌀뜨물 비누. 엄마가 예전에 쌀뜨물로 세수하던 게 생각나서 만들어봤어요. 거품이 크진 않은데 뽀득하게 씻겨요"
    },
    {
        # 재료가 거의 없어 NEED_MORE_INFO가 나와야 맞다.
        "name": "아메리카노",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": "아메리카노 4500원 맛있어요"
    },
    # 랜딩 사례(index.html case-seonunsa-bell)의 메모. 구매자로 쓴 글이라 DEMO_SELLER.
    {
        "name": "선운사 소원의 종",
        "scenario_mode": "DEMO_SELLER",
        "seller_additions": [],
        "memo": "선운사 종은 만원인데 소원나무에 저렇게 대부분 가족의 건강과 성공을 기원하는 거라 나도 시댁어른이랑 남편이랑 간 김에 구매했어. 사서 몸에 지니지 않더라도 저렇게 바람에 풍경처럼 흔들리면서 촤르르 소리나니까 마음이 평안해지면서 꼭 소원이 이루어진것 같더라"
    },
    # ── 사용자가 준 새 메모 3개 (2026-10-28). 오타·띄어쓰기·줄바꿈은 원문 그대로 둔다 ──
    {
        # 메모의 가격(4500원)·기간(11월 중순까지만)은 써도 된다. 6천원은 가격이 아니다.
        # "줄 서서 사는 그런 데 아니고"를 뒤집거나 "다 팔리면 끝"을 완판으로 쓰면 안 된다.
        "name": "무화과 찹쌀떡",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": "우리 떡집은 원래 팥찹쌀떡만 했는데 딸이 요즘 과일찹쌀떡 유행이라고 해보자고 해서 시작함. 무화과가 비싸서 첨엔 6천원 받으려다가 동네 어르신들 사가시라고 4500원으로 맞췄음. 대신 무화과 철 끝나는 11월 중순까지만 함. 줄 서서 사는 그런 데 아니고 그냥 아침에 만들어서 다 팔리면 끝"
    },
    {
        # 가격 미정이라 카드 가격은 비어야 한다. 판매 준비 중이라 주문을 권하면 안 된다.
        # 한탄강은 메모에 있는 고유명사라 써도 된다.
        "name": "반려돌 키트",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": """상품 칸: 이름 지어주는 반려돌 키트 (판매 준비 중)  가격 미정

아직 판매는 안하고 준비중임. 한탄강 갔을때 주운 돌이 동글동글해서 눈 붙여서 책상에 뒀는데 회사에서 힘들때 쳐다보면 웃겨서 좀 나아짐. 그래서 돌이랑 눈스티커랑 이름표 넣어서 키트로 팔아볼까 생각중. 돌은 직접 주워서 씻어서 넣을거"""
    },
    {
        # 32,000원은 카드에 써도 된다. "350정도"를 정확한 용량으로 바꾸면 안 된다.
        # 단골의 "맛이 다르다"는 판매자가 믿지 않는 말이라 효능·후기로 쓰면 안 된다.
        # "같은 모양은 절대 안나와요"를 한정·유일 상품으로 늘리면 안 된다.
        "name": "유약 흘림 머그컵",
        "scenario_mode": "REAL_SELLER",
        "seller_additions": [],
        "memo": """상품 칸: 유약 흘림 머그컵 / 32,000원

이번에 가마 새로 돌린거 나왔는데요 ㅠㅠ 유약이 생각보다 많이 흘러내려서 첨엔 망했다 싶었는데 꺼내놓고 보니까 컵마다 흐른 모양이 다 달라요.. 어떤건 물방울 맺힌거같고 어떤건 산 능선같고 ㅋㅋ 원래는 다 깔끔하게 떨어지게 하려던건데 이게 더 이쁜거같아서 그냥 이대로 팔기로 함

용량은 350정도? 손잡이는 좀 두껍게 만들었어요 제가 손이 작아서 얇으면 불안하더라구요

아 그리고 지난주에 단골분이 하나 미리 가져가셨는데 이거에 커피마시면 맛이 다른거 같다고 하셔서 웃었어요 ㅋㅋ 그럴리가요..

전자렌지 식세기 되고요 주문하면 같은 모양은 절대 안나와요 그건 감안해주세요!!

아 콩이(공방고양이) 사진도 같이 올릴까 고민중.."""
    },
]


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def _call_model(stats, call):
    # stats["model"]은 [Analyzer 모델, Writer 모델]이다.
    models = stats.get("model") or [None, None]
    return models[0] if call.get("name") == "analyzer" else models[1]


def call_cost_krw(call, model):
    price_in, price_out = PRICES.get(call.get("served") or model, PRICES.get(model, (0, 0)))
    usd = (
        call.get("in", 0) * price_in
        + call.get("cache_w", 0) * price_in * 1.25
        + call.get("cache_r", 0) * price_in * 0.1
        + call.get("out", 0) * price_out
    ) / 1_000_000
    return usd * KRW_PER_USD


def run_one(index, client, test):
    """run_story_engine을 부르면서 통계와 단계별 원본 출력을 함께 잡아 둔다."""
    outputs = {}
    original_call = index.call_structured

    def spy_call(*args, **kwargs):
        result = original_call(*args, **kwargs)
        outputs[args[3]] = result
        return result

    index.call_structured = spy_call
    stats = {}
    started = time.time()
    try:
        result = index.run_story_engine(
            client,
            test["memo"],
            scenario_mode=test["scenario_mode"],
            seller_additions=test["seller_additions"],
            stats=stats
        )
    except Exception as error:
        result = {"error": repr(error)}
    finally:
        index.call_structured = original_call

    calls = stats.get("calls") or []
    return {
        "name": test["name"],
        "scenario_mode": test["scenario_mode"],
        "seconds": round(time.time() - started, 1),
        "result": result,
        "stats": stats,
        "tokens": {
            key: sum(c.get(key, 0) for c in calls)
            for key in ("in", "out", "cache_w", "cache_r")
        },
        "krw": round(sum(call_cost_krw(c, _call_model(stats, c)) for c in calls), 1),
        # 검사가 무엇을 지웠는지 로컬에서 보기 위한 원본. 화면·로그에는 나가지 않는다.
        "outputs": outputs
    }


def print_report(report):
    stats = report["stats"]
    tokens = report["tokens"]
    status = report["result"].get("status") or "ERROR"
    print(
        f"\n### {report['name']} · {report['scenario_mode']} · {status} · "
        f"{report['seconds']}초 · 호출 {len(stats.get('calls') or [])}회 · "
        f"재작성 {'예' if stats.get('rewrite') else '아니오'}"
        + (f"(건너뜀: {stats['rewrite_skipped']})" if stats.get("rewrite_skipped") else "")
    )
    print(
        f"  토큰 입력 {tokens['in']} / 출력 {tokens['out']} / 캐시쓰기 {tokens['cache_w']}"
        f" / 캐시읽기 {tokens['cache_r']} · {report['krw']}원"
    )
    print(f"  1차 지운 문장: {stats.get('deleted') or {}} · 신호: {stats.get('signals') or []}")
    if stats.get("rewrite"):
        print(f"  재작성 사유: {stats.get('rewrite_codes')} · 2차 지운 문장: {stats.get('deleted_2') or {}}")
    print(f"  최종 지운 문장: {stats.get('deleted_final') or {}}")
    would = stats.get("would")
    if would:
        print(
            f"  [report] 했을 삭제 {would['delete']} · 재작성 사유 {would['rewrite_reasons']}"
            f" · 비율 초과 {would['ratio_over']} · 제목 실패 {would['headline_fail']}"
            f" · 상품 빈칸 {would['product_gaps']} · 결과 상태 {would['status']}"
        )
    calls_ms = [(c['name'], c.get('ms')) for c in stats.get('calls') or []]
    print(f"  호출 ms {calls_ms} · 운영 시간 초과였을지 {'예' if stats.get('over_prod') else '아니오'}")
    if "roles" in stats or "charm" in stats:
        print(
            f"  charm {stats.get('charm')} · 상식 {stats.get('ck', 0)}(버림 {stats.get('ck_dropped', 0)})"
            f" · 계절 {stats.get('season')} · 역할 {stats.get('roles') or {}}"
            f" · 고침 role {stats.get('role_fix', 0)}/ending {stats.get('ending_fix', 0)}"
        )
    print(json.dumps(report["result"], ensure_ascii=False, indent=1))


def print_averages(reports, model):
    if not reports:
        return
    n = len(reports)

    def average(values):
        return sum(values) / n

    print(f"\n## 변환 한 번당 평균 ({model}, {n}개)")
    print(f"  시간 {average([r['seconds'] for r in reports]):.1f}초"
          f" · 호출 {average([len(r['stats'].get('calls') or []) for r in reports]):.2f}회"
          f" · 재작성 {sum(bool(r['stats'].get('rewrite')) for r in reports)}/{n}")
    print(f"  입력 {average([r['tokens']['in'] for r in reports]):.0f}"
          f" · 출력 {average([r['tokens']['out'] for r in reports]):.0f}"
          f" · 캐시쓰기 {average([r['tokens']['cache_w'] for r in reports]):.0f}"
          f" · 캐시읽기 {average([r['tokens']['cache_r'] for r in reports]):.0f} 토큰")
    print(f"  원가 {average([r['krw'] for r in reports]):.1f}원"
          f" (1달러 {KRW_PER_USD}원, 최대 {max(r['krw'] for r in reports):.1f}원)")
    statuses = {}
    for r in reports:
        status = r["result"].get("status") or "ERROR"
        statuses[status] = statuses.get(status, 0) + 1
    print(f"  상태 {statuses}")
    print(f"  운영 기준(42초·호출 25초)이면 시간 초과였을 테스트 {sum(bool(r['stats'].get('over_prod')) for r in reports)}/{n}")
    woulds = [r["stats"].get("would") for r in reports if r["stats"].get("would")]
    if woulds:
        total_delete = {}
        reasons = {}
        for w in woulds:
            for code, count in w["delete"].items():
                total_delete[code] = total_delete.get(code, 0) + count
            for code in w["rewrite_reasons"]:
                reasons[code] = reasons.get(code, 0) + 1
        print(f"  [report] 했을 삭제 합계 {total_delete} · 재작성됐을 글 {sum(bool(w['rewrite_reasons']) for w in woulds)}/{len(woulds)}"
              f" · 사유별 {reasons} · 제목 실패 {sum(bool(w['headline_fail']) for w in woulds)}"
              f" · 비율 초과 {sum(w['ratio_over'] for w in woulds)}")


def main():
    # Windows 터미널에서도 한글이 깨지지 않게 한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("out", nargs="?", help="결과 JSON 경로")
    parser.add_argument("--model", help="LEPI_MODEL 대신 쓸 모델")
    parser.add_argument("--only", help="쉼표로 구분한 테스트 이름")
    args = parser.parse_args()

    load_env()
    if args.model:
        os.environ["LEPI_MODEL"] = args.model
    # 테스트는 시간 때문에 결과가 잘리지 않게 넉넉히 둔다(운영 42초·25초 초과 여부는 따로 센다).
    os.environ.setdefault("LEPI_DEADLINE_S", "120")
    os.environ.setdefault("LEPI_CALL_TIMEOUT_S", "60")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY가 없습니다.")

    # MODEL은 import 시점의 LEPI_MODEL을 읽으므로 환경을 정한 뒤에 불러온다.
    import index
    import anthropic

    tests = TESTS
    if args.only:
        names = {name.strip() for name in args.only.split(",")}
        tests = [t for t in TESTS if t["name"] in names]

    client = anthropic.Anthropic(api_key=api_key)
    reports = []
    for test in tests:
        report = run_one(index, client, test)
        print_report(report)
        reports.append(report)

    print_averages(reports, f"{index.ANALYZER_MODEL} + {index.WRITER_MODEL}")

    out_path = (
        Path(args.out).resolve()
        if args.out
        else Path(__file__).resolve().parent / "test_results.json"
    )
    out_path.write_text(
        json.dumps(reports, ensure_ascii=False, indent=1),
        encoding="utf-8"
    )
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
