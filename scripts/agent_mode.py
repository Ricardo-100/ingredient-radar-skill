# -*- coding: utf-8 -*-
"""agent_mode · 用 Agent 自己的多模态能力替代外部推理端点

**为什么要有这个模式**

原设计第①②步（定位四区 + 逐区抽取）走 HTTP 打到外部多模态端点。但本 Skill 本就运行在
Agent 里，而 Agent 本身就是个能看图的模型——再绕一圈去调另一个端点，是浪费：

    Agent 自己看图（Read 工具，图在上下文里）→ 按约定 schema 产出 JSON
      → 本模块把 JSON 变成 VisionResult
      → judge / serving / allergen_map / profile 全部本地计算
      → 照旧出 contract.json + result.jpg + MEDIA 行

**这一步把什么交给 Agent、把什么留在本地（重要，别混）**

交给 Agent 的只有两件**真需要眼睛和脑子**的事：
  1. 四区定位框（0–1000 归一化）与逐字段抽取；
  2. 「照 rules.yaml 读下来，该命中哪个结论分支」——即 verdict 的 id。

留在本地的是一切**算得出来**的东西：每份折算、方糖数、NRV%、蛋白密度、双口径、
Mifflin-St Jeor 个人分母、过敏 direct/cross 分级、不确定边界、全部文案。

理由很直接：让模型"照着规则算数"是可靠性最低的用法——`round(4.85, 1)` 在不同
模型/不同次运行里都能给出不同答案，而本项目最硬的指标就是「同图同参数必然同结果」。
算术交给 `serving.py`，模型只做选择。

**对可复现性的影响（必须如实说明）**

Agent 模式下 `verdict` 来自 Agent 的选择，**不保证两次运行一致**。
契约里会写 `judgment_source: "agent"`，让拿到契约的人不会误以为这是确定性结果。
同时本模块会用 `judge.goal_verdict()` 本地再算一份规则引擎的结论，
若与 Agent 选的分支不一致，契约写 `verdict_divergence: true` 并在
`agent_vs_rules` 里给出两边——**分歧是记录，不是掩盖**。
这也是个免费的质量信号：跑一批图，看分歧率就知道这个 Agent 读规则读得准不准。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import allergen_map as AM
from . import config
from . import judge as J
from . import profile as PR
from . import regions as R
from . import serving as S
from .vision_types import GroundingResult, RegionBox, ReferResult

SCHEMA = "ingredient-radar.agent/1"

# 这些字段名在 REFER_SPECS 里是 number|null，agent 里写成 "12 克" 这类字符串一律算错
_NUMBER_FIELDS = {
    "name": ["net_content_value", "servings_per_pack", "serving_size_value"],
    "nut": ["basis_value", "energy_kj", "kcal", "protein", "fat", "trans_fat",
            "carbs", "sugar", "fiber", "sodium"],
}
_ARRAY_FIELDS = {
    "ing": ["ingredients", "claim_words"],
    "all": ["allergens", "cross_contact"],
}
_STRING_FIELDS = {
    "name": ["product_name", "flavor", "net_content_unit",
             "serving_size_unit"],
    "ing": [],
    "all": ["statement"],
    "nut": ["basis", "basis_unit"],
}


class AgentPayloadError(ValueError):
    """Agent 产出的 JSON 不合契约。消息要能让人一眼看出该改哪一行。"""


# ---------------------------------------------------------------- 模板
def template() -> Dict[str, Any]:
    """给一份空白模板，Agent 照着填即可。

    `--dump-agent-template` 用它。里面带上**当前 rules.yaml 里合法的 verdict id**
    和每个区域的字段表——Agent 不需要凭记忆猜 schema。
    """
    rules = J.load_rules()
    verdicts = {}
    for goal in config.GOALS:
        spec = (rules.get("verdicts") or {}).get(goal) or {}
        branches = [
            {"id": t.get("id"), "title": t.get("title")}
            for t in (spec.get("thresholds") or [])
        ]
        verdicts[goal] = branches

    region_fields = {}
    for key, spec in R.REFER_SPECS.items():
        region_fields[key] = {
            "phrase": spec["title"],
            "fields": [
                {"name": n, "desc": d, "type": t} for n, d, t in spec["fields"]
            ],
        }

    out: Dict[str, Any] = {
        "_schema": SCHEMA,
        "_howto": (
            "1) 用 Read 看这张图；2) 填 is_food_label / caption；"
            "3) 给四个区各填 box（0–1000 归一化，[x1,y1,x2,y2]）与 score；"
            "4) 按 _region_fields 逐字段填 data，看不清就填 null，别猜；"
            "5) 读 rules.yaml 的 verdicts.<goal>.thresholds，给每个目标选一个 verdict_id；"
            "6) 存成 JSON，交给 --agent-json。"
        ),
        "_valid_verdict_ids": verdicts,
        "_region_fields": region_fields,
        "judged_by": "",
        "is_food_label": True,
        "caption": "",
        "regions": {
            "name": {"box": None, "score": 0.0, "data": {},
                     "unreadable_fields": []},
            "ing": {"box": None, "score": 0.0, "data": {},
                    "unreadable_fields": []},
            "all": {"box": None, "score": 0.0, "data": {},
                    "unreadable_fields": []},
            "nut": {"box": None, "score": 0.0, "data": {},
                    "unreadable_fields": []},
        },
        "judgment": {
            g: {"verdict_id": None, "notes": [], "uncertain_reasons": []}
            for g in config.GOALS
        },
    }
    # 去掉模板里的说明键前，先把字段表转成「可直接照着填」的空壳
    for key in R.REGION_KEYS:
        out["regions"][key]["data"] = {
            f["name"]: ([] if f["type"].startswith("array") else None)
            for f in region_fields[key]["fields"]
        }
    return out


# ---------------------------------------------------------------- 载入与校验
def load_payload(path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise AgentPayloadError(f"agent JSON 不存在：{p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AgentPayloadError(
            f"agent JSON 不是合法 JSON：{e}\n"
            f"（第 {e.lineno} 行第 {e.colno} 列。可用 "
            f"`--dump-agent-template` 重新拿一份模板）"
        )
    if not isinstance(raw, dict):
        raise AgentPayloadError("agent JSON 顶层必须是 object")
    schema = raw.pop("_schema", SCHEMA)
    if schema != SCHEMA:
        raise AgentPayloadError(
            f"agent JSON schema 不匹配：文件写的是 {schema!r}，"
            f"本版本要 {SCHEMA!r}。用 `--dump-agent-template` 取新模板"
        )
    return raw


def validate(payload: Dict[str, Any]) -> List[str]:
    """返回 warning 列表（不阻断）。结构性错误直接抛 AgentPayloadError。"""
    warn: List[str] = []

    if not isinstance(payload.get("is_food_label"), bool):
        raise AgentPayloadError("is_food_label 必须是 true/false")

    regions = payload.get("regions")
    if not isinstance(regions, dict):
        raise AgentPayloadError("regions 必须是 object（四个区各一项）")

    rules = J.load_rules()
    judgment = payload.get("judgment") or {}
    if not isinstance(judgment, dict):
        raise AgentPayloadError("judgment 必须是 object（每个目标一项）")

    for key in R.REGION_KEYS:
        item = regions.get(key)
        if item is None:
            continue
        if not isinstance(item, dict):
            raise AgentPayloadError(f"regions.{key} 必须是 object")
        box = item.get("box")
        if box is not None:
            if not (isinstance(box, list) and len(box) == 4):
                raise AgentPayloadError(
                    f"regions.{key}.box 必须是 [x1,y1,x2,y2] 四个数，收到 {box!r}"
                )
            for v in box:
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise AgentPayloadError(
                        f"regions.{key}.box 必须是数字，收到 {v!r}"
                    )
            if min(box) < 0 or max(box) > 1000:
                warn.append(f"regions.{key}.box 超出 0–1000，"
                            f"将被夹紧（原值 {box}）")
        data = item.get("data") or {}
        if not isinstance(data, dict):
            raise AgentPayloadError(f"regions.{key}.data 必须是 object")
        for f in _NUMBER_FIELDS.get(key, []):
            v = data.get(f)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise AgentPayloadError(
                    f"regions.{key}.data.{f} 要数字或 null，收到 {v!r}"
                    f"（单位写进 {f.rstrip('_value') + '_unit'}，别混进数值）"
                )
        for f in _ARRAY_FIELDS.get(key, []):
            v = data.get(f)
            if v is None:
                continue
            if not isinstance(v, list):
                raise AgentPayloadError(f"regions.{key}.data.{f} 要数组，收到 {v!r}")
        for f in _STRING_FIELDS.get(key, []):
            v = data.get(f)
            if v is not None and not isinstance(v, str):
                raise AgentPayloadError(f"regions.{key}.data.{f} 要字符串或 null，"
                                        f"收到 {v!r}")
        # 图上有这一区却没给框：evidence 与 result.jpg 会少了它，必须告知
        if item.get("data") and box is None:
            warn.append(f"regions.{key} 有 data 但没给 box，"
                        f"该区不会进 evidence，也不会画在 result.jpg 上")
        # unreadable_fields 是「显式声明看不清」，别和「图上没这一行」混为一谈
        urf = item.get("unreadable_fields")
        if urf is not None:
            if not isinstance(urf, list):
                raise AgentPayloadError(
                    f"regions.{key}.unreadable_fields 要数组，收到 {urf!r}"
                )
            known = _all_field_names(key)
            for f in urf:
                if str(f) not in known:
                    warn.append(f"regions.{key}.unreadable_fields 里的 {f!r} "
                                f"不是该区的字段（合法值：{known}）")
            nulls = {f for f, v in (item.get("data") or {}).items() if v is None}
            for f in urf:
                if str(f) not in nulls:
                    warn.append(
                        f"regions.{key}.unreadable_fields 声明 {f!r} 不可辨，"
                        f"但 data.{f} 有值——两处矛盾，以 unreadable_fields 为准")

    for goal in config.GOALS:
        j = judgment.get(goal)
        if j is None:
            warn.append(f"judgment.{goal} 缺失，该目标的结论将由规则引擎本地给出")
            continue
        if not isinstance(j, dict):
            raise AgentPayloadError(f"judgment.{goal} 必须是 object")
        vid = j.get("verdict_id")
        if vid is None:
            continue
        spec = (rules.get("verdicts") or {}).get(goal) or {}
        ids = [t.get("id") for t in (spec.get("thresholds") or [])]
        if vid not in ids:
            raise AgentPayloadError(
                f"judgment.{goal}.verdict_id = {vid!r} 不在 rules.yaml 的 "
                f"verdicts.{goal}.thresholds 里（合法值：{ids}）"
            )

    if payload.get("is_food_label") is False and not payload.get("caption"):
        warn.append("is_food_label 为 false 但没给 caption，"
                    "拒判原因只能说「不是食品包装标签」")

    return warn


# ---------------------------------------------------------------- 转成 VisionResult
def build_vision_result(payload: Dict[str, Any]) -> Any:
    """把 Agent JSON 变成 vision_types.VisionResult，下游一行不用改。"""
    from .vision_types import VisionResult

    regions_in = payload.get("regions") or {}
    boxes: List[RegionBox] = []
    refers: Dict[str, ReferResult] = {}
    traces: List[Dict[str, Any]] = []

    for spec in R.REGIONS:
        key = spec["key"]
        item = regions_in.get(key) or {}
        data = dict(item.get("data") or {})
        box_raw = item.get("box")
        has_box = box_raw is not None
        box = R_box(box_raw) if has_box else [0, 0, 0, 0]
        found = bool(has_box and data)
        try:
            score = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        boxes.append(RegionBox(
            key=key, phrase=spec["phrase"], box=box, score=score, found=found,
        ))
        if found:
            # double_check.status 写成 "agent"，契约的 evidence 里就会如实显示
            # 「这一格没经过第二遍复核」——不伪装成 agree。
            # unreadable_fields **只认 Agent 显式声明的**，绝不从「字段是 null」反推：
            # 营养成分表没列膳食纤维、能量标千卡而非千焦，填 null 是正确答案，
            # 把它当成「不可辨」会凭空造出人工复核（第一版就犯了这个错）。
            dc = {
                "status": "agent",
                "mode": "agent",
                "notes": "由 Agent 直接读图产出，未走独立的 double_check 通道",
                "unreadable_fields": [
                    str(f) for f in (item.get("unreadable_fields") or [])
                    if str(f) in _all_field_names(key)
                ],
            }
            refers[key] = ReferResult(
                key=key, data=data, double_check=dc, backend="agent",
            )
        traces.append({
            "step": "agent_extract",
            "region": key,
            "backend": "agent",
            "has_box": has_box,
            "fields": len(data),
        })

    grounding = GroundingResult(
        regions=boxes,
        is_food_label=bool(payload.get("is_food_label")),
        caption=str(payload.get("caption") or ""),
        backend="agent",
    )
    rejected = not grounding.is_food_label
    return VisionResult(
        grounding=grounding,
        refers=refers,
        traces=traces,
        rejected=rejected,
        reject_reason=(
            "该图不是食品包装标签（不适用于本 Skill）" if rejected else ""
        ),
    )


def _all_field_names(key: str) -> List[str]:
    return [n for n, _, _ in R.REFER_SPECS.get(key, {}).get("fields", [])]


def goal_label_of(goal: str) -> str:
    return (config.GOALS.get(goal) or {}).get("label", goal)


def R_box(box) -> List[int]:
    """0–1000 归一化框的夹紧与排序（复用 base.normalize_box 的语义）。"""
    from .vision_types import normalize_box

    return normalize_box(box)


# ---------------------------------------------------------------- 判定
def _verdict_by_id(rules: Dict[str, Any], goal: str, verdict_id: Optional[str],
                   vars_: Dict[str, Any], nut: Dict[str, Any]) -> Dict[str, Any]:
    """按 Agent 选的分支 id 从 rules.yaml 取文案。

    找不到 id 时**不猜**：返回 None，由调用方回落到规则引擎的本地结论。
    """
    spec = (rules.get("verdicts") or {}).get(goal) or {}
    for th in (spec.get("thresholds") or []):
        if th.get("id") == verdict_id:
            return {
                "goal": goal,
                "level": th.get("level") or spec.get("level") or "warn",
                "emoji": spec.get("emoji") or "•",
                "title": J._render(th.get("title", ""), vars_),
                "detail": J._render(th.get("detail", ""), vars_),
                "branch": th.get("id"),
            }
    return None


def judge_agent(
    vision,
    goal: str,
    user_allergens: List[str],
    agent_judgment: Optional[Dict[str, Any]] = None,
    serving_override: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
    goal_adjust: bool = False,
) -> Dict[str, Any]:
    """Agent 模式的判定。算术/过敏/不确定边界全部本地，结论分支听 Agent 的。"""
    rules = J.load_rules()

    name_data = vision.get("name")
    ing_data = vision.get("ing")
    all_data = vision.get("all")
    nut_data = vision.get("nut")

    personal = PR.build(profile, goal=goal, goal_adjust=goal_adjust)
    daily_ref = personal or PR.population_reference()

    nut = S.from_regions(name_data, nut_data, serving_override=serving_override,
                         daily_ref=daily_ref)
    if nut_data.get("basis"):
        nut["per_100g_basis"] = str(nut_data["basis"])
        nut["per_100g_basis_unit"] = str(nut_data.get("basis_unit") or "g")

    present = AM.derive_present(
        statement=all_data.get("statement") or "",
        direct_words=all_data.get("allergens") or [],
        cross_words=all_data.get("cross_contact") or [],
    )
    hits = AM.cross_check(user_allergens, present)

    vars_ = J.build_vars(nut, name_data, ing_data)
    flags = J.base_flags(rules, nut, vars_)
    unc = J.evaluate_uncertainty(rules, vision, nut, name_data, nut_data)
    product = (str(name_data.get("product_name") or "").strip()
               or vision.grounding.caption or "未识别品名")

    # ---- 结论分支：Agent 选 → 规则引擎算 → 分歧如实记账 ----
    agent_j = (agent_judgment or {}).get(goal) or {}
    agent_verdict_id = agent_j.get("verdict_id")
    rules_verdict = J.goal_verdict(rules, goal, vars_, nut)
    agent_verdict = (_verdict_by_id(rules, goal, agent_verdict_id, vars_, nut)
                     if agent_verdict_id else None)

    if agent_verdict is not None:
        verdict = dict(agent_verdict)
        verdict["source"] = "agent"
    else:
        verdict = dict(rules_verdict)
        verdict["source"] = "rules"
        if agent_verdict_id:
            # 走到这里说明 id 不合法——validate() 本该拦住，兜底也不猜
            verdict["fallback_reason"] = f"agent 给的 verdict_id {agent_verdict_id!r} 不合法"

    divergence = bool(
        agent_verdict is not None
        and rules_verdict.get("branch") != agent_verdict.get("branch")
    )
    if divergence:
        # 把「为什么不一致」写清：只给两个分支名，看图的人根本不知道该信谁。
        # 最常见的原因是 **--serving-g / 个人资料改变了口径**——Agent 填 JSON 时
        # 还不知道命令行会覆盖成多少克，按整包选的分支到 30 g 上就不成立了。
        spec_g = (rules.get("verdicts") or {}).get(goal) or {}
        metric = spec_g.get("metric") or ""
        ps = nut.get("per_serving") or {}
        metric_val = ps.get(metric) if isinstance(ps, dict) else None
        why = [f"Agent 选 {agent_verdict.get('branch')}，"
               f"规则引擎按 {goal_label_of(goal)}口径算 {rules_verdict.get('branch')}"]
        if nut.get("serving_g") is not None:
            why.append(f"当前口径 {nut['serving_g']} g/份")
        if metric and metric_val is not None:
            why.append(f"该目标主指标 {metric} = {metric_val} g/份")
        if nut.get("override"):
            why.append("（口径由 --serving-g 手填指定，Agent 填 JSON 时看不到这个值）")
        unc["reasons"] = list(unc["reasons"]) + [
            "结论分支分歧：" + "；".join(why)
        ]
        unc["uncertain"] = True
        unc["human_review_required"] = True
        if not unc.get("human_review_text"):
            unc["human_review_text"] = rules.get("uncertain", {}).get(
                "human_review_text", "")

    # Agent 自己声明的原因接在后面（它看过图，可能发现规则覆盖不到的情况）
    extra_reasons = [str(x) for x in (agent_j.get("uncertain_reasons") or []) if x]
    if extra_reasons:
        unc["reasons"] = list(unc["reasons"]) + [
            f"Agent 声明：{x}" for x in extra_reasons
        ]
        if extra_reasons:
            unc["uncertain"] = True
            unc["human_review_required"] = True

    notes = list(nut.get("notes") or [])
    notes.append("判定模式：agent（第①②步由 Agent 读图产出，未调用外部推理端点）")
    for n in (agent_j.get("notes") or []):
        if str(n) not in notes:
            notes.append(str(n))
    if divergence:
        notes.append(f"结论分支分歧：Agent 选 {agent_verdict.get('branch')}，"
                     f"规则引擎算 {rules_verdict.get('branch')}"
                     + (f"；当前口径 {nut.get('serving_g')} g/份"
                        if nut.get("serving_g") is not None else ""))

    judgment: Dict[str, Any] = {
        "product": product,
        "goal": goal,
        "goal_label": (config.GOALS.get(goal) or {}).get("label", goal),
        "serving_g": nut.get("serving_g"),
        "net_content": nut.get("net_content"),
        "per_100g": nut.get("per_100g"),
        "per_serving": nut.get("per_serving"),
        "derived": {
            "sugar_cubes": nut.get("sugar_cubes"),
            "sugar_share_of_carbs_pct": nut.get("sugar_share_of_carbs_pct"),
            "protein_per_100kcal": nut.get("protein_per_100kcal"),
            "sodium_nrv_pct": nut.get("sodium_nrv_pct"),
            "sodium_nrv_serving_pct": nut.get("sodium_nrv_serving_pct"),
            "kcal_nrv_pct": nut.get("kcal_nrv_pct"),
            "kcal_nrv_serving_pct": nut.get("kcal_nrv_serving_pct"),
            "protein_nrv_pct": nut.get("protein_nrv_pct"),
            "protein_nrv_serving_pct": nut.get("protein_nrv_serving_pct"),
            "fat_nrv_pct": nut.get("fat_nrv_pct"),
            "fat_nrv_serving_pct": nut.get("fat_nrv_serving_pct"),
            "carbs_nrv_pct": nut.get("carbs_nrv_pct"),
            "carbs_nrv_serving_pct": nut.get("carbs_nrv_serving_pct"),
            "net_carbs_per_100g": nut.get("net_carbs_per_100g"),
            "daily_reference": nut.get("daily_reference"),
        },
        "ingredients": ing_data.get("ingredients") or [],
        "claim_words": ing_data.get("claim_words") or [],
        "sweeteners": vars_.get("sweeteners") or "",
        "allergen_statement": all_data.get("statement") or "",
        "allergens_present": present,
        "flags": flags,
        "allergen_hits": hits,
        "allergen_flags": J.allergen_flags(rules, hits),
        "verdict": verdict,
        "missing": nut.get("missing") or [],
        "notes": notes,
        "uncertain": unc["uncertain"],
        "uncertain_reasons": unc["reasons"],
        "human_review_required": unc["human_review_required"],
        "human_review_text": unc["human_review_text"],
        "_rules_version": rules.get("version"),
        # agent 模式专属：结论来源与对照
        "judgment_source": "agent" if agent_verdict is not None else "rules",
        "agent_verdict_id": agent_verdict_id,
        "rules_verdict_branch": rules_verdict.get("branch"),
        "rules_verdict_title": rules_verdict.get("title"),
        "verdict_divergence": divergence,
    }
    return judgment


# ---------------------------------------------------------------- 编排
def run_agent_mode(
    image_path,
    payload: Dict[str, Any],
    goal: str = "cut",
    allergens: Optional[List[str]] = None,
    *,
    goals: Optional[List[str]] = None,
    serving_override: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
    goal_adjust: bool = False,
    out_dir=None,
    keep_report: bool = True,
    verbose: bool = False,
    progress=None,
) -> Dict[str, Any]:
    """Agent 模式的完整编排：消费 JSON → 本地判定 → 契约 + result.jpg + MEDIA。"""
    import time

    from . import pipeline as P
    from . import render as RD

    def say(msg: str):
        if progress:
            progress(msg)
        elif verbose:
            print(msg, flush=True)

    t_all = time.time()
    img = Path(image_path)
    if not img.exists():
        raise FileNotFoundError(f"图片不存在：{img}")

    allergies = list(allergens or [])
    want_goals = [g for g in (goals or [goal]) if g in config.GOALS]
    if goal in config.GOALS and goal not in want_goals:
        want_goals.insert(0, goal)
    if not want_goals:
        raise ValueError(f"未知目标 {goal!r}，可选：{', '.join(config.GOALS)}")

    say("① Agent 读图：四区定位 + 逐字段抽取（来自 --agent-json，未调外部端点）")
    vision = build_vision_result(payload)

    if vision.rejected:
        say(f"⛔ 拒判：{vision.reject_reason}")
        return {
            "status": "rejected",
            "reason": vision.reject_reason,
            "image": str(img.resolve()),
            "backend": "agent",
            "grounding": vision.grounding.to_dict(),
            "final_reply": (
                f"无法分析：{vision.reject_reason}。\n"
                "本 Skill 只处理食品包装标签上的配料与营养成分，"
                "对非食品图像、定位不到配料表/营养成分表的图像一律拒判，"
                "不做任何成分推断。"
            ),
            "media": None,
        }

    n_found = sum(1 for r in vision.grounding.regions if r.found)
    say(f"  定位到 {n_found}/{len(R.REGIONS)} 个区域")

    ing_ok = vision.grounding.region("ing") and vision.grounding.region("ing").found
    nut_ok = vision.grounding.region("nut") and vision.grounding.region("nut").found
    if not ing_ok and not nut_ok:
        return {
            "status": "rejected",
            "reason": "未定位到配料表或营养成分表，无法判定",
            "image": str(img.resolve()),
            "backend": "agent",
            "grounding": vision.grounding.to_dict(),
            "final_reply": (
                "无法分析：未定位到配料表或营养成分表，无法判定。\n"
                "本 Skill 只处理食品包装标签上的配料与营养成分，"
                "定位不到就如实说明，不按同类产品常见值估算。"
            ),
            "media": None,
        }

    agent_judgment = payload.get("judgment") or {}
    say(f"③ 本地判定（算术/flags/过敏/不确定边界）× {len(want_goals)} 个目标；"
        f"结论分支由 Agent 指定")
    judgments: Dict[str, Any] = {}
    for g in want_goals:
        # 先按全部忌口算一遍，再裁剪成用户勾选的：这样切换勾选不必重跑判定
        j = judge_agent(vision, g, list(config.ALLERGEN_OPTIONS),
                        agent_judgment=agent_judgment,
                        serving_override=serving_override, profile=profile,
                        goal_adjust=goal_adjust)
        judgments[g] = J.filter_allergens(j, allergies)
    judgment = judgments[goal]

    say("④ 输出契约 + result.jpg …")
    out_base = Path(out_dir) if out_dir else config.ensure_out_dir()
    out_base.mkdir(parents=True, exist_ok=True)
    media_info = RD.annotate(
        img, grounding=vision.grounding, judgment=judgment,
        out_path=out_base / config.MEDIA_FILENAME,
    )
    model = str(payload.get("judged_by") or "agent（自带多模态能力）")
    contract = P.build_contract(
        judgment=judgment,
        vision_result=vision,
        media_path=Path(media_info["path"]),
        image_path=img,
        model=model,
        backend_name="agent",
        elapsed=time.time() - t_all,
    )
    # agent 模式的身份必须写进契约：不让人误以为这是确定性链路跑出来的
    contract["judgment_source"] = judgment.get("judgment_source", "rules")
    contract["agent_verdict_id"] = judgment.get("agent_verdict_id")
    contract["rules_verdict_branch"] = judgment.get("rules_verdict_branch")
    contract["verdict_divergence"] = bool(judgment.get("verdict_divergence"))
    if contract["verdict_divergence"]:
        contract["agent_vs_rules"] = {
            "agent_branch": judgment.get("agent_verdict_id"),
            "rules_branch": judgment.get("rules_verdict_branch"),
            "rules_title": judgment.get("rules_verdict_title"),
        }

    if keep_report:
        (out_base / config.REPORT_FILENAME).write_text(
            json.dumps({
                "contract": contract,
                "judgment": judgment,
                "judgments": judgments,
                "vision": vision.to_dict(),
                "agent_payload": payload,
                "config": config.snapshot(),
                "media": media_info,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_base / config.CONTRACT_FILENAME).write_text(
            json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")

    say(f"✅ 完成 · {contract['elapsed_seconds']}s · 判定模式 agent（未调用外部推理端点）")

    # 其余目标的契约也一起算好：界面切换目标时直接换，不重新计算
    contracts: Dict[str, Any] = {goal: contract}
    for g, j in judgments.items():
        if g == goal:
            continue
        contracts[g] = P.build_contract(
            judgment=j,
            vision_result=vision,
            media_path=Path(media_info["path"]),
            image_path=img,
            model=model,
            backend_name="agent",
            elapsed=contract["elapsed_seconds"],
        )
        # 与主契约一样标上 agent 身份
        contracts[g]["judgment_source"] = j.get("judgment_source", "rules")
        contracts[g]["agent_verdict_id"] = j.get("agent_verdict_id")
        contracts[g]["rules_verdict_branch"] = j.get("rules_verdict_branch")
        contracts[g]["verdict_divergence"] = bool(j.get("verdict_divergence"))
        if contracts[g]["verdict_divergence"]:
            contracts[g]["agent_vs_rules"] = {
                "agent_branch": j.get("agent_verdict_id"),
                "rules_branch": j.get("rules_verdict_branch"),
                "rules_title": j.get("rules_verdict_title"),
            }

    return {
        "status": "ok",
        "image": str(img.resolve()),
        "backend": "agent",
        "model": contract["model"],
        "contract": contract,
        "judgment": judgment,
        "grounding": vision.grounding.to_dict(),
        "evidence": contract.get("evidence", []),
        "media": contract["media"],
        "final_reply": P.format_final_reply(contract, judgment),
        "judgments": judgments,
        "contracts": contracts,
    }
