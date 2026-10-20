# 함께읽기 앱 (Flet)

같은 책을 각자의 속도로, 친구와 함께 읽는 소셜 독서 앱이에요. 화면은 모두 Python([Flet](https://flet.dev))으로 만들었고, 서버는 저장소 루트의 FastAPI 백엔드를 그대로 써요.

## 화면

| 탭 | 하는 일 |
|---|---|
| 홈 | 이어 읽기, 오늘 목표 링, 친구 소식, 내 읽기방·배틀 |
| 둘러보기 | 검색, 장르, 인기·새 책, 위키백과 책 소개, 외부 책 가져오기 |
| 서재 | 읽는 중 · 읽고 싶은 · 완독 책장, 밑줄 모음(공유 · 밀어서 삭제) |
| 함께 | 친구 피드(응원), 친구 찾기(친구 코드), 읽기방, 팀 배틀 리그 |
| 나 | 오늘 · 연속 기록, 주간 그래프, 12주 잔디, 연간 목표, 배지, 포인트, 알림, 설정 |

리더에서는 쪽을 넘기며 읽고, 문장을 골라 밑줄·메모를 남기고, 친구 반응을 봐요. 아직 안 읽은 곳의 반응은 스포일러 가드로 가려 둬요. 읽는 속도를 배워서 남은 시간을 알려 주고, 잠깐 다른 앱에 다녀오면 독서 시간을 멈춰요.

디자인은 **설정 → 디자인**에서 글래스(처음 시안) · 머티리얼 3 · iOS 중에 고르고, 각각 라이트·다크를 쓸 수 있어요.

## 실행

먼저 서버를 켜요(저장소 루트에서).

```bash
pip install -e ".[dev]"
alembic upgrade head && python -m app.seed   # 데모 계정: seoyeon@demo.kr / junho@demo.kr, 비밀번호 demo1234
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

그다음 앱을 켜요(`mobile/`에서).

```bash
uv sync                       # 또는: pip install -e . "flet-cli<1.1" "flet-desktop<1.1" "flet-web<1.1"
flet run src/main.py          # 데스크톱 창 (폰 크기)
flet run --web src/main.py    # 브라우저
```

첫 화면 아래의 **서버** 버튼에서 주소를 바꿀 수 있어요. 기본값은 `http://127.0.0.1:8000`이에요.

- 안드로이드 에뮬레이터 → `http://10.0.2.2:8000`
- 같은 와이파이의 실제 폰 → `http://<내 컴퓨터 IP>:8000`
- 배포 서버 → `https://...` (`render.yaml` 참고)

## 안드로이드 APK 만들기

필요한 것: **JDK 17**, 그리고 Android SDK(없으면 `flet build`가 받아 줘요). Flutter SDK도 처음 빌드할 때 자동으로 받아요.

```bash
# macOS 예시
brew install --cask temurin@17
export JAVA_HOME=$(/usr/libexec/java_home -v 17)

cd mobile
flet build apk
# 결과물: build/apk/ 폴더의 .apk 파일
```

폰에 설치하려면 APK 파일을 폰으로 옮겨서 열거나, USB 디버깅을 켜고 `adb install build/apk/<파일 이름>.apk`를 실행해요.

> 안드로이드는 보안 때문에 `http://` 주소 접속을 막을 수 있어요. 실제 폰에서 개발 서버에 연결되지 않으면 https 배포 서버 주소를 쓰세요.

## 개발용 환경 변수

화면 확인이나 시연 준비를 빠르게 하려고 만든 스위치예요. 출시 빌드에서는 쓰지 않아요.

| 변수 | 예시 | 뜻 |
|---|---|---|
| `SAIPR_SERVER` | `http://127.0.0.1:8010` | 기본 서버 주소 |
| `SAIPR_DEMO_LOGIN` | `seoyeon@demo.kr` | 이 계정으로 바로 로그인 (`이메일:비밀번호`, 비밀번호 생략 시 demo1234) |
| `SAIPR_DESIGN` | `material:dark` | 디자인 고정 (`glass` · `material` · `cupertino`) |
| `SAIPR_OPEN` | `read:1` | 시작 화면 — `tab:N` · `book:id` · `read:id` · `room:id` · `user:id` · `battle:id` · `team:id` · `settings` · `notifications` |

## 구조

```
src/
  main.py               진입점
  saipr/app.py          앱 상태 · 화면 이동 · 로그인 · 실시간 연결
  saipr/core/           화면과 상관없는 로직 (테스트 대상)
    api.py              서버 API 클라이언트 (Bearer 토큰)
    realtime.py         WebSocket 채널 (자동 재연결 · 놓친 이벤트 이어 받기)
    reading.py          독서 시간 측정 · 이벤트 큐 · 읽기 속도 학습
    store.py            기기 저장소 (설정 · 오프라인 본문)
    fmt.py              시간 · 숫자 문구, 한국어 단어 단위 줄바꿈
  saipr/ui/             디자인 시스템 (theme.py) · 공용 위젯
  saipr/views/          화면들
  assets/               아이콘 · 글꼴 (Pretendard, 고운바탕 — OFL)
tests/                  core 테스트
```

## 테스트

```bash
cd mobile && pytest -q
```
