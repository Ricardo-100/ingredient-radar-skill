# -*- coding: utf-8 -*-
"""
judge · 第③步：自研 Skill 规则判定

这里是整个项目**唯一做判断的地方**，规则全部来自 rules.yaml，本文件不含硬编码阈值。
判定顺序与静态 Demo 完全一致：

    五个与目标无关的基础 flag
      → 目标匹配 verdict（增肌 / 减脂控糖 / 生酮，三态）
      → 过敏原交叉核验（direct / cross）
      → 不确定与人工复核边界

边界（写死，不靠提示词）：
  - 目标与过敏一律来自用户手动勾选，本模块不推断、不补默认；
  - 关键数字缺失或被 double_check 判为不可辨 → uncertain:true，宁可不判也不猜；
  - 干净配料不凑 flag：阈值没命中就不生成对应 flag。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config
from . import miniyaml
from . import serving as S
from . import allergen_map as AM
from . import profile as PR

# ---------------------------------------------------------------- 规则表加载
_RULES_CACHE: Optional[Dict[str, Any]] = None


def load_rules(path=None, refresh: bool = False) -> Dict[str, Any]:
    """加载规则表。优先用 PyYAML；没装就用内置的零依赖子集解析器，结果完全一致。"""
    global _RULES_CACHE
    if _RULES_CACHE is not None and not refresh and path is None:
        return _RULES_CACHE

    p = Path(path or config.RULES_PATH)
    if not p.exists():
        raise FileNotFoundError(f"规则表不存在：{p}")

    try:
        import yaml  # type: ignore

        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except ImportError:
        raw = miniyaml.loads(p.read_text(encoding="utf-8"))

    rules = miniyaml.normalize(raw)
    if not isinstance(rules, dict):
        raise ValueError(f"规则表顶层必须是 mapping：{p}")

    if path is None:
        _RULES_CACHE = rules
    return rules


# ---------------------------------------------------------------- 模板变量
# 配料表里属于「糖类来源」的特征词（GB 7718 递减排序，靠前即为强证据）
SUGAR_INGREDIENT_WORDS = [
    "白砂糖", "蔗糖", "糖", "糖浆", "葡萄糖", "果糖", "麦芽糖", "乳糖",
    "糊精", "麦芽糊精", "蜂蜜", "果汁", "浓缩果汁", "冰糖", "红糖", "黑糖",
]

PROTEIN_INGREDIENT_WORDS = [
    "蛋白粉", "乳清", "酪蛋白", "大豆蛋白", "分离乳清", "浓缩乳清", "奶粉",
    "脱脂乳粉", "全脂乳粉", "牛奶", "蛋白", "豌豆蛋白", "小麦蛋白",
]

# 高甜度甜味剂 / 糖醇。用户拿无糖饮料来问时，一句都不提代糖是失职——
# 代糖不升糖，但「部分人会起胰岛素反应」正是控糖与生酮人群真正的疑问。
SWEETENER_WORDS = [
    "阿斯巴甜", "安赛蜜", "安赛蜜钾", "三氯蔗糖", "蔗糖素", "甜菊糖苷", "甜叶菊",
    "罗汉果甜苷", "甜蜜素", "糖精", "糖精钠", "纽甜", "阿力甜", "索马甜",
    "赤藓糖醇", "赤癣糖醇", "木糖醇", "麦芽糖醇", "山梨糖醇", "异麦芽酮糖醇",
    "甘露糖醇", "乳糖醇", "塔格糖", "阿洛酮糖", "异麦芽酮糖",
]

# 含苯丙氨酸的代糖：苯丙酮尿症(PKU)患者必须避开，这是标签上「含苯丙氨酸」的由来
PKU_SWEETENERS = ["阿斯巴甜", "纽甜", "阿力甜"]

# 蛋白宣称词：只有包装真这么说了，「名不副实」才成立。
# 无糖可乐蛋白 0 g，但它从没宣称过蛋白，报「名不副实」是无的放矢。
PROTEIN_CLAIM_WORDS = [
    "高蛋白", "高蛋白质", "蛋白质", "蛋白", "乳清", "增肌", "健身", "运动",
    "蛋白棒", "补充蛋白质", "富含蛋白", "优质蛋白", "蛋白含量",
]


def _fmt(v, nd: int = 1) -> str:
    if v is None:
        return "?"
    if isinstance(v, float):
        return f"{v:.{nd}f}".rstrip("0").rstrip(".") if nd else str(v)
    return str(v)


def sugar_ingredients(ingredients: List[str], limit: int = 3) -> str:
    """从配料表前段挑出含糖来源（保持原顺序），用于「糖从哪来」的证据链。

    GB 7718 要求配料按加入量递减排序，所以只在前 10 位里找，靠前才是有效证据。
    """
    if not ingredients:
        return "（未识别到配料表）"
    head = list(ingredients)[:10]
    hits = [i for i in head if any(w in str(i) for w in SUGAR_INGREDIENT_WORDS)]
    picks = hits[:limit] if hits else [str(head[0])]
    return " + ".join(picks)


def protein_ingredients(ingredients: List[str], limit: int = 2) -> str:
    if not ingredients:
        return "（未识别到配料表）"
    hits = [i for i in ingredients if any(w in str(i) for w in PROTEIN_INGREDIENT_WORDS)]
    return " + ".join(str(x) for x in hits[:limit]) if hits else "（配料表中未见明确蛋白来源）"


def sweeteners(ingredients: List[str]) -> List[str]:
    """从配料表里挑出代糖，保持原始顺序、按出现次数去重。"""
    out: List[str] = []
    for item in ingredients or []:
        s = str(item)
        for w in SWEETENER_WORDS:
            if w in s and w not in out:
                out.append(w)
    return out


def pku_sweeteners(found: List[str]) -> List[str]:
    return [w for w in (found or []) if any(p in w for p in PKU_SWEETENERS)]


def has_protein_claim(name_data: Dict[str, Any], ing_data: Dict[str, Any]) -> bool:
    """包装是否真的宣称过蛋白。

    判定依据只有两处：品名/规格区的产品名，以及配料区抽取到的 claim_words。
    宁可漏判（不报「名不副实」）也不误判——误判等于平白骂一款好产品。
    """
    text = " ".join([
        str(name_data.get("product_name") or ""),
        str(name_data.get("flavor") or ""),
        " ".join(str(x) for x in (ing_data.get("claim_words") or [])),
    ])
    return any(w in text for w in PROTEIN_CLAIM_WORDS)


def build_vars(nut: Dict[str, Any], name_data: Dict[str, Any], ing_data: Dict[str, Any]) -> Dict[str, Any]:
    per = nut.get("per_serving") or {}
    p100 = nut.get("per_100g") or {}
    ingredients = [str(x) for x in (ing_data.get("ingredients") or [])]
    claim_words = [str(x) for x in (ing_data.get("claim_words") or [])]
    sweets = sweeteners(ingredients)
    pku = pku_sweeteners(sweets)
    # 占比分母：填了个人资料就是「你每日所需」，否则是人口 NRV。
    # 文案里必须写清用的哪个分母——同一个 12% 在两个口径下含义完全不同。
    dref = nut.get("daily_reference") or {}
    ref_name = "你每日所需" if dref.get("basis") == "personal" else "每日 NRV"

    vars_: Dict[str, Any] = {
        # 每份口径
        "value": 0,
        "kcal": per.get("kcal"), "protein": per.get("protein"), "fat": per.get("fat"),
        "carbs": per.get("carbs"), "sugar": per.get("sugar"),
        "sodium": per.get("sodium"), "trans_fat": per.get("trans_fat"),
        # 每 100 g 口径（规则表里可能按任一口径设阈值）
        "kcal_100g": p100.get("kcal"), "carbs_100g": p100.get("carbs"),
        "sugar_100g": p100.get("sugar"), "sodium_100g": p100.get("sodium"),
        "protein_100g": p100.get("protein"), "fat_100g": p100.get("fat"),
        # 派生
        "sugar_cubes": nut.get("sugar_cubes"),
        "sugar_share": nut.get("sugar_share_of_carbs_pct"),
        "protein_density": nut.get("protein_per_100kcal"),
        "sodium_nrv": nut.get("sodium_nrv_serving_pct"),
        "sodium_nrv_100g": nut.get("sodium_nrv_pct"),
        "kcal_nrv": nut.get("kcal_nrv_serving_pct"),
        "protein_nrv": nut.get("protein_nrv_serving_pct"),
        "fat_nrv": nut.get("fat_nrv_serving_pct"),
        "carbs_nrv": nut.get("carbs_nrv_serving_pct"),
        "net_carbs": nut.get("net_carbs_per_serving"),
        "net_carbs_100g": nut.get("net_carbs_per_100g"),
        "serving_g": nut.get("serving_g"),
        "basis": (nut.get("per_100g_basis") or name_data.get("_basis") or "每 100 g"),
        "basis_unit": (nut.get("per_100g_basis_unit") or "g"),
        # 分母口径：模板里写成「占{kcal_ref_name}（{kcal_ref_kcal} kcal）的 {kcal_nrv}%」
        "kcal_ref_name": ref_name,
        "kcal_ref_kcal": dref.get("daily_kcal"),
        "sodium_ref_mg": dref.get("sodium_nrv_mg"),
        "protein_ref_g": dref.get("protein_nrv_g"),
        "fat_ref_g": dref.get("fat_nrv_g"),
        "carbs_ref_g": dref.get("carbs_nrv_g"),
        "personal_profile": dref.get("basis") == "personal",
        # 文本证据
        "claim": "（包装话术未识别）" if not claim_words else "、".join(claim_words),
        "sugar_ingredients": sugar_ingredients(ingredients),
        "protein_ingredients": protein_ingredients(ingredients),
        # 代糖：无糖饮料的核心问题不是糖，是代糖
        "sweeteners": "、".join(sweets),
        "sweetener_count": len(sweets),
        "pku_count": len(pku),
        "sweetener_note": _sweetener_note(sweets, pku),
        "pku_warning": _pku_note(pku),
        "protein_claim": has_protein_claim(name_data, ing_data),
        "good_protein": 20,
        "calories_note": "",
    }
    ref = load_rules().get("reference") or {}
    vars_["good_protein"] = ref.get("good_protein_threshold_g", 20)
    return vars_


def _sweetener_note(sweets: List[str], pku: List[str]) -> str:
    """有代糖才拼这句话；没有就返回空串，模板里直接 ``{sweetener_note}`` 占位。

    苯丙酮尿症的警示单独放 ``pku_warning``，避免两处重复同一句话。
    """
    if not sweets:
        return ""
    return (f"配料含代糖（{'、'.join(sweets)}）：代糖不提供热量、不直接升糖，"
            "但部分人会对代糖产生胰岛素反应或肠道反应，个体差异大；"
            "控糖/生酮期建议少量尝试并观察自身反应。")


def _pku_note(pku: List[str]) -> str:
    if not pku:
        return ""
    return f"含苯丙氨酸类代糖：{'、'.join(pku)}；苯丙酮尿症(PKU)患者须严格避开。"


# ---------------------------------------------------------------- flag 生成
def _render(template: str, vars_: Dict[str, Any]) -> str:
    try:
        return str(template).format(**vars_)
    except (KeyError, IndexError, ValueError):
        # 模板引用了不存在的变量时，退回原样文本并在调用方记录，不让整条链崩
        return str(template)


def metric_value(metric: str, nut: Dict[str, Any], vars_: Dict[str, Any]) -> Optional[float]:
    """按名字取指标值。查找顺序：每份 → 每 100 g → 派生量（nut 顶层）→ 文本变量。

    规则表里写 ``metric: sodium_nrv_serving_pct`` 也能直接用，不用在 Python 里
    为每种指标加一个分支——加新口径时只改 rules.yaml。
    """
    if not metric:
        return None
    per = nut.get("per_serving") or {}
    p100 = nut.get("per_100g") or {}
    # nut 顶层放的是 derive() 出来的派生量（sugar_cubes / sodium_nrv_serving_pct / …）
    for src in (per, p100, nut, vars_):
        if metric in src and src[metric] is not None:
            v = src[metric]
            if isinstance(v, (list, tuple, dict)):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def _op_match(th: Dict[str, Any], value: float) -> bool:
    """支持 ``<metric>_at_least`` / ``_below`` / ``_at_most`` 三种比较。"""
    for key in ("metric_at_least", "metric_below", "metric_at_most"):
        if key in th and th[key] is not None:
            bound = float(th[key])
            if key == "metric_at_least":
                return value >= bound
            if key == "metric_below":
                return value < bound
            return value <= bound
    # 没有任何条件时视为恒真（用于 requires_claim 这类仅做门禁的分支）
    return True


# 比较后缀 → 内部标识。长后缀排前面，避免 ``_at_least`` 抢切 ``sodium_x_at_least``
_OPS = ("_at_least", "_below", "_at_most")


def _condition_metrics(th: Dict[str, Any], default_metric: str = "") -> List[tuple]:
    """把一个分支里的所有比较条件拆成 [(指标名, 比较键, 阈值)]。

    三种写法都支持：
        metric_at_least: 20                       # 指标取 spec 的 metric 字段
        carbs_at_most: 5                          # 指标名直接写在键里
        sodium_nrv_serving_pct_at_least: 25       # 派生量也能当条件
    """
    out: List[tuple] = []
    for k, v in (th or {}).items():
        if v is None:
            continue
        if k.startswith("metric_"):
            out.append((default_metric, k, v))
            continue
        for suffix in _OPS:
            if k.endswith(suffix) and len(k) > len(suffix):
                out.append((k[: -len(suffix)], "metric" + suffix, v))
                break
    return out


def _match_threshold(
    thresholds: List[Dict[str, Any]],
    value: Optional[float] = None,
    vars_: Dict[str, Any] = None,
    nut: Dict[str, Any] = None,
    default_metric: str = "",
) -> Optional[Dict[str, Any]]:
    """取第一条命中的分支。

    ``requires_claim``：该分支只有在包装真的这么宣称过时才允许命中。
    没有它，「蛋白质 0 g（名不副实）」会打到一款从没提过蛋白的无糖可乐头上。
    """
    for th in thresholds or []:
        conds = _condition_metrics(th, default_metric)
        if conds:
            ok = True
            for metric_name, key, bound in conds:
                v = metric_value(metric_name, nut or {}, vars_ or {})
                if v is None or not _op_match({key: bound}, v):
                    ok = False
                    break
            if not ok:
                continue
        if th.get("requires_claim") and not (vars_ or {}).get("protein_claim"):
            continue
        return th
    return None


def base_flags(rules: Dict[str, Any], nut: Dict[str, Any], vars_: Dict[str, Any],
               region_of: Dict[str, str] = None) -> List[Dict[str, Any]]:
    """基础 flag；指标缺失则该 flag 直接不生成（不猜数值）。

    ``metric`` 用来匹配阈值分支；``value_metric`` 用来渲染 ``{value}``。
    钠就是这么分的：按 NRV% 分档，标题里显示的仍是毫克数——
    「按比例分档、按原单位说话」比把两个口径搅在一起清楚。
    """
    out: List[Dict[str, Any]] = []
    for name, spec in (rules.get("base_flags") or {}).items():
        metric = spec.get("metric") or ""
        value = metric_value(spec.get("value_metric") or metric, nut, vars_)
        th = _match_threshold(spec.get("thresholds"), None, vars_, nut, default_metric=metric)
        if th is None:
            continue
        local = dict(vars_)
        local["value"] = _trim(value)
        out.append(
            {
                "id": name,
                "region": spec.get("region") or ((region_of or {}).get(metric) or "nut"),
                "icon": th.get("icon") or "•",
                "level": th.get("level") or "warn",
                "title": _render(th.get("title", name), local),
                "detail": _render(th.get("detail", ""), local),
                "src": spec.get("src", ""),
                "metric": metric,
                "value": _trim(value),
            }
        )
    return out


def _trim(v):
    """数值归一：280.0 → 280，19.4 保留小数。

    契约与 flag 标题里的数字必须和标签、和静态 Demo 一致：
    早期版本把指标统一转成 float，于是「反式脂肪 0 g」变成「0.0 g」，
    既难看，也让 evals 的 flags_min 逐字比对标不上。
    """
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else round(v, 1)
    return v


def goal_verdict(
    rules: Dict[str, Any],
    goal: str,
    vars_: Dict[str, Any],
    nut: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """目标三态结论。

    ``verdicts.<goal>`` 支持两种写法：
      - 只有 title/detail：一刀切结论（旧写法，保留兼容）；
      - 带 ``thresholds``：自上而下取第一条命中的分支。

    生酮必须有分支：碳水 0 g 是生酮最理想的状态，碳水 30 g 才会打断血酮。
    早期版本对生酮只有一句「碳水 {carbs} g，足以直接中断血酮」，
    于是无糖可乐被判成「生酮:避雷」——结论与生酮的机制正好相反。
    （历史文案里的单位随 v1.3 统一改成了「份」，这里引用时略去单位以免误读。）
    """
    spec = (rules.get("verdicts") or {}).get(goal)
    if not spec:
        raise ValueError(f"rules.yaml 未定义目标 {goal!r} 的 verdict")

    emoji = spec.get("emoji") or "•"
    thresholds = spec.get("thresholds") or []
    if thresholds:
        # 每个目标有自己的主指标：增肌看蛋白、减脂看糖、生酮看碳水。
        # 不配 metric 的话 ``metric_at_least: 15`` 不知道在比谁，整组分支都会失配。
        th = _match_threshold(thresholds, None, vars_, nut or {},
                              default_metric=spec.get("metric") or "")
        if th:
            return {
                "goal": goal,
                "level": th.get("level") or spec.get("level") or "warn",
                "emoji": emoji,
                "title": _render(th.get("title", ""), vars_),
                "detail": _render(th.get("detail", ""), vars_),
                "branch": th.get("id") or th.get("title", "")[:12],
            }

    return {
        "goal": goal,
        "level": spec.get("level") or "warn",
        "emoji": emoji,
        "title": _render(spec.get("title", ""), vars_),
        "detail": _render(spec.get("detail", ""), vars_),
        "branch": "default",
    }


def allergen_flags(rules: Dict[str, Any], hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    spec_all = rules.get("allergen") or {}
    for h in hits:
        spec = spec_all.get(h["kind"]) or spec_all.get("direct")
        out.append(
            {
                "id": f"allergen_{h['key']}",
                "region": "all",
                "icon": spec.get("icon") or "🚫",
                "level": spec.get("level") or "bad",
                "title": _render(spec.get("title", "命中 {allergen}"),
                                 {"allergen": h["allergen"], **h}),
                "detail": _render(spec.get("detail", ""), {"allergen": h["allergen"], **h}),
                "src": spec.get("src", "→ 回跳:致敏原提示行"),
                "allergen": h["allergen"],
                "kind": h["kind"],
                "label": h.get("label", ""),
            }
        )
    return out


# ---------------------------------------------------------------- 不确定边界
def evaluate_uncertainty(
    rules: Dict[str, Any],
    vision,
    nut: Dict[str, Any],
    name_data: Dict[str, Any],
    nut_data: Dict[str, Any],
) -> Dict[str, Any]:
    reasons: List[str] = []
    cond = (rules.get("uncertain") or {}).get("conditions") or []

    nut_region = vision.grounding.region("nut")
    if "nut_table_missing" in cond and not (nut_region and nut_region.found):
        reasons.append("未定位到营养成分表")
    if "nut_illegible" in cond and nut_data.get("legible") is False:
        reasons.append("营养成分表存在不可辨数字")
    if "missing_any_of_kcal_sugar_sodium_protein" in cond:
        missing = [k for k in ("kcal", "sugar", "sodium", "protein")
                   if (nut.get("per_100g") or {}).get(k) is None]
        if missing:
            reasons.append("关键指标缺失：" + "、".join(missing))
    if "net_content_missing" in cond and nut.get("serving_g") is None:
        reasons.append("未识别到净含量，无法折算每份口径")
    if "double_check_unreadable" in cond and vision.unreadable_fields:
        pairs = ["{region}.{field}".format(**f) for f in vision.unreadable_fields]
        reasons.append("double_check 判定不可辨：" + "、".join(pairs))

    cfg = rules.get("uncertain") or {}
    return {
        "uncertain": bool(reasons),
        "reasons": reasons,
        "human_review_required": bool(reasons),
        "human_review_text": cfg.get("human_review_text", "")
        if reasons else "",
    }


def filter_allergens(judgment: Dict[str, Any], selected) -> Dict[str, Any]:
    """把「全部忌口的命中结果」裁剪成用户当前勾选的那些。

    为什么要这样绕一步：视觉链路跑一次要 20 多秒，用户改一次勾选就重跑一次太蠢。
    所以判定时按全部忌口项算一遍，界面切换时只做本地裁剪。
    ``all_allergen_hits`` / ``all_allergen_flags`` 保留全量，供界面回显。
    """
    sel = {str(s) for s in (selected or [])}
    hits = [h for h in (judgment.get("allergen_hits") or []) if h.get("allergen") in sel]
    judgment["all_allergen_hits"] = list(judgment.get("allergen_hits") or [])
    judgment["all_allergen_flags"] = list(judgment.get("allergen_flags") or [])
    judgment["allergen_hits"] = hits
    judgment["allergen_flags"] = allergen_flags(load_rules(), hits)
    return judgment


# ---------------------------------------------------------------- 主入口
def judge(
    vision,
    goal: str,
    user_allergens: List[str],
    serving_override: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
    goal_adjust: bool = False,
) -> Dict[str, Any]:
    rules = load_rules()

    name_data = vision.get("name")
    ing_data = vision.get("ing")
    all_data = vision.get("all")
    nut_data = vision.get("nut")

    # 占比分母优先用个人资料；缺任何一项就回落到人口 NRV，绝不猜
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

    vars_ = build_vars(nut, name_data, ing_data)
    flags = base_flags(rules, nut, vars_)
    verdict = goal_verdict(rules, goal, vars_, nut)
    hits_flags = allergen_flags(rules, hits)
    unc = evaluate_uncertainty(rules, vision, nut, name_data, nut_data)

    product = str(name_data.get("product_name") or "").strip() or vision.grounding.caption or "未识别品名"

    return {
        "product": product,
        "goal": goal,
        "goal_label": (config.GOALS.get(goal) or {}).get("label", goal),
        "serving_g": nut.get("serving_g"),
        # serving 口径的来源（整包 / ml 近似 / 每份×份数推算 / 用户手填覆盖）。
        # 不落这一项，「这 60 g 怎么来的」就无从回答，复现链断在这里。
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
            # 占比口径：personal = 用户手填资料推算；population_nrv = GB 28050 人口参考值
            "daily_reference": nut.get("daily_reference"),
        },
        "ingredients": ing_data.get("ingredients") or [],
        "claim_words": ing_data.get("claim_words") or [],
        "sweeteners": vars_.get("sweeteners") or "",
        "allergen_statement": all_data.get("statement") or "",
        "allergens_present": present,
        "flags": flags,
        "allergen_hits": hits,
        "allergen_flags": hits_flags,
        "verdict": verdict,
        "missing": nut.get("missing") or [],
        "notes": nut.get("notes") or [],
        "uncertain": unc["uncertain"],
        "uncertain_reasons": unc["reasons"],
        "human_review_required": unc["human_review_required"],
        "human_review_text": unc["human_review_text"],
        "_rules_version": rules.get("version"),
    }
