# -*- coding: utf-8 -*-
"""
serving · 每 100 g → 每份双口径折算

Demo 原版只存「每 100 g」数据，所有结论按「一份 = 60 g」折算。真实链路里净含量不再是人工
常量，而是从**品名/规格区**抽取出来的（附录 B 的要求：PRODUCT 常量必须退役）。

设计原则：
  - 折算只做一次乘法，所有派生量都在这里算完，judge 层不再碰数字；
  - 任何一个关键数字缺失或被判定不可辨，就如实标记 ``missing``，
    **绝不补默认值、绝不按「同类产品常见值」估算**（对应负向用例：不臆测数值）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config

# 营养成分表 → 本项目统一键
# energy_kj 是国产品牌的标注单位（GB 28050 要求以千焦标示），进来后统一折算成 kcal
NUT_KEYS = ["kcal", "protein", "fat", "trans_fat", "carbs", "sugar", "fiber", "sodium"]

# GB 28050 规定的能量换算口径
KJ_PER_KCAL = 4.184

# 每个指标的展示精度（与静态 Demo 的换算口径一致：能量/钠取整，其余保留 1 位小数）
METRIC_PRECISION = {
    "kcal": 0,
    "protein": 1,
    "fat": 1,
    "trans_fat": 1,
    "carbs": 1,
    "sugar": 1,
    "fiber": 1,
    "sodium": 0,
}


def _is_zero(v) -> bool:
    """严格判断「0」。0 是有效值，绝不能和 None 混为一谈。

    早期版本大量使用 ``if not x`` 判空，于是一张写着「能量 0 千焦、碳水 0 克」的
    无糖可乐标签会被判成「能量缺失」「糖占碳水比不可算」，报出来的结论全是错的。
    """
    return isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == 0.0


def _num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace(",", "").strip()
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    # 「60」就还你 60，不要变成 60.0 —— 契约里 serving_g: 60 比 60.0 干净
    if f.is_integer() and "." not in s and "e" not in s.lower():
        return int(f)
    return f


# ---------------------------------------------------------------- 单位换算
# 质量类：包装上可能出现的写法
_MASS_TO_G = {
    "g": 1.0, "gram": 1.0, "grams": 1.0, "克": 1.0, "公克": 1.0,
    "kg": 1000.0, "千克": 1000.0, "公斤": 1000.0, "公斤装": 1000.0,
    "mg": 0.001, "毫克": 0.001,
    "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495, "盎司": 28.3495,
    "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592, "磅": 453.592,
}
# 容量类：折算成毫升，再按 1 ml ≈ 1 g 近似成质量（密度差异未校正，必须在 notes 声明）
_VOL_TO_ML = {
    "ml": 1.0, "milliliter": 1.0, "millilitre": 1.0, "毫升": 1.0,
    "l": 1000.0, "liter": 1000.0, "litre": 1000.0, "升": 1000.0,
    "floz": 29.5735, "fl.oz": 29.5735, "fl.oz.": 29.5735,
    "fluidounce": 29.5735, "fluidounces": 29.5735, "液量盎司": 29.5735,
}


def _to_grams(value: float, unit: str):
    """(数值, 单位) → (克, 归一化单位, 备注)。认不出单位时按克处理并如实说明。"""
    u = str(unit or "").replace(" ", "").replace("．", ".").lower().rstrip(".")
    if u in _MASS_TO_G:
        return value * _MASS_TO_G[u], "g", ""
    if u in _VOL_TO_ML:
        ml = value * _VOL_TO_ML[u]
        return ml, "ml", "净含量按容量标注，折算时按 1 ml ≈ 1 g 近似处理，密度差异未校正"
    # 认不出单位：不猜，按克算并说清
    return value, "g", f"净含量单位「{unit}」不在已知换算表内，已按克处理"


def _clean_servings(v: Optional[float]):
    """份数显示用：6.0 → 6，6.1 保留小数。"""
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 1)


def parse_net_content(name_data: Dict[str, Any]) -> Dict[str, Any]:
    """从品名/规格区解析**整包**净含量与份数。

    返回 {"serving_g": 整包克数, "pack_g": 整包克数, "unit": "g", "servings": int,
          "raw": str, "note": str, ...}

    口径（2026-09-24 起）：**默认按整包算**。包装标「每包 6.1 份、每份 28 g」时，
    用户问的是「这一袋我吃下去是多少」，不是「标签建议的那一小份是多少」。
    标签建议份仍然记录在 ``label_serving_g`` / ``label_servings`` 里并写进 notes，
    可查、可回溯，但不作为计算口径。用户手填一份多少由 ``serving_override`` 覆盖。

    整包重量的来源按优先级：
      1. 包装直给总净含量（net_content_value × 单位换算）
      2. 每份大小 × 每包份数（进口标签常见：SERVING SIZE 28g × 6.1 = 170.8 g）
    两条都拿不到才返回 None，让上层标 uncertain——不猜。
    """
    raw_val = _num(name_data.get("net_content_value"))
    unit = str(name_data.get("net_content_unit") or "").strip()
    # 「每包份数」**可以是小数**：进口标签常写 SERVINGS PER PACKAGE: 6.1。
    # 早先这里 int() 截断，28 g × 6.1 会算成 168 g 而不是 170.8 g——
    # 一袋薯片少算 2.8 g 事小，把「小数份数」这个合法输入直接丢人事大。
    label_servings = _num(name_data.get("servings_per_pack"))
    label_servings = float(label_servings) if label_servings and label_servings > 0 else 1.0
    # 进口标签的「每份大小」（SERVING SIZE: 28g / SERVINGS PER PACKAGE: 6.1）
    serving_size_val = _num(name_data.get("serving_size_value"))
    serving_size_unit = str(name_data.get("serving_size_unit") or "").strip()

    notes: List[str] = []
    pack_g = None
    source = None

    if raw_val is not None:
        pack_g, unit_norm, unit_note = _to_grams(raw_val, unit)
        if unit_note:
            notes.append(unit_note)
        source = "label_net_content"
        raw = f"{name_data.get('net_content_value')}{name_data.get('net_content_unit') or ''}"
    elif serving_size_val is not None and label_servings > 0:
        # 从每份 × 份数推整包：进口标签没印总净含量时的唯一合法来源
        per_serving_g, _, unit_note = _to_grams(serving_size_val, serving_size_unit)
        pack_g = _round(per_serving_g * label_servings, 3)
        unit_norm = "g"
        if unit_note:
            notes.append(unit_note)
        source = "derived_from_serving_size"
        raw = f"{serving_size_val}{serving_size_unit} × {label_servings} 份"
        notes.append(
            f"整包重量由「每份 {_round(per_serving_g,3)} g × {label_servings} 份」推得，"
            "包装未直给总净含量"
        )
    else:
        return {"serving_g": None, "unit": "g", "servings": 1, "raw": None,
                "note": "未识别到净含量，也无从每份×份数推算的依据", "notes": notes,
                "pack_g": None, "source": None}

    # 标签建议份：记录下来供查，但不作为计算口径（口径一律整包）
    label_serving_g = None
    if label_servings > 1 and source == "label_net_content":
        label_serving_g = _round(pack_g / label_servings, 3)
        notes.append(
            f"标签标注每包 {_clean_servings(label_servings)} 份、每份约 {label_serving_g} g；"
            f"本报告按整包 {_round(pack_g,3)} g 计（用户手填一份克数可覆盖）"
        )
    elif source == "derived_from_serving_size":
        label_serving_g = _round(pack_g / label_servings, 3) if label_servings else None

    return {
        # serving_g 恒等于整包克数——consumers 读它就等于「一次吃完这一包」
        "serving_g": _round(pack_g, 3),
        "pack_g": _round(pack_g, 3),
        "unit": unit_norm,
        "servings": 1,
        "label_servings": label_servings,
        "label_serving_g": label_serving_g,
        "raw": raw,
        "source": source,
        "note": "；".join(notes),
        "notes": notes,
    }


def _clean(v: Optional[float]):
    """参考值显示用：2000.0 → 2000，2007.6 保留小数。"""
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 1)


def _round(value: Optional[float], nd: int) -> Optional[float]:
    """半进位取整（ROUND_HALF_UP），并顺手把 10.0 归一成 10，契约里更好看。

    不用内置 round：它是银行家进位，round(4.85, 1) 会得到 4.8，
    与静态 Demo 的 r1()（4.9）不一致——同图同结果不能被舍入方式破坏。
    """
    if value is None:
        return None
    from decimal import Decimal, ROUND_HALF_UP

    q = Decimal(1).scaleb(-nd)
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    if nd == 0:
        return int(d)
    f = float(d)
    return int(f) if f == int(f) else f


def scale(value: Optional[float], serving_g: float, nd: int = 1) -> Optional[float]:
    if value is None:
        return None
    return _round(value * serving_g / 100.0, nd)


def resolve_energy(nut_data: Dict[str, Any]) -> Dict[str, Any]:
    """把能量统一成 kcal，并说清这个数是标签直给还是千焦换算来的。

    国产标签按 GB 28050 以千焦标示；直接把 kJ 当 kcal 会让热量虚高 4.18 倍。
    标签同时给了两个单位时，以直给的 kcal 为准（更贴标签原文）。
    """
    kcal = _num(nut_data.get("kcal"))
    kj = _num(nut_data.get("energy_kj"))
    if kcal is not None:
        return {"kcal": kcal, "energy_source": "label_kcal",
                "energy_kj_label": kj}
    if kj is not None:
        return {"kcal": _round(kj / KJ_PER_KCAL, METRIC_PRECISION["kcal"]),
                "energy_source": "converted_from_kj", "energy_kj_label": kj}
    return {"kcal": None, "energy_source": None, "energy_kj_label": None}


def derive(
    per100: Dict[str, Any],
    serving_g: Optional[float],
    daily_ref: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """产出双口径 + 全部派生量。任一关键值缺失时对应字段为 None 并记入 missing。

    ``daily_ref``：分母口径，形如 ``{"basis": "personal"|"population_nrv",
    "daily_kcal": 1850, "protein_nrv_g": 60, ...}``。
    填了个人资料就用「你每日所需」当分母，否则回落到 GB 28050 人口 NRV。
    """
    ref = daily_ref or {}
    daily_kcal = _num(ref.get("daily_kcal")) or config.NRV_KCAL
    protein_ref = _num(ref.get("protein_nrv_g")) or config.NRV_PROTEIN_G
    fat_ref = _num(ref.get("fat_nrv_g")) or config.NRV_FAT_G
    carbs_ref = _num(ref.get("carbs_nrv_g")) or config.NRV_CARBS_G
    sodium_ref = _num(ref.get("sodium_nrv_mg")) or config.NRV_SODIUM_MG
    is_personal = ref.get("basis") == "personal"
    missing: List[str] = []
    base: Dict[str, Optional[float]] = {}
    for k in NUT_KEYS:
        v = _num(per100.get(k))
        base[k] = v
        if v is None:
            missing.append(k)

    energy = resolve_energy(per100)
    base["kcal"] = energy["kcal"]
    if energy["kcal"] is None:
        missing = [m for m in missing if m != "kcal"] + ["kcal"]
    else:
        missing = [m for m in missing if m != "kcal"]

    out: Dict[str, Any] = {
        "per_100g": {k: base[k] for k in NUT_KEYS},
        "serving_g": serving_g,
        "missing": sorted(set(missing)),
        "notes": [],
    }
    if energy["energy_source"] == "converted_from_kj":
        out["notes"].append(
            f"能量由标签的 {energy['energy_kj_label']} 千焦按 GB 28050 口径"
            f"（1 kcal = {KJ_PER_KCAL} kJ）换算为 {base['kcal']} kcal"
        )
    elif energy["energy_source"] == "label_kcal" and energy["energy_kj_label"] is not None:
        out["notes"].append("能量采用标签直给的千卡数值（标签同时标了千焦）")

    has_serving = serving_g is not None and serving_g > 0
    if has_serving:
        factor = serving_g / 100.0
        ps: Dict[str, Optional[float]] = {}
        for k in NUT_KEYS:
            ps[k] = None if base[k] is None else _round(base[k] * factor, METRIC_PRECISION.get(k, 1))
        out["per_serving"] = ps
    else:
        out["per_serving"] = {k: None for k in NUT_KEYS}

    # ---- 派生量（同时给两个口径都算得出来的才填）----
    # 注意 0 是合法值：0 糖 0 碳水时「糖占碳水」应记 0，不是 None。
    sugar, carbs = base["sugar"], base["carbs"]
    if sugar is not None and carbs is not None:
        out["sugar_share_of_carbs_pct"] = (
            0 if carbs == 0 else int(round(sugar / carbs * 100.0))
        )
    else:
        out["sugar_share_of_carbs_pct"] = None

    sugar_srv = out["per_serving"]["sugar"]
    out["sugar_cubes"] = (
        _round(sugar_srv / config.SUGAR_CUBE_G, 1) if sugar_srv is not None else None
    )

    # 蛋白质密度：g 蛋白 / 100 kcal（附录 A2，把「一般」变成可核验数字）
    # 0 kcal 的饮品：蛋白也是 0，密度就记 0；只有「有热量却算不出」才给 None
    if base["kcal"] is None:
        out["protein_per_100kcal"] = None
    elif base["kcal"] == 0:
        out["protein_per_100kcal"] = 0.0 if _is_zero(base["protein"]) else None
    else:
        out["protein_per_100kcal"] = (
            _round(base["protein"] / base["kcal"] * 100.0, 1)
            if base["protein"] is not None else None
        )

    # 各指标「占每日参考值的百分之几」。钠 / 蛋白 / 脂肪 / 碳水用人口 NRV，
    # 能量分母看 daily_ref：填了个人资料就是「你每日所需」，否则是人口 NRV。
    # 「钠 90 mg」听着不多，换成「占每日推荐量 4.5%」才有意义。
    if base["sodium"] is not None:
        out["sodium_nrv_pct"] = _round(base["sodium"] / sodium_ref * 100.0, 1)
        out["sodium_nrv_serving_pct"] = (
            _round(out["per_serving"]["sodium"] / sodium_ref * 100.0, 1)
            if out["per_serving"]["sodium"] is not None else None
        )
    else:
        out["sodium_nrv_pct"] = None
        out["sodium_nrv_serving_pct"] = None

    def _pcts(key: str, denom: float) -> None:
        """同一个指标的每 100 g / 每份两个占比，缺值就是 None，不补。"""
        if base[key] is None:
            out[f"{key}_nrv_pct"] = None
            out[f"{key}_nrv_serving_pct"] = None
            return
        out[f"{key}_nrv_pct"] = _round(base[key] / denom * 100.0, 1)
        out[f"{key}_nrv_serving_pct"] = (
            _round(out["per_serving"][key] / denom * 100.0, 1)
            if out["per_serving"][key] is not None else None
        )

    _pcts("kcal", daily_kcal)
    _pcts("protein", protein_ref)
    _pcts("fat", fat_ref)
    _pcts("carbs", carbs_ref)

    out["daily_reference"] = {
        "basis": "personal" if is_personal else "population_nrv",
        "daily_kcal": _clean(daily_kcal),
        "sodium_nrv_mg": _clean(sodium_ref),
        "protein_nrv_g": _clean(protein_ref),
        "fat_nrv_g": _clean(fat_ref),
        "carbs_nrv_g": _clean(carbs_ref),
        # 个人口径的推算过程也带上（BMR、活动系数、是否按目标调过），
        # 这些都是**结果**，不含年龄/性别/体重/身高原值
        "activity_factor": ref.get("activity_factor"),
        "activity_label": ref.get("activity_label"),
        "bmr_kcal": ref.get("bmr_kcal"),
        "goal_adjusted": bool(ref.get("goal_adjusted")),
        # 开了 --goal-adjust 时乘数是几：光有 goal_adjusted=true 复算不出这个分母
        "goal_adjust_factor": ref.get("goal_adjust_factor"),
    }
    if is_personal:
        # 口径写进 notes：拿到契约的人要能复现每一个百分比，
        # 光有 daily_reference 猜不出「分母为什么不是 2007.6」。
        # 只写口径与推算结果，不写年龄 / 性别 / 体重 / 身高原值（隐私约定，SKILL.md 6.4）。
        out["notes"].append(
            f"每日能量分母按你填写的个人资料推算（Mifflin-St Jeor："
            f"BMR {ref.get('bmr_kcal')} kcal × 活动系数 "
            f"{ref.get('activity_factor')} {ref.get('activity_label')}）："
            f"约 {config._round0(daily_kcal)} kcal / 天"
            + (f"，已再按所选目标乘以 {ref.get('goal_adjust_factor')}"
               f"（维持热量 → 目标热量，叠加乘数的估算值，非医学建议）"
               if ref.get("goal_adjusted") else "（维持当前体重所需）")
        )
        out["notes"].append(
            "蛋白 / 脂肪 / 碳水 / 钠的参考值仍用 GB 28050 人口 NRV，"
            "未按个人资料调整：个人化的「你该吃多少」属于饮食处方，不在本 Skill 边界内"
        )

    # 净碳水：只有表上给了膳食纤维才能算（附录 A4：不给就是不可知，不臆测）
    if base["carbs"] is not None and base["fiber"] is not None:
        out["net_carbs_per_100g"] = _round(base["carbs"] - base["fiber"], 1)
        out["net_carbs_per_serving"] = (
            _round(out["per_serving"]["carbs"] - out["per_serving"]["fiber"], 1)
            if out["per_serving"]["carbs"] is not None
            and out["per_serving"]["fiber"] is not None else None
        )
    else:
        out["net_carbs_per_100g"] = None
        out["net_carbs_per_serving"] = None

    # 反式脂肪标注口径（GB 28050：≤0.3 g/100 g 即可标「0」）
    if base["trans_fat"] is not None:
        out["trans_fat_labeled_zero"] = base["trans_fat"] <= config.GB_TRANS_ZERO_LIMIT
    else:
        out["trans_fat_labeled_zero"] = None

    return out


def from_regions(
    name_data: Dict[str, Any],
    nut_data: Dict[str, Any],
    serving_override: Optional[Dict[str, Any]] = None,
    daily_ref: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """汇总净含量与营养表。

    ``serving_override``：用户手填的「一次吃多少克」，形如 ``{"serving_g": 85}``。
    留空 = 整包（默认口径）。用户说「这袋我掰一半」就填 85，比让模型猜强。
    ``daily_ref``：占比口径，见 :func:`derive`。
    """
    net = parse_net_content(name_data or {})
    serving_g = net.get("serving_g")
    notes: List[str] = list(net.get("notes") or [])
    if net.get("note"):
        notes.append(net["note"])

    ov = serving_override or {}
    ov_g = _num(ov.get("serving_g"))
    if ov_g is not None and ov_g > 0:
        serving_g = _round(ov_g, 3)
        net["serving_g"] = serving_g
        net["pack_g"] = _round(ov_g, 3)
        net["servings"] = 1
        net["raw"] = f"{_round(ov_g,3)} g（用户手填）"
        net["override"] = True
        if net.get("source"):
            notes.append(
                f"一份克数由用户手填（{_round(ov_g,3)} g），"
                f"覆盖了包装口径（{net.get('raw_before_override') or '整包'}）"
            )
        else:
            notes.append(f"一份克数由用户手填（{_round(ov_g,3)} g），非图片识别结果")
    else:
        net["override"] = False
        if net.get("source"):
            notes.append(f"一份口径按整包计（{_round(serving_g,3)} g，来源：{net['source']}）")

    out = derive(nut_data or {}, serving_g, daily_ref)
    out["net_content"] = net
    for n in notes:
        if n and n not in out["notes"]:
            out["notes"].append(n)
    return out
