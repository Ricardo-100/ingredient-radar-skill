# Agent 模式 · 不调外部端点，用 Agent 自己的模型

> 这一模式的存在理由：本 Skill 本就运行在 Agent 里，而 **Agent 本身就是一个能看图的模型**。
> 第①②步再绕一圈打到外部多模态端点，是重复劳动。Agent 模式让 Agent 自己看图产出结构化 JSON，
> 剩下的算术、判定边界、过敏分级、契约全部本地完成——**零网络请求**。

## 什么时候用

**2026-09-25 起这是唯一一种模式**，没有第二种可选。原先的 `qwen` 模式
（打到 OpenAI 兼容多模态端点）连同 `scripts/llm_client.py`、`scripts/backends/`
整个目录一起删掉了。

动机很直接：本 Skill 本就运行在 Agent 里，而 Agent 本身就是一个能看图的模型。
第①②步再绕一圈打到外部多模态端点，是重复劳动——而且每换一个平台，
都要重配一遍端点、Key、模型名。

> **「删掉」不等于「曾经的实现不可信」**：被删之前那条链路是真跑通过的
> （十条用例回放、离线回归全绿）。删它是因为维护成本与重复，不是因为它坏。
> 若将来确有需要接第二个来源（例如本地 sglang），照 `scripts/agent_mode.py`
> 的样子接进来即可——**先把新链路跑通、跑绿，再决定是否留下**，
> 不要预写适配层。

**最重要的取舍（先说清楚）**：结论分支由 Agent 选择，**不保证两次运行一致**。
`skill_pin` + `seed=7` + `temperature=0` 保证的是第③④步「同样的抽取必然算出同样的结论」，
但第①②步本身就不是确定性的。契约里会写 `judgment_source: "agent"`，别把它当成确定性结果。
REPORT.md 里的质量维度测的是「给定固化的抽取，本地判得对」，
**不覆盖「Agent 每次都抽得一样」**——那本来就不可复现。

## 跑起来

```bash
# 1. 拿一份空白模板（自带合法 verdict id 和每个区的字段表，不用凭记忆猜 schema）
python scripts/main.py --dump-agent-template /tmp/t.json

# 2. 用 Read 看那张图，按模板填好，然后：
python scripts/main.py <图片> --agent-json /tmp/t.json --goal cut --allergen 花生
```

实测（合成威化棒样例图，912×910）：从填好的 JSON 到出契约与结果图 **约 0.6 秒**，
其中绝大部分是 PIL 渲染——算术只占零头。没有网络往返，因为没有网络。

## 边界：Agent 做什么，脚本做什么

这条线划得很刻意，**不要凭手感挪**。

**交给 Agent**（没有眼睛和判断力就做不了的两件事）：

1. 四区定位框（`[x1,y1,x2,y2]`，0–1000 归一化）与 `score`；
2. 逐字段抽取：读 `references/` 里的字段表，照图上原文填；
3. 「照 `rules.yaml` 读下来该命中哪个结论分支」——即每个目标给一个 `verdict_id`。

**留在本地**（一切算得出来的东西）：

每份折算与双口径、方糖数、糖占碳水比、蛋白密度、五项 NRV%、
Mifflin-St Jeor 个人分母、过敏 direct/cross 分级、不确定边界、**全部文案**。

理由：让模型「照着规则算数」是可靠性最低的用法。`round(4.85, 1)` 在不同模型、
不同次运行里都能给出不同答案，而算术恰恰是本项目最不能抖的部分。
所以数值一律由 `serving.py` 算，模型只做选择——**模型说的每句话（标题、详情、单位）
都从 `rules.yaml` 取，不让它自己造句**。

## 完整 schema

```jsonc
{
  "judged_by": "claude-xxx @ 平台名",      // 可选。写进契约的 model 字段，留痕用
  "is_food_label": true,                    // 必填。false = 拒判，退出码 3
  "caption": "轻态 · 高蛋白威化棒，60 g",     // 必填。一句话描述图上是什么

  "regions": {
    "name": {                                // 品名 / 规格区
      "box": [68, 49, 581, 132],             // 0–1000 归一化；null = 未定位到
      "score": 0.95,
      "unreadable_fields": [],               // 显式声明「这些字段看不清」，可为空
      "data": {
        "product_name": "轻态 · 高蛋白威化棒",
        "flavor": "黑莓味",
        "net_content_value": 60,             // 整包总净含量，只要数字
        "net_content_unit": "g",
        "servings_per_pack": 1,              // 可以是小数（进口标签 6.1）
        "serving_size_value": 60,            // 「每份大小」对应的数字
        "serving_size_unit": "g"
      }
    },
    "ing": {                                 // 配料表
      "box": [64, 269, 937, 363],
      "score": 0.93,
      "data": {
        "ingredients": ["花生酱", "白砂糖"],  // 必须保持图上从左到右的原始顺序
        "claim_words": ["高蛋白"]             // 包装话术，用于与真实数值对冲
      }
    },
    "all": {                                 // 致敏原提示行
      "box": [64, 382, 937, 461],
      "score": 0.9,
      "data": {
        "statement": "含花生、…;生产线亦加工坚果。",
        "allergens": ["花生", "小麦"],        // 直接含
        "cross_contact": ["坚果"]             // 产线共线 / 可能含有
      }
    },
    "nut": {                                 // 营养成分表
      "box": [64, 495, 937, 775],
      "score": 0.94,
      "data": {
        "basis": "每 100 g",
        "basis_value": 100,
        "basis_unit": "g",
        "energy_kj": null,                   // 标的是千卡就填 null，别自己换算
        "kcal": 466,
        "protein": 18.6, "fat": 17.2,
        "trans_fat": 0, "carbs": 55.8,
        "sugar": 32.4, "fiber": null,
        "sodium": 320,
        "legible": true                      // 任何一格模糊即 false
      }
    }
  },

  "judgment": {
    "cut":  { "verdict_id": "cut_bad",  "notes": [], "uncertain_reasons": [] },
    "gain": { "verdict_id": "gain_mediocre", "notes": [], "uncertain_reasons": [] },
    "keto": { "verdict_id": "keto_bad", "notes": [], "uncertain_reasons": [] }
  }
}
```

