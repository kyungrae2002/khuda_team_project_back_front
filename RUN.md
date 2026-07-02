# travel-buddy 실행 가이드

단체 여행 일정 생성 서비스 — FastAPI 백엔드 + Streamlit 데모 UI.

## 0. 사전 준비물

- Python 3.11+
- Docker Desktop (Postgres 실행용)
- OpenAI API 키 (`OPENAI_API_KEY`) — 슬롯 추출/쿼리 생성/장소 선별/일정 비평/서사화 전부 OpenAI 구조화 출력(`response_format: json_schema`, strict 모드) 사용
- Google Places API (New) 키 (`GOOGLE_PLACES_API_KEY`) — Places Text Search / Nearby Search 권한 필요

기본 모델은 `app/services/*.py` 상단의 `DEFAULT_MODEL` 상수에 하드코딩되어 있습니다(`slot_extractor`/`place_selector`/`itinerary_builder`/`narrator`는 `gpt-4o`, 저비용 티어인 `query_builder`는 `gpt-4o-mini`). 계정에서 사용 가능한 모델이 다르면 해당 상수만 바꾸면 됩니다.

키가 없으면 `/health`와 DB 관련 기능은 동작하지만, `/sessions/upload`·`/sessions/{id}/itinerary`·`/evaluation`은 외부 API 호출 시점에 502 에러를 반환합니다.

## 1. 환경 변수 설정

```sh
cp .env.example .env
```

`.env`를 열어 아래 값을 채웁니다.

```
OPENAI_API_KEY=sk-...
GOOGLE_PLACES_API_KEY=AIza...
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/travel_buddy
```

## 2. Postgres 기동

```sh
docker compose up -d
```

`docker ps`로 `travel-buddy-postgres` 컨테이너가 `Up` 상태인지 확인하세요.

## 3. 백엔드 의존성 설치 + 마이그레이션

```sh
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash. PowerShell은 .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# .env의 DATABASE_URL을 읽어 스키마를 최신 상태로 적용
alembic upgrade head
```

## 4. 백엔드 실행

```sh
uvicorn app.main:app --reload --port 8000
```

- API 문서(Swagger): http://localhost:8000/docs
- 헬스체크: http://localhost:8000/health

### 제공되는 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| POST | `/sessions/upload` | 카카오톡 대화(.txt) 업로드 → 세션 생성 + 슬롯 추출·저장 |
| POST | `/sessions/{session_id}/itinerary` | 확정 슬롯 기반 장소 검색 → 2차 선별 → 동선 생성/검증·수정 루프 → 서사화 |
| GET | `/evaluation` | 골드셋 대비 슬롯 추출 지표(F1) + 최근 `ValidationLog` 기반 위반 통계 |

`POST /sessions/upload`는 `multipart/form-data`로 `file` 필드에 `.txt` 파일을 담아 보냅니다.
`POST /sessions/{id}/itinerary`는 `{"days": 2}`처럼 여행 일수를 JSON body로 받습니다.

## 5. 데모 UI(Streamlit) 실행

백엔드가 8000번 포트에서 떠 있는 상태에서, **새 터미널**을 열어:

```sh
python -m venv .venv-demo
source .venv-demo/Scripts/activate
pip install -r demo/requirements.txt

streamlit run demo/app.py
```

기본적으로 `http://localhost:8000`을 호출합니다. 다른 주소를 쓰려면:

```sh
BACKEND_URL=http://localhost:9000 streamlit run demo/app.py
```

브라우저가 자동으로 열리지 않으면 터미널에 출력되는 URL(보통 http://localhost:8501)로 접속하세요.

### 데모 사용 순서

1. **대화 업로드** 탭에서 카카오톡 대화 내보내기 `.txt` 파일 업로드 → 추출된 슬롯이 확정(초록)/미정(회색)/충돌(빨강) 뱃지로 표시됩니다.
2. **일정 생성** 탭에서 여행 일수를 입력하고 "일정 생성" 클릭 → 장소 검색·선별·동선 생성/검증까지 수 분 걸릴 수 있습니다. day별 expander로 결과가 표시되고, "AI 검증 N회 수정" 문구로 비평 루프 결과를 보여줍니다.
3. **비교** 탭에서 "지표 불러오기"를 누르면 내장 골드셋 대비 슬롯 추출 F1과 최근 일정 검증 통계를 확인할 수 있습니다.

## 6. 백엔드 테스트 실행 (선택)

외부 API 호출 없이(mock 처리) 순수 로직만 검증하는 유닛테스트입니다:

```sh
source .venv/Scripts/activate
python -m unittest discover -s tests -v
```

## 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `/sessions/upload`가 502 | `OPENAI_API_KEY` 미설정 또는 슬롯 추출 실패. 서버 로그 확인 |
| `/sessions/{id}/itinerary`가 422 | 목적지 등 필수 슬롯이 confirmed 상태가 아님. 먼저 대화에서 목적지가 확정됐는지 확인 |
| `/sessions/{id}/itinerary`가 502 | Google Places API 키 문제이거나 OpenAI 호출 실패. 서버 로그의 상세 메시지 확인 |
| `/sessions/upload` 응답은 오는데 슬롯이 이상함 | `DEFAULT_MODEL`이 계정에서 접근 불가한 모델일 수 있음. 서버 로그의 OpenAI 에러 메시지 확인 후 모델명 조정 |
| Streamlit에서 "백엔드 호출 실패" | 백엔드가 8000번 포트에서 실행 중인지, `BACKEND_URL`이 맞는지 확인 |
| `alembic upgrade head` 실패 | Postgres 컨테이너가 떠 있는지(`docker ps`), `.env`의 `DATABASE_URL`이 맞는지 확인 |

## 프로젝트 구조 요약

```
app/
  api/            FastAPI 라우터 (health, sessions, evaluation)
  core/           설정(config), DB 세션(database)
  models/         SQLAlchemy 모델
  schemas/        Pydantic 스키마 (API I/O, LLM 구조화 출력)
  services/       비즈니스 로직 — 파싱, 슬롯 추출, 쿼리 생성, 장소 검색/선별,
                  동선 생성/검증/비평, 서사화, 파이프라인 오케스트레이션
demo/
  app.py          Streamlit 데모 UI (requests로 백엔드 호출)
alembic/          DB 마이그레이션
tests/            유닛테스트 (전부 mock 기반, 인프라 불필요)
docker-compose.yml  Postgres
```
