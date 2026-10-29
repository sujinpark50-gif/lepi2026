"""Lepi 글 품질 판정기 (LLM judge).

rubric.md의 6개 항목을 0~5점으로 매긴다. 글 하나씩, 출처를 알리지 않고(blind) 판정한다.

함수:  score_text(client, text) -> {"scores": {항목: {"score", "reason"}}, "total": int}
CLI:   python engine/tests/judge.py <run_tests 결과 JSON> [--out 판정결과.json]
       READY 결과만 판정한다. 판정할 글 = headline + 빈 줄 + body 문단들.
기준선과 목표 구간은 judge_baseline.md 참고.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

MODEL = "claude-opus-5-5"
RUBRIC_PATH = HERE / "rubric.md"

CRITERIA = [
    ("voice", "1. 판매자 목소리"),
    ("decision", "2. 구체적 장면·결정"),
    ("usefulness", "3. 손님에게 쓸모"),
    ("naturalness", "4. 자연스러움"),
    ("restraint", "5. 담백함"),
    ("structure", "6. 구조와 끝맺음"),
]
MAX_TOTAL = 5 * len(CRITERIA)

# 목표 구간 (judge_baseline.md에서 정함)
# 품질 % = (총점 - 기계 글 평균) / (파사드패턴 평균 - 기계 글 평균). 기계 글 = 0%, 파사드패턴 = 100%.
REFERENCE_AVG = 18.1      # 파사드패턴 IG 캡션 49개 평균 총점 (= 100%, 2026-10-28 2차 측정)
MACHINE_AVG = 10.4        # 상투어로 제외한 기계 글 16개 평균 총점 (= 0%)
TARGET_LOW = 0.60         # 평균 총점 >= 15.1
TARGET_HIGH = 0.70        # 평균 총점 >= 15.8
POST_FLOOR = 15           # 글 하나 최저선: 총점 15 이상, 그리고 어느 항목도 1점 이하가 아님


def quality_ratio(total):
    return (total - MACHINE_AVG) / (REFERENCE_AVG - MACHINE_AVG)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [key for key, _ in CRITERIA],
    "properties": {
        key: {
            "type": "object",
            "additionalProperties": False,
            "required": ["reason", "score"],
            "properties": {
                "reason": {"type": "string"},
                "score": {"type": "integer"},
            },
        }
        for key, _ in CRITERIA
    },
}

SYSTEM = """너는 한국어 SNS 상품 글을 평가하는 엄격한 편집자다.
아래 루브릭으로 주어진 글 하나를 채점한다. 글의 출처(누가 썼는지, 사람인지 AI인지, 브랜드 규모)는 알려주지 않으며 추측해서 점수에 반영하지 않는다.
글에 나온 가게·브랜드 이름이나 유명세도 점수에 반영하지 않는다. 글 자체만 본다.
항목마다 루브릭의 1·3·5 설명과 비교해 정수 점수를 정하고, 근거를 한국어 한 문장(60자 이내)으로 적는다. 근거에 원문을 길게 인용하지 않는다.
후하게 주지 않는다. 5점은 그 항목에서 흠잡을 데가 없을 때만 준다.

키 대응: voice=1, decision=2, usefulness=3, naturalness=4, restraint=5, structure=6.

<rubric>
{rubric}
</rubric>"""


def make_client():
    import anthropic
    from run_tests import load_env  # .env의 ANTHROPIC_API_KEY를 환경 변수로 올린다 (출력하지 않음)

    load_env()
    return anthropic.Anthropic()


def score_text(client, text):
    rubric = RUBRIC_PATH.read_text(encoding="utf-8")
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM.replace("{rubric}", rubric),
        messages=[{"role": "user", "content": f"<post>\n{text.strip()}\n</post>\n\n이 글을 채점해 줘."}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    raw = next(block.text for block in response.content if block.type == "text")
    data = json.loads(raw)
    scores = {}
    for key, _ in CRITERIA:
        score = max(0, min(5, int(data[key]["score"])))
        scores[key] = {"score": score, "reason": data[key]["reason"]}
    return {"scores": scores, "total": sum(s["score"] for s in scores.values())}


def format_result(result):
    paragraphs = [p.strip() for p in (result.get("body") or []) if p and p.strip()]
    return "\n\n".join([(result.get("headline") or "").strip(), *paragraphs]).strip()


def passes_floor(judged):
    return judged["total"] >= POST_FLOOR and all(s["score"] >= 2 for s in judged["scores"].values())


def main():
    parser = argparse.ArgumentParser(description="run_tests 결과 JSON의 READY 글을 루브릭으로 판정")
    parser.add_argument("results", help="run_tests.py가 저장한 결과 JSON")
    parser.add_argument("--out", help="판정 결과 저장 경로 (JSON)")
    args = parser.parse_args()

    reports = json.loads(Path(args.results).read_text(encoding="utf-8"))
    if isinstance(reports, dict):
        reports = [reports]
    client = make_client()

    judged_all = []
    for report in reports:
        result = report.get("result") or {}
        name = report.get("name", "?")
        if result.get("status") != "READY":
            print(f"- {name}: {result.get('status') or 'ERROR'} (판정 제외)")
            continue
        judged = score_text(client, format_result(result))
        judged["name"] = name
        judged_all.append(judged)
        line = " ".join(f"{label.split('. ')[1]} {judged['scores'][k]['score']}" for k, label in CRITERIA)
        flag = "" if passes_floor(judged) else "  [최저선 미달]"
        print(f"- {name}: {judged['total']}/{MAX_TOTAL} (품질 {quality_ratio(judged['total']):.0%}){flag}")
        print(f"    {line}")
        for key, label in CRITERIA:
            print(f"    {label}: {judged['scores'][key]['reason']}")

    if judged_all:
        avg = sum(j["total"] for j in judged_all) / len(judged_all)
        ratio = quality_ratio(avg)
        verdict = "목표 달성(70%+)" if ratio >= TARGET_HIGH else "최소선 통과(60%+)" if ratio >= TARGET_LOW else "미달"
        below = sum(1 for j in judged_all if not passes_floor(j))
        print(f"\n평균 {avg:.1f}/{MAX_TOTAL} = 파사드패턴 대비 {ratio:.0%} → {verdict}; 최저선 미달 {below}/{len(judged_all)}")
    if args.out:
        Path(args.out).write_text(json.dumps(judged_all, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
