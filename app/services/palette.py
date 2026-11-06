"""참가자 색 — 같은 사람은 어디서나(레이스 트랙 · 순위 · 리더의 '지금 읽는 중' 칩) 같은 색으로 보인다.

색은 사용자 id만으로 정해진다: ``PALETTE[id % len(PALETTE)]``.
브라우저 쪽 짝은 ``app/static/palette.js`` 의 ``colorFor(userId)`` 이고, 두 목록은 순서까지 똑같아야 한다
(tests/test_palette.py 가 둘을 비교한다). 색을 바꾸려면 두 파일을 함께 고친다.

밝은/어두운 테마 모두에서 흰 글자를 올려도 읽히고, 서로 헷갈리지 않는 중간 밝기의 색만 쓴다.
정원(8명)만큼 준비해 두어 연달아 가입한 친구들은 서로 다른 색을 받는다.
"""

PALETTE: tuple[str, ...] = (
    "#E8603C",  # 주홍
    "#2F80ED",  # 파랑
    "#1FA463",  # 초록
    "#9B51E0",  # 보라
    "#E0457B",  # 분홍
    "#C9920A",  # 겨자
    "#0E9AA7",  # 청록
    "#5B6CD9",  # 남색
)


def color_for(user_id: int) -> str:
    """사용자 id에 묶인 고정 색(#RRGGBB)."""
    return PALETTE[abs(int(user_id)) % len(PALETTE)]
