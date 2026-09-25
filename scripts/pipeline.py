# -*- coding: utf-8 -*-
"""
pipeline · 输出契约与最终回复

    ③ 规则判定                   judge.judge()   ← rules.yaml（agent 模式在 agent_mode.py）
    ④ 输出契约                   本模块：contract.json + result.jpg + 最后一行 MEDIA

负向路径（重要）：输入不是食品包装标签、或定位不到配料/营养表时，**不产出 result.jpg、
不输出 MEDIA 行**，只给出拒判说明。理由见 SKILL.md「负向路径契约」——
「正确答案是不调用本 Skill / 不硬出结论」，这条比「最后一行必须是 MEDIA」优先级更高。

2026-09-25 起第①②步由 Agent 自己看图产出（`agent_mode.py`），本模块不再包含
任何后端编排 / HTTP 调用。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List
from . import config
from . import judge as J
from . import vision_types as V


# ---------------------------------------------------------------- 指纹 / 版本锁定
PIN_PREFIX = "p#"
# 这些目录装的是**产物和样例**，不是 skill 本身的内容。
# 早期版本没排除 evals/_runs：流水线每跑一次就改写那里的 report.json，
# 于是同一份代码连续跑两遍，skill_pin 会自己变，「同图同结果」被悄悄破坏。
# evals 的 repeat_identical 机检点把这题抓了出来，所以这条注释留着当教训。
UNHASHED_DIRS = {"output", "_runs", "__pycache__", "samples", ".git", ".venv", "venv"}
HASHED_SUFFIXES = {".py", ".md", ".yaml", ".json", ".sh", ".txt"}


def skill_fingerprint() -> str:
    """对自研 Skill 的内容做 SHA-256，前 8 位作为 skill_pin。

    与静态 Demo 里写死的 ``p#a6f3c21`` 不同，这个值是**算出来的**：
    内容一个字节不改 → pin 不变；内容被改过 → pin 立刻变。现场两遍跑同一张图，
    只要 pin 与 seed 都一致，结果就必然一致，这是可复现的真正依据。
    """
    h = hashlib.sha256()
    files = sorted(
        p
        for p in config.SKILL_DIR.rglob("*")
        if p.is_file()
        and not (UNHASHED_DIRS & set(p.parts))
        and p.suffix in HASHED_SUFFIXES
    )
    for p in files:
        h.update(p.relative_to(config.SKILL_DIR).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return PIN_PREFIX + h.hexdigest()[:8]


# ---------------------------------------------------------------- 契约
def build_contract(
    *,
    judgment: Dict[str, Any],
    vision_result: V.VisionResult,
    media_path: Path,
    image_path: Path,
    model: str,
    backend_name: str,
    elapsed: float,
) -> Dict[str, Any]:
    rules = J.load_rules()
    export = rules.get("export") or {}

    contract: Dict[str, Any] = {
        "contract_version": export.get("contract_version", "1.3"),
        "status": "ok",
        "product": judgment["product"],
        "goal": judgment["goal"],
        "goal_label": judgment["goal_label"],
        "serving_g": judgment["serving_g"],
        # serving 口径的来源必须落盘：整包 / ml 近似 / 每份×份数推算 / 用户手填覆盖。
        # 少了它，拿到契约的人无法回答「这 60 g 是怎么来的」——而复现要的正是这条链。
        "net_content": (judgment.get("net_content") or None),
        "per_100g": judgment["per_100g"],
        "per_serving": judgment["per_serving"],
        # 派生量：方糖数、糖占碳水比、蛋白密度、钠/蛋白/脂肪/碳水 NRV%（附录 A2 / A6）
        "derived": judgment["derived"],
        # 占比口径：只落推算结果（basis / 每日千卡 / 活动系数）与人口参考值，
        # **不落年龄、性别、体重、身高的原值**——那是要保护的敏感信息，
        # 而复现只需要分母本身（见 SKILL.md 隐私约定）。
        "daily_reference": (judgment.get("derived") or {}).get("daily_reference"),
        "flags": [f["title"] for f in judgment["flags"]],
        "allergen_hits": [f["title"] for f in judgment["allergen_flags"]],
        "verdict": judgment["verdict"]["title"],
        "verdict_level": judgment["verdict"].get("level"),
        "uncertain": judgment["uncertain"],
    }
    # 配料、话术、代糖也进契约：这些是「为什么这么判」的原文证据
    if judgment.get("ingredients"):
        contract["ingredients"] = judgment["ingredients"]
    if judgment.get("claim_words"):
        contract["claim_words"] = judgment["claim_words"]
    if judgment.get("sweeteners"):
        contract["sweeteners"] = judgment["sweeteners"]
    # notes 恒显式给出（没有要说明的口径时也是空数组）：
    # 下游写 `for n in contract["notes"]` 不必先判断键在不在
    contract["notes"] = list(judgment.get("notes") or [])

    # A9：免责与人工复核必须落在最终文本里，不能只存在于文档。
    # human_review_required 恒显式给出（干净图也是 false）：
    # 下游 Agent 不必去猜「字段缺失」是不是就等于「不用复核」。
    if export.get("include_disclaimer", True):
        contract["disclaimer"] = export.get("disclaimer") or config.DISCLAIMER
    contract["human_review_required"] = bool(judgment.get("human_review_required"))
    if judgment.get("human_review_required"):
        contract["human_review_reasons"] = judgment["uncertain_reasons"]
        contract["human_review_text"] = judgment["human_review_text"]

    # A8：证据坐标数组，任何人都能当场验 0–1000 → 像素 的回映射
    if export.get("include_evidence", True):
        from PIL import Image

        with Image.open(image_path) as im:
            W, H = im.size
        contract["evidence"] = vision_result.evidence(W, H)

    # 锁版本 · 可复现
    contract["skill_pin"] = skill_fingerprint()
    contract["seed"] = config.SEED
    contract["temperature"] = config.TEMPERATURE
    contract["backend"] = backend_name
    contract["model"] = model
    contract["rules_version"] = rules.get("version")
    contract["image"] = str(Path(image_path).resolve())
    contract["media"] = str(media_path.resolve())
    contract["elapsed_seconds"] = round(elapsed, 2)
    contract["generated_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    return contract


def format_final_reply(contract: Dict[str, Any], judgment: Dict[str, Any]) -> str:
    """给 OpenClaw / 终端看的最终回复：人话结论 + 契约 JSON + 最后一行 MEDIA。"""
    lines: List[str] = []
    v = judgment["verdict"]
    ps = judgment.get("per_serving") or {}
    d = judgment.get("derived") or {}
    ref = d.get("daily_reference") or {}
    ref_name = "你每日所需" if ref.get("basis") == "personal" else "每日 NRV"

    def _nrv(v) -> str:
        return f"（占{ref_name} {v}%）" if v is not None else ""

    lines.append(f"**成分雷达 · {judgment['product']}**")
    lines.append(f"{v['emoji']} {v['title']} —— {v['detail']}")
    if ref.get("basis") == "personal":
        lines.append(f"占比分母：{ref_name} ≈ {ref.get('daily_kcal')} kcal/天"
                     f"（Mifflin-St Jeor × 活动系数 {ref.get('activity_factor')}）")
    if ps.get("kcal") is not None:
        sod = ps.get("sodium")
        sod_txt = ""
        if sod is not None:
            nrv_s = d.get("sodium_nrv_serving_pct")
            sod_txt = (f" · 钠 {sod} mg"
                       + (f"（占每日推荐 {ref.get('sodium_nrv_mg') or 2000} mg 的 {nrv_s}%）"
                          if nrv_s is not None else ""))
        lines.append(
            f"每份（{judgment.get('serving_g')} g）：{ps.get('kcal')} kcal"
            f"{_nrv(d.get('kcal_nrv_serving_pct'))} · "
            f"蛋白 {ps.get('protein')} g{_nrv(d.get('protein_nrv_serving_pct'))} · "
            f"脂肪 {ps.get('fat')} g{_nrv(d.get('fat_nrv_serving_pct'))} · "
            f"碳水 {ps.get('carbs')} g{_nrv(d.get('carbs_nrv_serving_pct'))}"
            f"（糖 {ps.get('sugar')} g）"
            + sod_txt
        )
    if judgment.get("sweeteners"):
        lines.append(f"代糖：{judgment['sweeteners']}")
    if judgment["flags"]:
        lines.append("告警：" + "；".join(f["title"] for f in judgment["flags"]))
    if judgment["allergen_flags"]:
        lines.append("过敏命中：" + "；".join(f["title"] for f in judgment["allergen_flags"]))
    if judgment.get("human_review_required"):
        lines.append(f"⚠ {judgment['human_review_text']}")
    if contract.get("disclaimer"):
        lines.append(contract["disclaimer"])
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(contract, ensure_ascii=False, indent=2))
    lines.append("```")
    # 铁纪律：最终回复的最后一个非空行必须是纯文本 MEDIA:<绝对路径>
    lines.append(f"MEDIA:{Path(contract['media']).resolve()}")
    return "\n".join(lines)