字段的权威说明在 `regions.py::REFER_SPECS`，`--dump-agent-template` 会把它们连同
合法 `verdict_id` 一起打出来——**不要手抄本文的 schema，以模板为准**。

### 填表三条纪律

1. **看不清就填 null，别猜。** `null` 与「图上没有这一行」都会触发本地的不确定判定，
   该要求人工复核时会要求。填一个猜测值比填 null 危险得多。
2. **数值字段只放数字。** 单位进 `*_unit`。写 `"320 毫克"` 会被校验拦下并提示。
3. **`unreadable_fields` 只声明真的看不清。** 它和「图上没这一行」是两件事——
   营养成分表没列膳食纤维填 `fiber: null` 是正确的，不是不可辨。

## 分歧检测：这个模式自带的保险

`judge_agent()` 在 Agent 选完分支后，会用 `judge.goal_verdict()` **本地再算一份**。
两者不一致时，契约写 `verdict_divergence: true`、`agent_vs_rules` 给出两边分支与标题，
并强制 `human_review_required: true`。**分歧是记录，不是掩盖。**

这不是摆设。实测时它抓到了一个真实问题：用 `--serving-g 30` 把口径改成 30 g 后，
糖降到 9.7 g/份，规则引擎算 `cut_ok`，而 Agent 是按整包 60 g 选的 `cut_bad`。
报出来是：

```
结论分支分歧：Agent 选 cut_bad，规则引擎按 减脂 · 控糖口径算 cut_ok；
              当前口径 30 g/份；该目标主指标 sugar = 9.7 g/份
```

一眼就看出问题在口径上。这也说明一个使用注意：
**用了 `--serving-g` 或个人资料时，Agent 选分支要以最终口径为准**，
而 Agent 填 JSON 时看不到命令行会覆盖成多少克——所以分歧提示里会带上当前口径。

顺带它还是个免费的质量信号：拿一批图跑 agent 模式，统计分歧率，
就知道这个 Agent 读 `rules.yaml` 读得准不准。

## 退出码

`0` 出结论 / `2` 输入或 JSON 有问题 / `3` 非食品图或定位不到配料与营养表。
拒判时不产 `result.jpg`、不输出 `MEDIA:` 行——这条优先级高于「最后一行必须是 MEDIA」。

## 产物

`contract.json` / `report.json` / `result.jpg`（带定位框与结论）。
`report.json` 里额外带 `agent_payload`（Agent 的原始 JSON），便于回溯「这个结论是哪张图、
哪次读图产生的」。

agent 模式专属的契约字段：

| 字段 | 含义 |
|------|------|
| `judgment_source` | `"agent"` 或 `"rules"`（Agent 没给 verdict_id 时回落规则引擎） |
| `agent_verdict_id` | Agent 选的分支 id |
| `rules_verdict_branch` | 规则引擎本地算出的分支 id |
| `verdict_divergence` | 两者是否不一致 |
| `agent_vs_rules` | 分歧时给出两边分支与标题 |

`evidence` 数组里每区的 `double_check` 字段是 `"agent"` 而不是 `"agree"`——
如实说明这一格没经过独立复核通道，不伪装。

## 安全边界不变

Agent 模式**没有放宽任何一条**：

- 非食品图照样拒判（退出码 3、不出图、不出 MEDIA 行）；
- 不推断用户的健康状况、年龄、性别、身份、意图——目标与过敏仍由用户手动指定；
- 不臆测数值：模糊/残缺走 `unreadable_fields` + 人工复核；
- 年龄/性别/体重/身高四个原值照样不落盘，契约只留推算出的分母；
- 免责声明与人工复核提示照旧出现在最终文本里。

代码见 `scripts/agent_mode.py`；`judge.py` / `serving.py` / `rules.yaml` 一行未改。
