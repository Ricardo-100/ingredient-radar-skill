# -*- coding: utf-8 -*-
"""
profile · 个人每日能量需求（Mifflin-St Jeor × 活动系数）

为什么要有这个模块：占比必须有个分母。用人口 NRV（8400 kJ ≈ 2007.6 kcal）当分母，
对一个个子高、训练量大的人和久坐的人给的是同一个分母，占比就失去了指导意义。
所以填了个人资料时，分母换成「你自己维持当前体重一天所需」。

公式（用户指定口径，Mifflin-St Jeor）：

    男 BMR = 10 × 体重kg + 6.25 × 身高cm − 5 × 年龄 + 5
    女 BMR = 10 × 体重kg + 6.25 × 身高cm − 5 × 年龄 − 161
    每日所需 = BMR × 活动系数（久坐 1.3 / 一般健身 1.55 / 高强度 1.8）

边界（与 SKILL.md 的禁止行为一致）：
  - 四个字段**全部由用户手填**，本模块不推断、不从图片里「看」、不留默认值；
  - 任何一项缺失或越界 → 返回 None，口径回落到人口 NRV，并在文案里说明用的是哪个分母；
  - 只做维持热量。按目标增减（减脂 ×0.85 / 增肌 ×1.1）默认关闭，
    要开必须显式传 ``goal_adjust``，且会在 notes 里如实写明这是叠加了口味的乘数，
    不是医学建议。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import config

# 活动水平 → 系数。只用用户给的三档，不自行扩充。
ACTIVITY_FACTORS = {
    "sedentary": 1.3,    # 久坐 / 普通上班族
    "active": 1.55,      # 一般健身人群
    "athlete": 1.8,      # 高强度运动 / 专项运动员
}

ACTIVITY_LABELS = {
    "sedentary": "久坐 / 普通上班族",
    "active": "一般健身人群",
    "athlete": "高强度运动 / 专项运动员",
}

# 取值范围：超出就当无效输入，宁愿回落也不猜
LIMITS = {
    "age": (10, 100),
    "weight_kg": (20.0, 300.0),
    "height_cm": (100.0, 250.0),
}


def _in_range(value, key) -> bool:
    lo, hi = LIMITS[key]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return lo <= v <= hi


def _num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def bmr(sex: str, weight_kg: float, height_cm: float, age: float) -> Optional[float]:
    """Mifflin-St Jeor 基础代谢率（kcal / 天）。性别只接受 male / female。"""
    if sex not in ("male", "female"):
        return None
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    return base + (5.0 if sex == "male" else -161.0)


def build(
    profile: Optional[Dict[str, Any]] = None,
    goal: Optional[str] = None,
    goal_adjust: bool = False,
) -> Optional[Dict[str, Any]]:
    """把用户手填的个人资料折算成「每日所需能量」。

    返回 None 表示**没有可用的个人资料**，调用方应回落到人口 NRV。
    返回的字典刻意只带结果与口径，不带年龄 / 性别 / 体重 / 身高的原值——
    这四个字段是要落盘的敏感信息，契约里只留推算结果（见 SKILL.md 隐私约定）。
    """
    p = profile or {}
    sex = str(p.get("sex") or "").strip().lower()
    age = _num(p.get("age"))
    weight = _num(p.get("weight_kg"))
    height = _num(p.get("height_cm"))
    activity = str(p.get("activity") or "").strip().lower()

    if not sex or age is None or weight is None or height is None or not activity:
        return None
    if sex not in ("male", "female") or activity not in ACTIVITY_FACTORS:
        return None
    if not (_in_range(age, "age") and _in_range(weight, "weight_kg")
            and _in_range(height, "height_cm")):
        return None

    b = bmr(sex, weight, height, age)
    if b is None or b <= 0:
        return None
    factor = ACTIVITY_FACTORS[activity]
    daily = b * factor

    adjusted = False
    adj_factor = 1.0
    if goal_adjust and goal in (config.GOAL_ADJUST or {}):
        adj_factor = float(config.GOAL_ADJUST[goal])
        if adj_factor != 1.0:
            daily *= adj_factor
            adjusted = True

    out: Dict[str, Any] = {
        "basis": "personal",
        "bmr_kcal": config._round1(b),
        "activity_factor": factor,
        "activity_label": ACTIVITY_LABELS[activity],
        "goal_adjusted": adjusted,
        "goal_adjust_factor": adj_factor if adjusted else None,
        "daily_kcal": config._round0(daily),
        # 三大营养素的参考值仍用人口 NRV：个人化的「蛋白 / 脂肪 / 碳水该吃多少」
        # 属于饮食处方，超出本 Skill「只做机械比对」的边界
        "protein_nrv_g": config.NRV_PROTEIN_G,
        "fat_nrv_g": config.NRV_FAT_G,
        "carbs_nrv_g": config.NRV_CARBS_G,
        "sodium_nrv_mg": config.NRV_SODIUM_MG,
        "energy_nrv_kcal": config.NRV_KCAL,
    }
    return out


def population_reference() -> Dict[str, Any]:
    """没填个人资料时的分母：GB 28050 人口 NRV。"""
    return {
        "basis": "population_nrv",
        "activity_factor": None,
        "activity_label": None,
        "goal_adjusted": False,
        "goal_adjust_factor": None,
        "daily_kcal": config.NRV_KCAL,
        "protein_nrv_g": config.NRV_PROTEIN_G,
        "fat_nrv_g": config.NRV_FAT_G,
        "carbs_nrv_g": config.NRV_CARBS_G,
        "sodium_nrv_mg": config.NRV_SODIUM_MG,
        "energy_nrv_kcal": config.NRV_KCAL,
    }


def reference_label(ref: Dict[str, Any]) -> str:
    """给文案用的分母名字：填了资料就是「你每日所需」，没填就是「每日 NRV」。"""
    if (ref or {}).get("basis") == "personal":
        return "你每日所需"
    return "每日 NRV"
