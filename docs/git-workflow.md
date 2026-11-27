# Git 작업 가이드

평가 기준의 '강의 내용 활용'에서 **이 저장소의 Git 기록**이 그대로 증거가 됩니다. 처음부터 아래 방식으로 쌓아 두세요.

## 1. 저장소 시작

GitHub에서 빈 저장소 `file-secretary`를 만든 뒤:

```bash
cd file-secretary
git init
git add .
git commit -m "chore: 파일 정리 비서 MVP 초기 코드"
git branch -M main
git remote add origin https://github.com/<아이디>/file-secretary.git
git push -u origin main
```

## 2. 브랜치 전략 (GitHub Flow)

- `main`: 항상 실행 가능한 상태
- `feature/<기능>`: 작업 브랜치 → GitHub에서 **Pull Request** → 확인 후 merge

| 브랜치 예시 | 할 일 |
|---|---|
| `feature/real-folder-test` | 내 실제 파일로 시험하며 이름·분류 규칙 개선 |
| `feature/prompt-tuning` | `api/app/analyzer.py` 프롬프트 개선 |
| `feature/ui-polish` | `web/app.py` 화면 다듬기 |
| `feature/knime-analysis` | (선택) `knime/` 워크플로와 결과 캡처 |
| `docs/presentation` | 발표 자료, 시연 영상, README 캡처 |

```bash
git switch -c feature/prompt-tuning
# ... 작업 ...
git add . && git commit -m "feat(analyzer): 과목 별칭을 프롬프트에 함께 전달"
git push -u origin feature/prompt-tuning
# GitHub에서 PR 생성 → merge → 로컬 정리
git switch main && git pull
```

## 3. 자동 검사 (GitHub Actions)

`.github/workflows/ci.yml` — main에 올리거나 PR을 열면 GitHub가 자동으로:

| 작업 | 내용 |
|---|---|
| test | 테스트 전체를 SQLite와 **PostgreSQL 컨테이너** 양쪽에서 실행 |
| docker | `docker compose build`로 이미지 빌드 확인 + Trivy 이미지 취약점 검사(보고만) |
| lint | `shellcheck scripts/*.sh` |

PR 화면에 초록 체크(✔)가 뜨면 merge합니다. 빨간 X면 'Details'에서 실패 이유를 확인합니다.

## 4. 커밋 규칙

- `type(scope): 요약` 형식 (Conventional Commits). 예: `fix(planner): 같은 이름이 있으면 번호 붙이기`
- 한 커밋에는 한 가지 목적만.

## 5. 발표용 캡처 체크리스트

| 강의 | 장면 |
|---|---|
| Git 1 | `git status`, `git add`, `git commit` |
| Git 2 | `git diff`, 브랜치 생성·전환, conflict 해결 커밋, `git revert` |
| Git 3 | `git push` / `git pull`, GitHub의 PR 목록, PR의 자동 검사 초록 체크 |
| 전체 | `git log --all --graph --oneline` — 브랜치와 merge가 보이는 그래프 |

## 6. 주의

- `.env`는 절대 커밋하지 않습니다. 이미 올렸다면 키를 **재발급**하세요 (revert해도 이력에 남음).
- `demo/inbox/` 안의 파일은 `.gitignore`에 있습니다 (연습 폴더는 매번 초기화).
