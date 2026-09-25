# -*- coding: utf-8 -*-
"""
成分雷达 · Grounding 定位提示词与区域契约（中英术语对照）

本文件是四个待定位区域的唯一事实来源（single source of truth）：
  - ``REGIONS``      ：区域键 / 中文注解 / 英文术语 / 定位提示
  - ``REGION_HINTS`` ：给 grounding 模型的开放词汇提示
  - ``REFER_SPECS``  ：给 referring 模型的逐区抽取契约（字段级）

坐标约定：0–1000 归一化整数（与主流 VLM 的 grounding 输出口径一致）
  模型输出 0–1000 归一化整数坐标；渲染时回映射到原图像素：
      px = round(v / 1000 * W),  py = round(v / 1000 * H)
  回映射函数见 ``render.py``。好处是关系极简、可当场手算，且不引入二次缩放误差。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 区域定义
REGIONS = [
    {
        "key": "name",
        "phrase": "品名 / 规格",
        "official_term": "product name & net content",
        # hint 是**喂给模型的输入侧例子**，写的是包装上真实会出现的字样（支 / 袋 / 瓶 / 罐都有），
        # 与「输出给用户的单位」是两件事：v1.3 起输出统一为「份」，识别侧仍要认得原文怎么写。
        # 2026-09-24 补：进口标签的规格常写成 Serving Size / Servings Per Package，
        # 且不一定挨着品名；这一区要把它们一起框进来，否则整包重量无从推算。
        "hint": "食品包装上印的产品名称、口味、净含量 / 规格（如「净含量 60 g（1 支 / 袋）」）；"
                "进口标签的 Serving Size / Servings Per Package / 每份大小 也算这一区",
        "box_label": "① 品名 / 规格",
    },
    {
        "key": "ing",
        "phrase": "配料表",
        "official_term": "ingredient list",
        "hint": "配料表 / 配料 / 成分表，按加入量递减顺序排列的明细文字块",
        "box_label": "② 配料表 · 逐项",
    },
    {
        "key": "all",
        "phrase": "致敏原提示",
        "official_term": "allergen statement",
        "hint": "致敏原 / 过敏原 提示行，常见写法「含有…」「生产线亦加工…」",
        "box_label": "③ 致敏原行",
    },
    {
        "key": "nut",
        "phrase": "营养成分表",
        "official_term": "nutrition facts table",
        "hint": "营养成分表 / 营养标签，含能量、蛋白质、脂肪、碳水化合物、钠等数值的表格",
        "box_label": "④ 营养成分表",
    },
]

REGION_BY_KEY = {r["key"]: r for r in REGIONS}
REGION_KEYS = [r["key"] for r in REGIONS]

# 每个区域在图上的配色（与静态 Demo 的虚线框配色保持一致）
REGION_COLORS = {
    "name": "#2dd4bf",   # teal
    "ing": "#3fb950",    # green
    "all": "#f47067",    # rose
    "nut": "#58a6ff",    # blue
}

# ---------------------------------------------------------------- Grounding 提示
GROUNDING_SYSTEM = """你是一个包装标签区域定位器（region grounder）。
你的唯一任务：在给定的食品包装照片上，用开放词汇找出下面四个区域的边界框。
- 只输出 JSON，不要输出任何解释文字、markdown 代码块标记或前后缀。
- 坐标系为 0–1000 归一化整数：左上角 (0,0)，右下角 (1000,1000)。
  像素换算由调用方完成：px = round(v / 1000 * 图片宽)。
- 找不到某个区域时，该区域 ``found`` 置 false，``box`` 给 [0,0,0,0]，不要编造框。
- ``score`` 填 0.0–1.0 的自我置信度，宁低勿高；看不清就填 0.3 以下并把 found 置 false。
"""

GROUNDING_USER_TMPL = """请在下图中定位以下四个区域（开放词汇检索，可返回多个候选框）：

{region_block}

另外给出两项整图判断：
- ``is_food_label``：这张图是否确实是「食品 / 保健食品包装标签」的照片（有品名、配料或营养信息）。
  风景、人像、账单、截图、马路等一律 false。
- ``caption``：不超过 30 个字的整图描述。

