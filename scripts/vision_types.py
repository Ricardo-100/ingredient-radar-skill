# -*- coding: utf-8 -*-
"""vision_types · 视觉产物数据结构与坐标工具

2026-09-25 起 skill 移除了所有 HTTP / 外部推理端点代码（删掉 `backends/` 与
`llm_client.py`），只保留一种来源：**Agent 自己看图产出 JSON**（见 `agent_mode.py`）。

原先这些结构定义在 `backends/base.py` 里，与「可插拔视觉后端」的契约放在一起。
后端契约已经不需要了，但**产物结构还要**——`agent_mode` 要构造它们，
`agent_mode.py` 要构造它们，`render.py` 要用坐标回映射。所以搬到这里，
只留数据与纯函数，不带任何网络或模型调用。

零第三方依赖（Pillow 只在真正要开图时才 import）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import regions as R


# ---------------------------------------------------------------- 数据结构
@dataclass
class RegionBox:
    key: str
    phrase: str
    box: List[int]          # [x1,y1,x2,y2]，0–1000 归一化
    score: float
    found: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region": self.key,
            "phrase": self.phrase,
            "box": list(self.box),
            "score": round(float(self.score), 4),
            "found": bool(self.found),
        }


@dataclass
class GroundingResult:
    regions: List[RegionBox]
    is_food_label: bool
    caption: str
    raw: Dict[str, Any] = field(default_factory=dict)
    backend: str = "agent"          # 移除外部后端后恒为 agent

    def region(self, key: str) -> Optional[RegionBox]:
        for r in self.regions:
            if r.key == key:
                return r
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "is_food_label": self.is_food_label,
            "caption": self.caption,
            "regions": [r.to_dict() for r in self.regions],
        }


@dataclass
class ReferResult:
    key: str
    data: Dict[str, Any]
    double_check: Dict[str, Any] = field(default_factory=dict)
    backend: str = "agent"

    @property
    def status(self) -> str:
        return str((self.double_check or {}).get("status") or "agree")

    @property
    def corrections(self) -> List[Dict[str, Any]]:
        return list((self.double_check or {}).get("corrections") or [])

    @property
    def unreadable(self) -> List[str]:
        return list((self.double_check or {}).get("unreadable_fields") or [])


# ---------------------------------------------------------------- 坐标工具
def clamp1000(v) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(1000, n))


def normalize_box(box, lineno: str = "") -> List[int]:
    """把框规整成 [x1,y1,x2,y2] 且 x1<=x2、y1<=y2、落在 0–1000。"""
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return [0, 0, 0, 0]
    x1, y1, x2, y2 = (clamp1000(v) for v in box[:4])
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return [x1, y1, x2, y2]


def box_to_pixels(box: List[int], width: int, height: int) -> List[int]:
    """0–1000 归一化坐标 → 原图像素坐标。必须能回映射，否则结论无法点回原图核对。"""
    x1, y1, x2, y2 = normalize_box(box)
    return [
        int(round(x1 / 1000.0 * width)),
        int(round(y1 / 1000.0 * height)),
        int(round(x2 / 1000.0 * width)),
        int(round(y2 / 1000.0 * height)),
    ]


def box_area_ratio(box: List[int]) -> float:
    x1, y1, x2, y2 = normalize_box(box)
    return ((x2 - x1) * (y2 - y1)) / 1_000_000.0


# ---------------------------------------------------------------- 裁剪
def crop_region(image_path, box: List[int], pad_ratio: float = 0.04, out_dir=None):
    """按 0–1000 框裁出区域子图（带少量外扩）。

    外扩是为了把被框线切掉的半行字带进来；超出画面自然截断。
    目前只有 Agent 模式，而 Agent 就在上下文里看整张图，暂不需要裁剪；
    留着是给将来真要「逐区单独看图」的实现用（那时再配对应的 Agent 调用）。
    """
    from PIL import Image  # 延迟导入：只读元数据时不强依赖 Pillow

    src = _Path(image_path)
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        x1, y1, x2, y2 = box_to_pixels(box, w, h)
        pad_x = max(4, int((x2 - x1) * pad_ratio))
        pad_y = max(4, int((y2 - y1) * pad_ratio))
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)
    return _crop_impl(src, (x1, y1, x2, y2), out_dir)


def _Path(p):
    from pathlib import Path

    return Path(p)


def _crop_impl(src, rect, out_dir=None):
    """真正落盘的那一步单独拆开，便于测试。"""
    from PIL import Image  # noqa: F811

    with Image.open(src) as im:
        crop = im.convert("RGB").crop(rect)
    if out_dir is None:
        from . import config

        out_dir = config.ensure_out_dir() / "crops"
    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"crop_{rect[0]}_{rect[1]}_{rect[2]}_{rect[3]}.jpg"
    crop.save(dest, quality=92)
    return dest


# ---------------------------------------------------------------- 产物容器
class VisionResult:
    """第①②步的完整产物。"""

    def __init__(
        self,
        grounding: GroundingResult,
        refers: Dict[str, ReferResult],
        traces: List[Dict[str, Any]],
        rejected: bool = False,
        reject_reason: str = "",
    ):
        self.grounding = grounding
        self.refers = refers
        self.traces = traces
        self.rejected = rejected
        self.reject_reason = reject_reason

    # ---------------------------------------------------------------- 便捷读取
    def get(self, key: str) -> Dict[str, Any]:
        return dict((self.refers.get(key).data if self.refers.get(key) else {}) or {})

    def flagged(self, key: str) -> Optional[ReferResult]:
        return self.refers.get(key)

    @property
    def double_check_failed(self) -> List[str]:
        return [k for k, r in self.refers.items() if r.status != "agree"]

    @property
    def unreadable_fields(self) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for key, r in self.refers.items():
            for f in r.unreadable:
                out.append({"region": key, "field": f})
        return out

    def evidence(self, width: int, height: int) -> List[Dict[str, Any]]:
        """把定位+抽取结果压成契约里的 evidence 数组（像素坐标 + score + 原文值）。"""
        out: List[Dict[str, Any]] = []
        for key in R.REGION_KEYS:
            rb: Optional[ReferResult] = self.refers.get(key)
            g = self.grounding.region(key)
            if not rb or not g or not g.found:
                continue
            data = rb.data
            proof = _pick_proof(key, data)
            out.append(
                {
                    "region": key,
                    "phrase": g.phrase,
                    "box": box_to_pixels(g.box, width, height),
                    "box_norm_0_1000": list(g.box),
                    "score": round(float(g.score), 4),
                    "double_check": rb.status,
                    "text": proof,
                }
            )
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grounding": self.grounding.to_dict(),
            "referring": {
                k: {"data": r.data, "double_check": r.double_check}
                for k, r in self.refers.items()
            },
            "traces": self.traces,
            "rejected": self.rejected,
            "reject_reason": self.reject_reason,
        }


def _pick_proof(key: str, data: Dict[str, Any]) -> str:
    """给 evidence 挑一句最能代表该区域抽到了什么的原文摘要。"""
    if not data:
        return ""
    if key == "name":
        bits = [str(data.get("product_name") or "")]
        if data.get("net_content_value"):
            bits.append(f"净含量 {data['net_content_value']}{data.get('net_content_unit') or ''}")
        return " · ".join(b for b in bits if b)
    if key == "ing":
        ing = data.get("ingredients") or []
        return "、".join(str(x) for x in ing[:8]) + ("…" if len(ing) > 8 else "")
    if key == "all":
        return str(data.get("statement") or "")
    if key == "nut":
        parts = []
        if data.get("basis"):
            parts.append(str(data["basis"]))
        pairs = [
            ("kcal", "kcal"), ("protein", "蛋白"), ("fat", "脂肪"),
            ("trans_fat", "反式脂肪"), ("carbs", "碳水"), ("sugar", "糖"), ("sodium", "钠"),
        ]
        parts += [f"{label} {data[k]}" for k, label in pairs if data.get(k) is not None]
        return " · ".join(parts)
    return ""
