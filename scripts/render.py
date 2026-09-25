# -*- coding: utf-8 -*-
"""
render · 在原图上画定位框与结论，产出 result.jpg

要求：
  - 坐标回映射：0–1000 归一化框 → 原图像素，可当场验算；
  - 每条结论都能「点回原图」：flag 的 region 与该区域框同色，命中过敏的区域加粗加角标；
  - 画图全程本地：这一模块只用 PIL 在原图上画框与文字，不调用任何外部服务。
    （注意：这说的是**画图这一步**不出本机；「图片发往推理端点」是另一回事，
     对外表述时不要把两者混成一句「画面不出设备」。）

中文字体说明：Pillow 自带字体不含 CJK，这里做一条字体探测链。
一个都找不到时不报错，退化成「框 + 英文标签 + 数字」仍然可用，并在 report 里记一条 note。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .regions import REGION_BY_KEY, REGION_COLORS

_FONT_CHAIN = [
    # Windows（本项目主要运行环境）
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/Deng.ttf",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Songti.ttc",
    # 项目自带（用户可以自己丢一个进去）
    str(config.SKILL_DIR / "references" / "fonts" / "NotoSansSC.ttf"),
]

# 状态 → 颜色。图上不再用 emoji：
# Pillow 的 truetype 画不出彩色 emoji，🚩 / ✅ / ⚠️ / 🚫 会糊成一串「□」，
# 早期版本的 result.jpg 底部就是这样一排方框。改用色块 + 符号，任何机器上都不会缺字形。
_LEVEL_RGB = {
    "bad": (247, 112, 103),
    "warn": (227, 163, 65),
    "good": (63, 185, 80),
    "info": (120, 170, 255),
}
_LEVEL_GLYPH = {"bad": "x", "warn": "!", "good": "+", "info": "i"}
_LEVEL_ORDER = {k: i for i, k in enumerate(_LEVEL_RGB)}


def _worst_level(levels: List[str]) -> str:
    """同一区域挂了多个 flag 时，取最严重的那个等级来画角标。"""
    safe = [x for x in (levels or []) if x in _LEVEL_ORDER]
    return min(safe, key=lambda x: _LEVEL_ORDER[x]) if safe else "warn"


def _find_font(size: int):
    from PIL import ImageFont

    for p in _FONT_CHAIN:
        try:
            if Path(p).exists():
                return ImageFont.truetype(p, size), True
        except Exception:
            continue
    try:
        return ImageFont.load_default(), False
    except Exception:  # pragma: no cover
        return None, False


def _text(draw, xy, text: str, font, fill, anchor="la"):
    if not text:
        return
    try:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
    except Exception:
        draw.text(xy, text.encode("ascii", "replace").decode(), font=font, fill=fill, anchor=anchor)


def _hex_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _wrap_boxes(image, grounding) -> List[Dict[str, Any]]:
    return [r.to_dict() for r in grounding.regions if r.found]


def annotate(
    image_path,
    *,
    grounding,
    judgment: Dict[str, Any],
    out_path=None,
    highlight_regions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """画一张带定位框与结论的 result.jpg，返回产物信息。"""
    from PIL import Image, ImageDraw

    src = Path(image_path)
    out_dir = Path(out_path).parent if out_path else config.ensure_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = Path(out_path) if out_path else out_dir / config.MEDIA_FILENAME

    with Image.open(src) as im:
        base = im.convert("RGB")
    W, H = base.size
    scale = max(W, H) / 1000.0

    note: List[str] = []
    body_font, has_cjk = _find_font(max(11, int(13 * max(0.6, scale))))
    small_font, _ = _find_font(max(10, int(11 * max(0.6, scale))))
    if not has_cjk:
        note.append("未找到中文字体，图上文字已退化为英文/数字标签")

    img = base.copy()
    draw = ImageDraw.Draw(img, "RGBA")

    flags = judgment.get("flags") or []
    allergen_flags = judgment.get("allergen_flags") or []
    # 每个区域被多少个 flag 引用 → 决定角标
    hits_by_region: Dict[str, List[str]] = {}
    for f in flags + allergen_flags:
        hits_by_region.setdefault(f.get("region") or "nut", []).append(f.get("level") or "warn")

    # ---------------------------------------------------------------- 顶部结论条
    # 先画横幅再画框：否则横幅会把顶部区域的标签盖住
    verdict = judgment.get("verdict") or {}
    level = verdict.get("level") or "warn"
    banner_rgb = _LEVEL_RGB.get(level, _LEVEL_RGB["warn"])

    bar_h = max(34, int(46 * max(0.7, scale)))
    draw.rectangle([0, 0, W, bar_h], fill=(14, 17, 22, 232))
    # 结论等级用色条 + 文字符号表示，不用 emoji（很多字体没有彩色字形）
    sw = max(6, int(bar_h * 0.42))
    draw.rectangle([10, (bar_h - sw) // 2, 10 + sw, (bar_h + sw) // 2],
                   fill=banner_rgb + (255,))
    _text(draw, (10 + sw // 2, bar_h * 0.5), _LEVEL_GLYPH.get(level, "!"),
          body_font, (10, 12, 14), anchor="mm")
    title = f"{judgment.get('product', '')}  →  {verdict.get('title', '')}"
    if not has_cjk:
        title = f"ingredient-radar: {judgment.get('goal_label', '')} -> {verdict.get('title', '')}"
    _text(draw, (10 + sw + 12, bar_h * 0.5), title, body_font, (255, 255, 255), anchor="lm")
    draw.rectangle([0, bar_h - 3, W, bar_h], fill=banner_rgb + (255,))

    # ---------------------------------------------------------------- 画框
    for rb in _wrap_boxes(img, grounding):
        key = rb["region"]
        box = rb["box"]
        x1 = int(round(box[0] / 1000.0 * W))
        y1 = int(round(box[1] / 1000.0 * H))
        x2 = int(round(box[2] / 1000.0 * W))
        y2 = int(round(box[3] / 1000.0 * H))
        color = _hex_rgb(REGION_COLORS.get(key, "#2dd4bf"))
        is_hit = key in hits_by_region
        is_hl = bool(highlight_regions) and key in (highlight_regions or [])
        width = max(3, int(3 * max(1.0, scale)))
        if is_hl:
            width = max(5, int(5 * max(1.0, scale)))

        # 半透明底色，让框在浅色标签上也看得见
        draw.rectangle([x1, y1, x2, y2], outline=color + (255,), width=width)
        if is_hl:
            draw.rectangle([x1 - 4, y1 - 4, x2 + 4, y2 + 4], outline=color + (110,), width=2)

        spec = REGION_BY_KEY.get(key, {})
        label = spec.get("box_label") or rb["phrase"]
        if not has_cjk:
            label = f"{key} {rb['score']:.2f}"
        else:
            label = f"{label} · {rb['score']:.2f}"

        pad = max(4, int(4 * scale))
        ls = max(10, int(11 * max(0.7, scale)))
        lf, _ = _find_font(ls)
        tw = draw.textlength(label, font=lf)
        bw, bh = int(tw + pad * 2), int(ls * 1.75)
        # 标签条优先画在框内顶边：框外经常被上一个区域的标签或画面内容占满，
        # 硬画到框外会压住配料表的最后一行
        inside = y2 - y1 > bh + 6
        top = y1 + 2 if inside else max(0, y1 - bh)
        draw.rectangle([x1, top, x1 + bw, top + bh], fill=color + (235,))
        _text(draw, (x1 + pad, top + bh * 0.16), label, lf, (4, 30, 26))
        if is_hit:
            # 命中 flag 的区域加角标小方块（不用 ⚑，多数中文字体里没有这个字形）
            m = max(7, int(9 * max(0.7, scale)))
            mark = _LEVEL_RGB[_worst_level(hits_by_region.get(key))]
            draw.rectangle([x2 - m - 2, y1 + 2, x2 - 2, y1 + m + 2], fill=mark + (255,))

    # ---------------------------------------------------------------- 底部结论摘要
    summary = [f for f in flags + allergen_flags]
    if summary:
        lines = [f"{f['title']}" for f in summary][:6]
        fh = max(13, int(15 * max(0.6, scale)))
        ff, _ = _find_font(fh)
        line_h = fh * 1.42
        note_line = (judgment.get("human_review_text") or "需人工复核原包装") \
            if judgment.get("uncertain") else ""
        n_lines = len(lines) + (1 if note_line else 0)
        box_h = int(line_h * n_lines + fh * 0.9)
        # 底部摘要不上移压住原图内容：优先保证原图可读，宁可少显示几行
        y0 = max(bar_h + 4, H - box_h)
        draw.rectangle([0, y0, W, H], fill=(14, 17, 22, 226))
        for i, f in enumerate(summary[:6]):
            f_level = f.get("level") or "warn"
            y = y0 + fh * 0.5 + i * line_h
            # 左侧色块代替 emoji 图标，任何字体下都不会缺字形
            sw = max(7, int(fh * 0.85))
            draw.rectangle([12, y + fh * 0.12, 12 + sw, y + fh * 0.12 + sw],
                           fill=_LEVEL_RGB.get(f_level, _LEVEL_RGB["warn"]) + (255,))
            _text(draw, (12 + sw // 2, y + fh * 0.12 + sw // 2),
                  _LEVEL_GLYPH.get(f_level, "!"), ff, (10, 12, 14), anchor="mm")
            _text(draw, (12 + sw + 10, y), f["title"], ff, (226, 237, 243))
        # 复核提示独占最后一行，绝不压在 flag 上面（早期版本就这样叠成一团）
        if note_line:
            _text(draw, (12, y0 + fh * 0.5 + len(lines) * line_h), note_line,
                  ff, (255, 200, 120))

    out_dir.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=90, optimize=True)

    return {
        "path": str(dest.resolve()),
        "width": W,
        "height": H,
        "boxes_drawn": len(_wrap_boxes(img, grounding)),
        "notes": note,
    }
