# (선택) KNIME로 정리 기록 분석하기

서비스는 KNIME 없이도 동작합니다. 시간이 남으면 아래 둘 중 하나로 'AutoML' 강의 내용을 더할 수 있습니다.

## A. 정리 기록 분석 (쉬움, 약 1시간)

서비스가 쌓은 파일 색인을 KNIME가 REST API로 직접 가져와 분석합니다.

| 순서 | 노드 | 설정 |
|---|---|---|
| 1 | **GET Request** | URL `http://localhost:8000/api/v1/files?limit=5000`, Request Headers에 `X-API-Key` = `.env`의 `SECRETARY_API_KEY` |
| 2 | **JSON to Table** | 배열을 행으로 펼치기 |
| 3 | **GroupBy** | `category`별 개수·`size` 합계 |
| 4 | **Bar Chart** | 분류별 파일 수 → "내 다운로드 폴더의 절반은 수업 자료" 같은 발표 소재 |

## B. Gemini 호출을 줄이는 분류 모델 (도전, 약 3시간)

1. A의 표에서 `ext`, `size`, `original_name`(단어), `category`(Gemini가 붙인 정답) 열을 고릅니다.
2. **Partitioning**(7:3, seed 0) → **Decision Tree Learner** → **Predictor** → **Scorer**로 정확도를 봅니다.
3. "이름과 확장자만으로 몇 %를 맞히는가 = 그만큼 Gemini 호출을 줄일 수 있다"를 발표에서 비교합니다.

> 서비스에 직접 넣는 것(PMML 등)은 실제 KNIME 파일로 호환성을 확인한 뒤에 진행하세요.
