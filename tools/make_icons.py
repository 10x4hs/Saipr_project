"""앱 아이콘(PWA·홈 화면용)을 그린다 — 시안의 유리 구슬 얼굴. 외부 라이브러리 없이 PNG를 직접 쓴다.

    python tools/make_icons.py

결과: app/web/static/icons/icon-{192,512}.png, maskable-512.png, apple-touch-icon.png(180)
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "icons"


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def over(dst, src, alpha):
    return mix(dst, src, max(0.0, min(1.0, alpha)))


def pixel(u, v, pad):
    """(u, v)는 0~1 좌표. pad는 마스커블 아이콘 안전 영역(가운데 80%)용 축소 비율."""
    sky = mix((0x6F, 0x76, 0x7F), (0xC2, 0xC0, 0xB8), v)
    # 아래쪽 초원 보케
    for cx, cy, r, col in ((0.2, 1.0, 0.45, (0x3C, 0x55, 0x30)), (0.8, 1.05, 0.5, (0x55, 0x70, 0x3F))):
        d = math.hypot(u - cx, v - cy) / r
        sky = over(sky, col, (1 - d) * 1.4)
    # 위쪽 광원
    d = math.hypot(u - 0.42, v + 0.05) / 0.55
    sky = over(sky, (255, 255, 255), (1 - d) * 0.8)

    # 유리 구슬
    x, y = (u - 0.5) / pad, (v - 0.5) / pad
    r = math.hypot(x, y)
    R = 0.34
    if r <= R:
        t = r / R
        glass = over(sky, (255, 255, 255), 0.10 + 0.55 * t**3)  # 가장자리일수록 밝은 테
        glass = over(glass, (185, 212, 160), max(0.0, y / R) * 0.35)  # 아래쪽 초록 반사
        # 윗면 하이라이트
        hd = math.hypot((x + 0.02) / 0.17, (y + 0.24) / 0.06)
        glass = over(glass, (255, 255, 255), (1 - hd) * 0.9)
        # 무지개 반사
        rd = math.hypot((x + 0.13) / 0.11, (y - 0.17) / 0.035)
        rainbow = mix((255, 143, 208), (143, 240, 255), max(0.0, min(1.0, (x + 0.24) / 0.22)))
        glass = over(glass, rainbow, (1 - rd) * 0.6)
        # 얼굴: 둥근 사각형 테두리 + 눈 두 개 + 받침
        fx, fy = abs(x), y + 0.005
        w, h, rad, th = 0.115, 0.085, 0.03, 0.022

        def rbox(px, py, w, h, rad):
            qx, qy = px - (w - rad), py - (h - rad)
            return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - rad

        edge = abs(rbox(fx, abs(fy), w, h, rad))
        if edge < th / 2:
            glass = over(glass, (255, 255, 255), 0.95)
        if abs(fx - 0.04) < 0.011 and abs(fy) < 0.03:
            glass = over(glass, (255, 255, 255), 0.95)
        if abs(x) < 0.1 and abs(y - 0.13) < 0.009:
            glass = over(glass, (255, 255, 255), 0.85)
        # 바깥 테두리 선
        if R - r < 0.006:
            glass = over(glass, (255, 255, 255), 0.7)
        return glass
    # 구슬 그림자·글로우
    glow = max(0.0, 1 - (r - R) / 0.12)
    return over(sky, (255, 255, 255), glow * 0.35)


def render(size, pad=1.0, ss=3):
    rows = []
    for j in range(size):
        row = bytearray([0])
        for i in range(size):
            acc = [0.0, 0.0, 0.0]
            for sj in range(ss):
                for si in range(ss):
                    c = pixel((i + (si + 0.5) / ss) / size, (j + (sj + 0.5) / ss) / size, pad)
                    for k in range(3):
                        acc[k] += c[k]
            row += bytes(int(max(0, min(255, a / (ss * ss)))) for a in acc)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, pad in (
        ("icon-192.png", 192, 1.0),
        ("icon-512.png", 512, 1.0),
        ("maskable-512.png", 512, 0.78),
        ("apple-touch-icon.png", 180, 0.92),
    ):
        (OUT / name).write_bytes(render(size, pad, ss=2 if size > 300 else 3))
        print("wrote", name)
