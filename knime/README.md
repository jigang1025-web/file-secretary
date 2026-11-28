# KNIME 실습 — "생성형 AI가 가르치고, AutoML이 배운다"

AutoML 강의에서 배운 노드(CSV Reader, Row Filter, Partitioning, Decision Tree, Random Forest, Scorer, Bar Chart)로 두 가지를 확인합니다.

| 실험 | 질문 | 발표에서 보여 줄 숫자 |
|---|---|---|
| **A. 정확도 비교** | 처음 보는 실제 파일에서 규칙 기반과 Gemini 중 누가 더 정확한가? | 규칙 ○% vs Gemini ○% (Scorer의 Accuracy, Confusion Matrix) |
| **B. 호출 줄이기** | 파일 **이름·확장자·크기만으로**(내용을 읽기 전에) 분류를 맞힐 수 있는가? 확실한 파일은 Gemini에 안 보내도 되는가? | "○%의 파일은 Gemini 없이 정밀도 ○%로 분류 가능 → 호출 ○% 감소" |

## 0. 데이터 준비

### 어떤 파일로 할까 (중요)

| 데이터 | 실험 A | 실험 B | 주의 |
|---|---|---|---|
| **내 다운로드 폴더 복사본** (추천) | ✅ 공정한 비교 | ✅ 파일이 많을수록 좋음 | 민감 파일은 AI로 안 가지만, 나머지 파일 내용은 Gemini 무료 등급으로 전송됨 |
| 연습 샘플 26개 | ⚠️ 비교로는 부적합 | ⚠️ 너무 적음 | 규칙 기반이 이 샘플을 보면서 다듬어졌기 때문에 규칙이 24/24로 다 맞힘 (공정하지 않음). 노드 연습용으로만 |

### 순서

1. (실제 파일로 할 때) 다운로드 폴더를 **복사**해서 예: `C:\Users\stopr\knime-files`를 만들고, `.env`에서 `HOST_TARGET_DIR=C:/Users/stopr/knime-files`로 바꾼 뒤 `docker compose up -d`.
   - 원본 다운로드 폴더는 건드리지 않습니다. 파일은 50~200개 정도가 적당합니다.
2. **폴더 감시 데몬**이 새 파일을 백그라운드에서 Gemini로 미리 분석합니다. 대시보드 오른쪽 위 상태가 "폴더 감시 · n/n 준비됨"이 될 때까지 기다립니다.
   - 무료 등급은 하루 요청 수가 정해져 있어 파일이 많으면 하루 넘게 걸릴 수 있습니다. 실패한 파일은 10분마다 다시 시도합니다.
3. CSV 내려받기 (Gemini를 새로 부르지 않음):

```powershell
cd $HOME\file-secretary\file-secretary
$key = (Select-String -Path .env -Pattern "^SECRETARY_API_KEY=(.*)").Matches.Groups[1].Value
curl.exe -H "X-API-Key: $key" http://localhost:8000/api/v1/export/knime.csv -o knime\data\files.csv
```

4. **정답 달기 (실험 A용)**: `knime\data\files.csv`를 엑셀로 열어 `true_category` 칸에 정답 분류를 직접 적습니다.
   - 쓸 수 있는 값: `수업`, `문서`, `개인서류`, `영수증·결제`, `사진`, `스크린샷`, `영상·음성`, `설치파일`, `압축파일`, `기타`
   - AI나 규칙 결과를 보지 말고(열을 숨기고) 파일을 직접 열어 판단해야 공정합니다. 50개면 15분쯤 걸립니다.
   - 저장할 때 형식은 **CSV UTF-8(쉼표로 분리)**.

### CSV 열 설명

| 열 | 뜻 |
|---|---|
| `file_name`, `ext`, `kind`, `size_kb` | 파일 이름, 확장자, 종류(document·image·media·installer·archive), 크기 |
| `name_type` | 이름 모양: `kakaotalk`, `screenshot`, `camera`(IMG_…), `installer`, `generic`(다운로드·제목 없음·무제…), `other` |
| `name_has_date`, `name_has_version`, `name_length` | 이름에 날짜가 있는지, `(1)`·최종·final 같은 버전 표시가 있는지, 이름 길이 |
| `is_duplicate`, `is_sensitive` | 중복 파일, 민감 파일 (둘 다 AI에 안 보냄) |
| `rule_category` | 규칙 기반 분류 (내 컴퓨터에서 키워드로 판단) |
| `ai_category`, `ai_course` | Gemini 분류와 과목 (저장된 결과. 아직 분석 안 됐으면 빈칸) |
| `true_category`, `true_course` | 정답 (직접 입력. 연습 샘플은 미리 채워짐) |

## A. 정확도 비교 워크플로

```
CSV Reader → Row Filter (중복·민감 제외) → Row Filter (true_category, ai_category 있는 행) ─┬→ Scorer (true vs rule)
                                                                                            └→ Scorer (true vs ai)
```

