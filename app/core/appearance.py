"""화면 꾸미기 선택지. 배경 모양은 app/static/app.css의 `.fx[data-bg=…]` 규칙과 짝을 이룬다."""

MODES = {"auto": "자동", "light": "밝게", "dark": "어둡게"}

# 묶음 → [(id, 이름, 움직임 여부)]
BACKGROUNDS: dict[str, list[tuple[str, str, bool]]] = {
    "기본": [
        ("plain", "기본", False),
        ("ash", "잿빛", False),
        ("sand", "모래", False),
        ("sage", "세이지", False),
        ("fog", "안개", False),
    ],
    "책": [
        ("study", "서재", False),
        ("paper", "종이", False),
        ("inkwash", "수묵", False),
        ("leather", "가죽 장정", False),
        ("grid", "원고지", False),
        ("candle", "촛불 독서", True),
    ],
    "자연": [
        ("forest", "숲", False),
        ("ocean", "물결", True),
        ("hills", "언덕", False),
        ("desert", "사막", False),
        ("petals", "꽃잎", True),
        ("sunset", "노을", False),
        ("seaside", "바닷가", False),
    ],
    "날씨": [
        ("sunny", "맑음", False),
        ("clouds", "구름", True),
        ("rain", "비", True),
        ("snow", "눈", True),
        ("storm", "뇌우", True),
        ("dawn", "새벽", False),
    ],
    "우주": [
        ("stars", "별밤", True),
        ("aurora", "오로라", True),
        ("nebula", "성운", False),
        ("prism", "프리즘", False),
        ("flow", "흐르는 빛", True),
        ("lava", "용암", True),
    ],
}
BG_IDS = {bid for group in BACKGROUNDS.values() for bid, _, _ in group}

# 배경의 밝기. 글자색은 테마(밝게·어둡게)가 아니라 실제로 깔린 배경을 따라야 한다 —
# 밝은 테마에서 어두운 배경을 고르면 검은 글자가 검은 배경 위에 놓여 안 보였다.
# "auto" = 바탕이 테마 색(var(--bg))이라 테마를 그대로 따라간다.
# 나머지 배경은 모두 짙은 바탕(--base)이고, 밝은 테마의 밝기 필터를 거쳐도 어둡다.
TONES = ("auto", "dark", "light")
BG_TONE: dict[str, str] = {bid: "dark" for bid in BG_IDS} | {"plain": "auto"}

ACCENTS = {
    "mono": ("기본", "#fafafa"),
    "multi": ("여러 색", "#ff9ec4"),
    "blue": ("파랑", "#5aa0ff"),
    "indigo": ("남색", "#8b93ff"),
    "violet": ("보라", "#c39bff"),
    "pink": ("분홍", "#ffb3c7"),
    "red": ("빨강", "#ff7a6b"),
    "orange": ("주황", "#ffa95a"),
    "yellow": ("노랑", "#ffd95a"),
    "green": ("초록", "#7fd99a"),
    "teal": ("청록", "#5fd3d3"),
    "gray": ("회색", "#b7bcc6"),
}

DEFAULT = {"mode": "auto", "bg": "plain", "accent": "pink"}


def resolve(settings: dict | None) -> dict:
    """저장된 값 중 알려진 것만 받아들이고 나머지는 기본값으로."""
    s = dict(DEFAULT)
    for key, allowed in (("mode", MODES), ("bg", BG_IDS), ("accent", ACCENTS)):
        if settings and settings.get(key) in allowed:
            s[key] = settings[key]
    s["accent_hex"] = ACCENTS[s["accent"]][1]
    s["bg_tone"] = tone_of(s["bg"])
    return s


def tone_of(bg: str) -> str:
    """배경 id → "dark" | "light" | "auto". 모르는 id는 테마를 따른다."""
    return BG_TONE.get(bg, "auto")
