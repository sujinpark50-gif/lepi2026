# 기준선 (현재 엔진, v1)

- 날짜: 2026-10-28 · 모델: claude-opus-5-5 · effort: low · 브랜치: engine-v2
- 원본: `baseline_results.json`, 로그: `baseline_log.txt`
- 토큰은 v1 테스트 러너가 기록하지 않아 비워 둔다. 4단계에서 run_tests.py에 추가한다.

| 메모 | 모드 | 결과 | 시간(초) | 호출 수 | 삭제된 문장 |
|---|---|---|---|---|---|
| 쥐꼬리 낚시대 | REAL_SELLER | READY | 15.3 | 2 | 0 |
| 밀짚모자 | DEMO_SELLER | READY | 18.4 | 2 | 0 |
| 닉스고 | DEMO_SELLER | READY | 19.6 | 2 | 0 |
| 잉어킹 | DEMO_SELLER | READY | 17.2 | 2 | 0 |
| 딸기 케이크 | REAL_SELLER | READY | 9.8 | 2 | 0 |
| 단풍 네일 | REAL_SELLER | READY | 14.3 | 2 | 0 |
| 작약 | REAL_SELLER | READY | 13.4 | 2 | 0 |
| 쌀뜨물 비누 | REAL_SELLER | READY | 14.7 | 2 | 0 |
| 아메리카노 | REAL_SELLER | NEED_MORE_INFO | 5.5 | 1 | 0 |

- 평균 14.2초 · 최대 19.6초 · 호출 합계 17회 · 삭제 0문장
- 주의: 삭제 0은 v1 검사가 느슨해서다(source 문자열이 메모에 있기만 하면 통과). 예: 쥐꼬리 낚시대 수동 실행에서 메모에 없는 "다른 장난감이랑은 반응이 달라요"가 통과했다.
