"""글쓰기 모델 비교: 같은 Analyzer 결과를 Opus·Sonnet Writer에 각각 넣어 글과 원가·시간을 비교한다.

사용:
    python engine/tests/compare_writer.py engine/tests/compare_writer.json
    python engine/tests/compare_writer.py out.json claude-sonnet-5-5:medium,claude-sonnet-5-5:high

Analyzer는 메모마다 한 번만 부른다(설정된 ANALYZER_MODEL). 차이는 Writer 모델에서만 난다.
검사는 light 모드와 같다. 판정기 점수도 함께 매긴다.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip() and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "engine" / "tests"))

import anthropic  # noqa: E402
import index  # noqa: E402
from run_tests import call_cost_krw  # noqa: E402
from judge import format_result, make_client, score_text  # noqa: E402

# (모델, effort) 짝. 두 번째 인자로 "모델:effort,모델:effort"를 주면 바꾼다.
WRITERS = [("claude-opus-5-5", None), ("claude-sonnet-5-5", None)]

# 비교용 새 메모(기존 테스트에 없는 업종·말투). 판매자 메모처럼 거칠게 썼다.
MEMOS = [
    ("유자차", "올해도 고흥 유자 들어왔어요. 껍질째 하나하나 썰어서 설탕이랑 1:1로 청 담갔어요. 손이 노랗게 물들어서 며칠 안 빠짐 ㅋㅋ 따뜻한 유자차 5500원, 청만 따로 500ml 18000원. 유자 떨어지면 끝"),
    ("소금빵", "소금빵 처음 구웠을 때 버터가 다 흘러나와서 바닥이 튀김처럼 됐었음. 그 바삭한 바닥을 손님들이 더 좋아해서 일부러 그렇게 굽고 있어요. 아침 8시, 11시 두 번 나와요. 개당 3000원"),
    ("빈티지 니트", "일본 빈티지 니트 들어왔어요. 할머니가 직접 뜬 것 같은 꽈배기 무늬인데 팔꿈치에 작게 덧댄 천이 있어요. 사이즈는 여자 66정도. 하나뿐이에요 58000원"),
    ("겨울 리스", "12월 되면 매년 리스 만들어요. 올해는 목화랑 솔방울이랑 말린 오렌지 넣었어요. 현관에 걸어두면 들어올때마다 오렌지 냄새 살짝 남. 지름 30cm 45000원 예약제로 받아요"),
    ("고양이 키링", "우리 가게 고양이 보리를 닮은 키링 만들었어요. 보리가 치즈냥인데 꼬리 끝만 하얀색이라 그것까지 똑같이 칠함. 레진이라 가볍고 하나하나 손으로 칠해서 조금씩 표정이 달라요. 15000원"),
    ("메추리알 장조림", "반찬가게 하는데 메추리알 장조림은 아침마다 까는게 일이에요. 기계로 까면 흰자가 뜯겨서 손으로만 까요. 간장은 꽈리고추 넣고 졸여서 살짝 매콤함. 300g 6000원 매일 오후 2시쯤이면 다 나가요"),
]


def writer_cost(call, model):
    return call_cost_krw(call, call.get("served") or model)


def main():
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "engine/tests/compare_writer.json")
    writers = WRITERS
    if len(sys.argv) > 2:
        writers = [tuple(item.split(":")) for item in sys.argv[2].split(",")]
    client = anthropic.Anthropic()
    judge_client = make_client()
    rows = []
    for name, memo in MEMOS:
        stats = {}
        deadline = time.monotonic() + 300
        mctx = index._memo_context(memo, [], "REAL_SELLER")
        analysis = index.call_structured(
            client, index.ANALYZER_PROMPT,
            {"scenario_mode": "REAL_SELLER", "raw_input": memo, "seller_additions": []},
            "analyzer", index.ANALYZER_SCHEMA, deadline, stats,
            effort=index.ANALYZER_EFFORT, model=index.ANALYZER_MODEL
        )
        analysis, stop = index.clean_analysis(analysis, mctx, stats)
        row = {"name": name, "memo": memo, "analyzer_krw": round(writer_cost(stats["calls"][0], index.ANALYZER_MODEL), 1)}
        if stop:
            row["stop"] = stop
            rows.append(row)
            print(name, "Analyzer에서 멈춤:", stop.get("status"))
            continue
        writer_input = {"raw_input": memo, "seller_additions": [], "analysis": analysis}
        for model, effort in writers:
            key = f"{model}@{effort}" if effort else model
            wstats = {}
            started = time.monotonic()
            story = index.call_structured(
                client, index.WRITER_PROMPT, writer_input, "writer", index.WRITER_SCHEMA,
                time.monotonic() + 300, wstats, model=model, effort=effort
            )
            seconds = round(time.monotonic() - started, 1)
            checked = index.check_story(story, analysis, mctx)
            result = index._report_only(index._light_check(story, analysis, mctx, wstats), analysis, checked, wstats)
            judged = score_text(judge_client, format_result(result)) if result.get("status") == "READY" else None
            row[key] = {
                "result": result,
                "writer_krw": round(writer_cost(wstats["calls"][0], model), 1),
                "seconds": seconds,
                "light_deleted": wstats.get("light_deleted"),
                "judge": judged,
            }
            print(name, key, seconds, "s", row[key]["writer_krw"], "원", judged and judged["total"])
        rows.append(row)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", out_path)


if __name__ == "__main__":
    main()