严格按此结构输出（示例中坐标仅供示意，请用真实坐标）：
{output_example}
"""


def region_block() -> str:
    lines = []
    for i, r in enumerate(REGIONS, 1):
        lines.append(f'{i}. "{r["key"]}" —— {r["phrase"]}（{r["official_term"]}）：{r["hint"]}')
    return "\n".join(lines)


def output_example() -> str:
    parts = ", ".join(
        '{{"key":"%s","phrase":"%s","box":[x1,y1,x2,y2],"score":0.0,"found":true}}' % (r["key"], r["phrase"])
        for r in REGIONS
    )
    return '{"regions":[' + parts + '],"is_food_label":true,"caption":"……"}'


# ---------------------------------------------------------------- Referring 提示
REFER_SYSTEM = """你是包装标签结构化抽取器（referring-expression extractor）。
输入是一张**已裁剪到单一区域**的标签图片。你只抽取该区域内的信息，绝不跨区域臆测。
原则：
- 只输出 JSON；数字必须与图上一模一样，保留图上给的小数位，不许四舍五入、不许换算单位。
- **图上写 0 就填 0，不是缺失**：0 与 null 含义完全不同，null 只用于「图上真的没有这一行」。
- 图上没有的字段填 null，禁止填空字符串、0 或「未知」以外的猜测值。
- 文本字段请原样转录（含括号与分隔符），不要改写、不要补全、不要翻译。
- 配料表必须逐项拆成数组，顺序、括号、别名字符一律照抄，不要合并、不要总结。
"""

# 每个区域的抽取契约：字段 → (说明, 类型)
REFER_SPECS = {
    "name": {
        "title": "品名 / 规格",
        "fields": [
            ("product_name", "产品名称原文，如「轻态 · 高蛋白威化棒」", "string|null"),
            ("flavor", "口味 / 风味，无则 null", "string|null"),
            ("net_content_value", "**整包总净含量**数值，仅取数字。进口标签写成 Serving Size × Servings Per Package 而没印总净含量时，这字段留 null", "number|null"),
            ("net_content_unit", "整包总净含量单位，如 g / kg / ml / L / oz / lb", "string|null"),
            ("servings_per_pack", "每包份数，**可以是小数**（进口标签如 6.1）。无标注则 1", "number"),
            ("serving_size_value", "「每份大小」数值，仅取数字。对应包装上的 Serving Size / 每份 / Per Serving，无则 null", "number|null"),
            ("serving_size_unit", "「每份大小」单位，如 g / oz / ml / fl oz", "string|null"),
        ],
    },
    "ing": {
        "title": "配料表",
        "fields": [
            ("ingredients", "配料数组，**必须严格保持图上从左到右、逗号分隔的原始顺序**", "array<string>"),
            ("claim_words", "包装话术关键词，如「高蛋白」「0 蔗糖」「无糖」「零糖」「0 脂肪」「低钠」"
                            "「零度」，用于与真实数值对冲；无则 []", "array<string>"),
        ],
    },
    "all": {
        "title": "致敏原提示行",
        "fields": [
            ("statement", "致敏原提示原文转录", "string|null"),
            ("allergens", "直接含的致敏原词表，中文原名逐个收录", "array<string>"),
            ("cross_contact", "产线共线 / 可能含有的致敏原词表", "array<string>"),
        ],
    },
    "nut": {
        "title": "营养成分表",
        "fields": [
            ("basis", "表头声明，如「每 100 g」；无法判定填 null", "string|null"),
            ("basis_value", "表头声明的数值，如 100", "number|null"),
            ("basis_unit", "表头声明的单位，如 g / ml", "string|null"),
            # 国产标签一律以千焦(kJ)标注能量，早期版本只留了 kcal 一个字段，
            # 模型照「不许换算单位」的指令办事，只能填 null，于是「能量缺失」被误报。
            # 现在两个单位都收，换算交给 serving.py（GB 28050：1 kcal = 4.184 kJ）。
            ("energy_kj", "能量，千焦(kJ)；国产标签基本都用这个单位", "number|null"),
            ("kcal", "能量，千卡(kcal)；仅当标签直接标注千卡时填，**不要自行换算**", "number|null"),
            ("protein", "蛋白质，克", "number|null"),
            ("fat", "脂肪，克", "number|null"),
            ("trans_fat", "反式脂肪酸，克", "number|null"),
            ("carbs", "碳水化合物，克", "number|null"),
            ("sugar", "其中「糖」，克", "number|null"),
            ("fiber", "其中「膳食纤维」，克；表上未列则 null", "number|null"),
            ("sodium", "钠，毫克", "number|null"),
            ("legible", "表格数字是否全部清晰可辨；任何一格模糊/残缺即 false", "boolean"),
        ],
    },
}

# ---------------------------------------------------------------- double_check 提示
DOUBLE_CHECK_SYSTEM = """你是复核员（double_check verifier）。
输入是一张**已裁剪到单一区域**的标签图片，以及上一轮从该图中抽取出的 JSON。
你的任务：逐字段把 JSON 与图片原文核对，**只做「一致 / 不一致 / 不可辨」三态判断**。
- 一致：字段照抄 "agree"。
- 不一致：字段照抄 "corrected"，并把图上真实值写进 corrections。
- 图上模糊、裁切缺失、被遮挡：字段照抄 "unreadable"，不要猜测、不要补全。
- 禁止因为「看起来不合理」而改值；只认图片原文。
- 只输出 JSON。
"""

DOUBLE_CHECK_USER_TMPL = """待复核的区域：{title}

上一轮抽取结果：
```json
{extracted}
```

请逐字段核对后严格按此结构输出：
{{"fields":{{"product_name":"agree","ingredients":"agree","kcal":"corrected"}},
  "corrections":[{{"field":"kcal","from":466,"to":488,"reason":"图上为 488"}}],
  "status":"agree",
  "unreadable_fields":[],
  "notes":"不超过 60 字的复核说明"}}

status 取值：agree（全部一致）/ corrected（存在修正）/ unreadable（存在不可辨字段）。
若 status 为 corrected，请把修正后的完整 JSON 放进 "revised" 键；否则省略 "revised"。
"""
