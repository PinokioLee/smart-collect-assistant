"""슬라이드2(기술 아키텍처)용 시스템 구성도 PNG 생성 (PIL).

실제 기술명을 사용한 멀티에이전트 파이프라인 다이어그램.
네이비/민트/그레이 팔레트로 템플릿과 통일.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NAVY = (26, 54, 93)
MINT = (78, 205, 196)
MINT_DK = (59, 184, 176)
GRAY = (102, 102, 102)
LGRAY = (229, 229, 229)
BG = (248, 249, 250)
INK = (26, 26, 26)
WHITE = (255, 255, 255)

FONT = r"C:\Windows\Fonts\malgun.ttf"
FONTB = r"C:\Windows\Fonts\malgunbd.ttf"

W, H = 980, 690
SCALE = 2  # 슈퍼샘플링


def _f(path, size):
    return ImageFont.truetype(path, size * SCALE)


def _center(d, box, text, font, fill):
    x0, y0, x1, y1 = box
    tb = d.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text(((x0 + x1) / 2 - tw / 2, (y0 + y1) / 2 - th / 2 - tb[1]),
           text, font=font, fill=fill)


def make(out_path: str) -> str:
    img = Image.new("RGB", (W * SCALE, H * SCALE), WHITE)
    d = ImageDraw.Draw(img)

    f_title = _f(FONTB, 21)
    f_box = _f(FONTB, 18)
    f_sub = _f(FONT, 13)
    f_chip = _f(FONTB, 15)
    f_small = _f(FONT, 12)
    f_rail = _f(FONTB, 13)

    M = 30 * SCALE
    cx0, cx1 = M, W * SCALE - M
    y = M

    # 타이틀
    d.text((M, y), "Smart Collect — Multi-Agent Pipeline", font=f_title, fill=NAVY)
    y += 40 * SCALE

    # 입력 칩 2개
    chip_h = 46 * SCALE
    gap = 16 * SCALE
    cw = (cx1 - cx0 - gap) // 2
    for i, label in enumerate(["INPUT  취합요청 메일", "INPUT  제출 엑셀 N개"]):
        x0 = cx0 + i * (cw + gap)
        d.rounded_rectangle([x0, y, x0 + cw, y + chip_h], radius=10 * SCALE,
                            fill=BG, outline=LGRAY, width=2)
        _center(d, (x0, y, x0 + cw, y + chip_h), label, f_chip, NAVY)
    y += chip_h + 14 * SCALE

    # 에이전트 박스 5개 (세로 흐름)
    agents = [
        ("Requirement Analysis Agent", "Azure OpenAI  ·  휴리스틱 폴백", MINT),
        ("Supervisor (Planning)", "Tree of Thoughts 규칙 선택", NAVY),
        ("Excel Validation Agent", "pandas / openpyxl  ·  4종 규칙검증", MINT),
        ("Self-Correction Agent", "Self-Refine 루프 (개선 시에만 채택)", NAVY),
        ("Report Agent", "결과 요약  ·  KPI", MINT),
    ]
    box_h = 64 * SCALE
    arrow_h = 22 * SCALE
    bw = cx1 - cx0
    for i, (title, sub, accent) in enumerate(agents):
        by = y
        d.rounded_rectangle([cx0, by, cx1, by + box_h], radius=12 * SCALE,
                            fill=WHITE, outline=LGRAY, width=2)
        # 좌측 액센트 바
        d.rounded_rectangle([cx0, by, cx0 + 10 * SCALE, by + box_h],
                            radius=6 * SCALE, fill=accent)
        d.text((cx0 + 26 * SCALE, by + 12 * SCALE), title, font=f_box, fill=INK)
        d.text((cx0 + 26 * SCALE, by + 38 * SCALE), sub, font=f_sub, fill=GRAY)
        # 단계 번호 원
        ncx, ncy = cx1 - 30 * SCALE, by + box_h // 2
        d.ellipse([ncx - 14 * SCALE, ncy - 14 * SCALE, ncx + 14 * SCALE,
                   ncy + 14 * SCALE], fill=accent)
        _center(d, (ncx - 14 * SCALE, ncy - 14 * SCALE, ncx + 14 * SCALE,
                    ncy + 14 * SCALE), str(i + 1), f_chip, WHITE)
        y += box_h
        if i < len(agents) - 1:
            # 화살표
            ax = (cx0 + cx1) // 2
            d.line([ax, y, ax, y + arrow_h], fill=NAVY, width=3 * SCALE)
            d.polygon([(ax - 7 * SCALE, y + arrow_h - 7 * SCALE),
                       (ax + 7 * SCALE, y + arrow_h - 7 * SCALE),
                       (ax, y + arrow_h)], fill=NAVY)
            y += arrow_h

    y += 14 * SCALE
    # 출력 칩 2개
    for i, label in enumerate(["OUTPUT  최종 취합본.xlsx", "OUTPUT  오류 보고서.xlsx"]):
        x0 = cx0 + i * (cw + gap)
        d.rounded_rectangle([x0, y, x0 + cw, y + chip_h], radius=10 * SCALE,
                            fill=NAVY, outline=NAVY, width=2)
        _center(d, (x0, y, x0 + cw, y + chip_h), label, f_chip, WHITE)
    y += chip_h + 14 * SCALE

    # 하단 레일 (오케스트레이션/런타임)
    rail_h = 38 * SCALE
    d.rounded_rectangle([cx0, y, cx1, y + rail_h], radius=10 * SCALE,
                        fill=(240, 253, 251), outline=MINT, width=2)
    _center(d, (cx0, y, cx1, y + rail_h),
            "LangGraph StateGraph  ·  FastAPI  ·  React/TS  ·  Langfuse(opt)",
            f_rail, MINT_DK)

    img = img.resize((W, H), Image.LANCZOS)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    p = make(r"C:\Users\LHJ\AI_Master\presentation\architecture.png")
    print("saved", p)