| 순서 | 노드 | 설정 |
|---|---|---|
| 1 | **CSV Reader** | `knime\data\files.csv`, Encoding: UTF-8 |
| 2 | **Row Filter** | `is_duplicate` = 0 그리고 `is_sensitive` = 0 인 행만 (두 번 연결하거나 Rule-based Row Filter: `$is_duplicate$ = 0 AND $is_sensitive$ = 0 => TRUE`) |
| 3 | **Row Filter** | `true_category`와 `ai_category`가 비어 있지 않은 행만 (Missing value 제외) |
| 4 | **Scorer** ① | First column: `true_category`, Second column: `rule_category` → Accuracy, Confusion Matrix |
| 5 | **Scorer** ② | First column: `true_category`, Second column: `ai_category` |
| 6 | (선택) **Bar Chart** | `ai_category`별 개수 → "내 다운로드 폴더의 ○%는 수업 자료" |

발표 포인트: 두 Scorer의 Accuracy를 나란히. Confusion Matrix에서 **규칙 기반이 어떤 분류를 헷갈리는지**(예: 카톡 사진 속 칠판 → 사진으로 착각)를 보여 주면 생성형 AI를 쓰는 이유가 됩니다.

## B. 이름만으로 분류하는 모델 → Gemini 호출 줄이기

생성형 AI(Gemini)가 붙인 `ai_category`를 **정답 삼아**, 내용을 읽지 않고 이름·확장자·크기만 보는 가벼운 모델을 학습합니다. 모델이 **확실하다고 한 파일**만 Gemini를 건너뛰면 됩니다.

```
CSV Reader → Row Filter (ai_category 있는 행) → Partitioning 7:3 ─┬→ Decision Tree Learner ─┐
                                                                  │                         ↓
                                                                  └──────────→ Decision Tree Predictor → Column Aggregator(Max) → Rule Engine(확실?) → Row Filter(확실) → Scorer
```

| 순서 | 노드 | 설정 |
|---|---|---|
| 1 | **CSV Reader** | 위와 같음 |
| 2 | **Row Filter** | `ai_category`가 비어 있지 않은 행 (중복·민감은 원래 AI에 안 가므로 자동으로 빠짐) |
| 3 | **Column Filter** | 남길 열: `ext`, `kind`, `size_kb`, `name_type`, `name_has_date`, `name_has_version`, `name_length`, `ai_category` (내용 정보는 쓰지 않음) |
| 4 | **Partitioning** | Relative 70%, Draw randomly, Use random seed: 0 (강의와 같음) |
| 5 | **Decision Tree Learner** | Class column: `ai_category`, Quality measure: Gini index, Min number records per node: 2 |
| 6 | **Decision Tree Predictor** | 위쪽 입력: Learner, 아래쪽 입력: Partitioning의 두 번째 출력. **Append columns with normalized class distribution** 체크 |
| 7 | **Column Aggregator** | 대상 열: `P (ai_category=…)` 확률 열 전부, Aggregation: Maximum → 새 열 이름 `confidence` |
| 8 | **Rule Engine** | `$confidence$ >= 0.9 => "확실"` / `TRUE => "애매"` → 새 열 `route` |
| 9 | **Row Filter** | `route` = 확실 |
| 10 | **Scorer** | First column: `ai_category`, Second column: `Prediction (ai_category)` → 확실한 파일에서의 정확도(= 정밀도) |

계산할 숫자:
- **건너뛸 수 있는 비율** = (9번에 남은 행 수) ÷ (6번 전체 행 수)
- **건너뛸 때의 정밀도** = 10번 Accuracy. 틀리면 잘못 정리되므로 **정밀도가 높아야(예: 95% 이상)** 의미가 있습니다. 낮으면 8번의 기준(0.9)을 올립니다.

비교 (강의처럼):
- 5·6번을 **Random Forest Learner/Predictor**(Number of models 100, seed 0)로 바꿔 같은 숫자를 비교합니다.
- 발표 문장 예: "테스트 파일 중 ○%는 이름만으로 정밀도 ○%로 분류됐다. 이 파일들은 Gemini를 건너뛰면 호출이 ○% 줄고, 그만큼 빨라지고, 밖으로 보내는 파일도 줄어든다."

> 학습한 모델을 서비스에 실제로 연결하는 것(PMML 내보내기)은 진짜 KNIME 파일로 호환성을 확인한 뒤 진행합니다. 연결 전에는 발표에서 "줄였다"가 아니라 **"줄일 수 있다(측정값)"** 라고 말해야 합니다.

## 캡처 체크리스트

- [ ] 워크플로 전체 화면 (A, B)
- [ ] Scorer ①② Accuracy와 Confusion Matrix
- [ ] Decision Tree 보기 (어떤 이름 특징이 가장 중요한지)
- [ ] B의 건너뛸 수 있는 비율과 정밀도
- [ ] (선택) 분류별 Bar Chart
- [ ] 워크플로 파일 내보내기: File → Export KNIME Workflow → `knime/file-secretary.knwf`로 저장해 GitHub에 올리기
