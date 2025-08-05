# 나만의 펀드 데모

간단한 포트폴리오 비중 추천 및 KIS 증권 주문 데모입니다. FastAPI로 구현되며 Render Web Service 배포를 목표로 합니다.

## 실행 방법

```bash
# 환경설정
cp .env.example .env  # 필요 시 값 수정

# 의존성 설치
pip install -r requirements.txt

# 서버 실행
uvicorn app.main:app --reload
```

## 주요 기능
- `/` 단일 페이지에서 환경설정과 포트폴리오 입력
- `/api/health` 헬스 체크
- `/api/kis/token` 토큰 발급 (메모리 캐시)
- `/api/quotes/daily` 일자별 시세 조회 (모드에 따라 KIS 또는 Mock)
- `/api/portfolio/weights` 종목 비중 추천
- `/api/orders/preview` 주문 프리뷰 생성
- `/api/orders/execute` 모의 주문 실행

## Render 배포
1. 이 저장소를 Fork 후 Render에서 새 Web Service 생성
2. Docker 또는 Python 환경 선택 후 `uvicorn app.main:app --host 0.0.0.0 --port $PORT` 명령으로 실행
3. Environment Variables 설정
   - `KIS_APP_KEY`, `KIS_APP_SECRET` 등 `.env.example` 참고
   - `KIS_MODE`를 `real`로 변경하면 실전 도메인과 TR이 사용됩니다.
   - `KIS_MOCK=1`일 경우 외부 호출 없이 Mock 데이터로 동작합니다.

## 테스트용 스텁
`KIS_MOCK=1`로 설정하면 가격조회 및 주문이 모두 Mock 데이터로 처리되어 KIS 계정이 없어도 동작을 확인할 수 있습니다.

## 기타
- `api.http`: REST Client 플러그인으로 테스트 가능한 예시 요청 모음
- `demo.py`: 로컬 서버와 상호작용하는 간단한 스크립트