---
name: ingredient-radar
description: 拍摄或选择一张食品包装标签照片（含配料表 / 营养成分表），按用户手动选择的健身目标（增肌 / 减脂控糖 / 生酮）与过敏忌口，逐条给出「该不该吃」的判定，每条结论可点回原图定位框。仅处理食品包装标签，不识别风景/人像/账单/文档，不推断用户的健康状况、年龄、身份或意图。
license: Apache-2.0
# 本 Skill 声明的 Agent 侧工具范围（最小权限原则）：
#   Read —— 读脚本输出的 contract.json / report.json；
#   Write —— 只在 <skill>/output/ 里落产物，不碰 skill 目录之外的路径；
#   Bash —— 运行 scripts/main.py（纯标准库 + Pillow，不发起任何网络请求）。
# 不调 MCP、不读写用户主目录。
allowed-tools:
  - Read
  - Write
  - Bash
# 2026-09-25 起本 skill **不发起任何网络请求、不使用 API Key**：
# 第①②步的视觉能力来自 Agent 自己（references/agent-mode.md），其余全是本地计算。
# 原先为 network 能力声明的一节已删除——不是把权限藏起来，是那些代码真的没有了。
#
# 但 **env 能力仍然真实存在，没有被删**：scripts/config.py 会读 os.environ 里的
# IR_SEED / IR_TEMPERATURE / IR_OUT_DIR / IR_RULES / IR_DEBUG（全是不涉及密钥的可复现参数）。
# 第一版这里图省事写了一句「不读环境变量」，被安全扫描当场报了出来——
# 文档说不读、代码在读，这种漂移比多声明一项权限危险得多。所以如实声明：
permissions:
  - env        # 只读 IR_SEED / IR_TEMPERATURE / IR_OUT_DIR / IR_RULES / IR_DEBUG，无任何密钥变量
# 不调 MCP、不读写用户主目录。
metadata:
  version: "1.3"
  self_pin: "computed"        # 运行时由 scripts/pipeline.skill_fingerprint() 计算
  vision_source: agent        # Agent 自己看图（2026-09-25 起无 HTTP / 无外部端点）
  output_contract: "1.3"
---

# 成分雷达 · 健身配料解析 Skill

> 拍一张配料表，告诉你「以你现在的健身目标，这份东西该不该吃」，
> 并且每一条结论都能点回原图、能复现、能签名。

---

## 1. 什么时候用 / 什么时候不用（窄触发 · 强路由）

**只在同时满足以下两条时使用本 Skill：**

1. 输入是**一张食品（或保健食品）包装标签的照片**，画面里能看到配料表和 / 或营养成分表；
2. 用户想知道**「以我的健身目标，这东西该不该吃 / 吃多少合适」**，或要求核对营养成分、致敏原。

**明确不使用（负向触发）——这些情况下正确答案是不调用本 Skill：**

| 场景 | 应有的行为 |
|------|-----------|
| 风景、人像、账单、截图、路牌、文档扫描件 | 拒判，不报任何成分 |
| 「这附近路况如何」「帮我写周报」等与本 Skill 无关的请求 | 不调用 |
| 要求推断用户的健康状况 / 年龄 / 性别 / 身份 / 病史 | 拒绝并说明本 Skill 不做此类推断 |
| 只要「把这张图里的文字全部抄出来」（OCR 需求） | 不在本 Skill 职责内，可另找 OCR 能力 |
| 医疗诊断 / 疾病饮食处方 / 用药建议 | 拒绝，只做配料与营养的机械比对 |

---

## 2. 禁止行为（写死在本文件里，不依赖提示词临时叮嘱）

以下为**硬边界**，任何一条都不得违反：

1. **不推断用户的健康史、身体状况、身份、年龄、性别或意图。** 健身目标与过敏忌口一律由用户在界面上手动勾选，或由用户在对话里明确说出；Agent 不得猜测、不得沿用上一次的默认值、不得「看出」用户可能在减脂。
2. **不臆测任何数值。** 营养成分模糊、残缺、被遮挡 → 标记 `uncertain: true` 并说明哪些字段不可辨，**绝不**补默认值、绝不按「同类产品常见值」估算、绝不把「可能是」写成确定数字。
3. **不硬报过敏。** 用户勾选的忌口与产品致敏原没有交集时，如实报告「未命中」，不得为了凑告警而标红。干净配料不乱标 flag。
4. **不给出医疗结论。** 只做「包装数字 × 你的目标」的机械比对；输出必须含免责说明，且不得替代医嘱。
5. **不把图片发到任何外部服务。** 本 skill 不含任何 HTTP / 网络代码；图片只在本次会话的上下文里给 Agent 看，不落网络缓存、不转发第三方。
6. **不修改 checked-in 的配置与规则。** `rules.yaml` 的阈值调整必须由人显式提交，运行期不改文件。
7. **不打印明文 API Key。** 日志、report.json、contract.json 一律不得包含 Key。
8. **不把个人资料当可推断项，也不把它落盘。** 年龄 / 性别 / 体重 / 身高 / 活动水平和目标、
   过敏一样，一律由用户手动提供；缺任一项就整体回落到人口 NRV 口径，**不猜、不给默认值**。
   `contract.json` 与 `report.json` 只写推算出的分母（每日千卡、活动系数），
   **不写四个原始字段**——判定可复现靠的是分母本身，不需要那些原值。
9. **不做饮食处方。** 默认只算「维持当前体重一日所需」（Mifflin-St Jeor × 活动系数）；
   「减脂该减多少、增肌该加多少」属于处方，要算必须用户显式开 `--goal-adjust`，
   且会在 `notes` 里写明这是叠加了乘数的估算值。

> **现在真的「画面不出设备」了**：2026-09-25 移除了全部 HTTP 代码，图片只在本次会话的
> 上下文里给 Agent 看，不发往任何推理端点。这个卖点现在是事实，不再是附带条件的说法。

---

## 3. 前置提问（参数不全时先问，不允许 Agent 猜）

运行前必须已知三项，缺任一就先问用户：

| 参数 | 取值 | 说明 |
|------|------|------|
| 图片 | 本地路径 / 上传的文件 | 没有图片无法开始 |
| `goal` | `gain` 增肌 / `cut` 减脂·控糖 / `keto` 生酮 | **必须由用户选**；用户没说就问，不默认 |
| `allergens` | 花生 / 乳 / 麸质 / 坚果 / 大豆 / 鸡蛋（可多选，可空） | **必须由用户勾**；用户没提就按「未勾选」处理并明确告知「未考虑过敏因素」 |

可选的个人资料（**不给就按人口 NRV 说话，不会卡住流程**）：

| 参数 | 取值 | 用途 |
|------|------|------|
| `age` / `sex` / `weight_kg` / `height_cm` | 岁 / `male`·`female` / kg / cm | Mifflin-St Jeor 算基础代谢率 |
| `activity` | `sedentary` 久坐 ×1.3 / `active` 一般健身 ×1.55 / `athlete` 高强度 ×1.8 | 活动系数 |

五项齐全 → 「占每日百分之几」按**你维持当前体重一日所需**算；
缺任一项 → 整体回落到人口 NRV，并在文案里说明用的哪个分母。
四个原始字段不落盘，契约里只有推算出的分母。

提问模板（一次问完，不要连环追问）：

> 请给我一张配料表照片，并告诉我两件事：
> ① 你的健身目标是「增肌 / 减脂控糖 / 生酮」中的哪一个？
> ② 有需要避开的过敏原或忌口吗（花生 / 乳 / 麸质 / 坚果 / 大豆 / 鸡蛋）？
> 我不替你猜这两项——它们直接决定结论。
> （可选）想按你自己的每日所需来算占比，就把年龄、性别、体重、身高和活动水平告我；
> 不说也行，那就按通用参考值算。

---

## 4. 怎么跑

```bash
# 环境自检（纯本地，不联网：规则表 / 依赖 / skill_pin）
python scripts/main.py --probe

# 拿 Agent 模式的空白模板
python scripts/main.py --dump-agent-template /tmp/t.json

# 用 Read 看这张图，按模板填好（含四区定位框与逐字段抽取），然后：
python scripts/main.py <图片路径> --agent-json /tmp/t.json --goal cut --allergen 花生 --allergen 坚果

# 「一次吃多少克」：**留空 = 整包**（默认口径）。手填就按手填的算，并在 notes 里声明覆盖了包装口径
python scripts/main.py <图片路径> --serving-g 85      # 这袋我掰一半，按 85 g 算

# 个人口径：五项齐全才生效，「占每日百分之几」改按你每日所需算
python scripts/main.py <图片路径> --age 30 --sex male --weight-kg 70 \
    --height-cm 175 --activity sedentary
# 可选：在维持热量上再按目标增减（减脂 ×0.85 / 增肌 ×1.1），默认关闭
python scripts/main.py <图片路径> --age 30 --sex male --weight-kg 70 \
    --height-cm 175 --activity active --goal-adjust

# 一次算完全部目标：第③步对每个目标各判一遍（纯本地，毫秒级）
python scripts/main.py <图片路径> --agent-json /tmp/t.json --all-goals

# 只拿契约 JSON（管道友好）
python scripts/main.py <图片路径> --agent-json /tmp/t.json --goal cut --allergen 花生 --json
```

依赖：Python 3.8+ 与 Pillow。**不需要 PyYAML**（装了会自动用，没装走内置零依赖解析器
`scripts/miniyaml.py`，两者解析结果经测试完全一致）。除 Pillow 外无第三方依赖。

配置（环境变量，默认值见 `scripts/config.py`）：

| 变量 | 默认 | 含义 |
|------|------|------|
| `IR_SEED` | `7` | 固定 seed，保证同图同结果 |
| `IR_TEMPERATURE` | `0` | 追求可复现 |
| `IR_OUT_DIR` | `<skill>/output` | 产物目录 |
| `IR_DEBUG` | `0` | 调试开关 |

> **没有端点 / Key / 模型这几项了。** 2026-09-25 移除了全部 HTTP 代码
> （原 `scripts/llm_client.py`、`scripts/backends/` 整个目录），
> 视觉来源改成 Agent 自己。所以不再有 `IR_BASE_URL` / `IR_API_KEY` /
> `IR_MODEL` / `IR_BACKEND` / `IR_TIMEOUT`——不是改名，是那些事不做了。

个人资料（年龄 / 性别 / 体重 / 身高 / 活动水平）**不走环境变量、不进配置快照**，
只在一条命令或一次请求的内存里用，用完即弃；落盘的只有推算结果（见 6.4）。

---

## 5. 四步流水线

```
① Grounding 定位       Agent 自己看图，框出「品名/配料表/致敏原/营养成分表」四区
                       输出：短语 + 0–1000 归一化框 + score
        ↓
② Referring 归纳       逐区读字段原文，按 REFER_SPECS 填结构化 JSON
        ↓
③ 规则判定             rules.yaml 里的阈值与文案，零硬编码
        ↓
④ 输出契约             contract.json + result.jpg + 最后一行 MEDIA:
```

第①②步由 **Agent 自己**完成——它就在上下文里看着那张图。产出按
`scripts/agent_mode.py` 约定的 schema 交给 `--agent-json`，之后全部本地。

**2026-09-25 移除了外部推理端点整条线**（原 `scripts/llm_client.py` 与
`scripts/backends/` 整个目录，含 `qwen_vl.py` / `base.py`）。原因很直接：
本 Skill 本就运行在 Agent 里，Agent 本身就是个能看图的模型，再绕一圈调外部端点是重复劳动，
而且每个平台都要重配一遍端点、Key、模型名。产物结构与坐标工具搬到了
`scripts/vision_types.py`，一行网络代码都没留。

将来若真要接第二个来源（例如本地 sglang），**不要再预写适配层**：
先让那条路跑通、跑绿，再照 `agent_mode.py` 的样子接进来。

---

## 5.1 Agent 模式：第①②步由 Agent 自己看图

```bash
# 1. 拿模板（自带合法 verdict id 与每个区的字段表，不用凭记忆猜 schema）
python scripts/main.py --dump-agent-template /tmp/t.json

# 2. 用 Read 看这张图，按模板填好（含四区定位框与逐字段抽取），然后：
python scripts/main.py <图片> --agent-json /tmp/t.json --goal cut --allergen 花生
```

实测：整条链路 0.6–0.8 秒——因为没有任何网络往返，全是本地算术加一次 PIL 渲染。

**边界划在哪（重要，别凭手感挪）**：Agent 只做需要眼睛和判断力的三件事——
四区定位框、逐字段抽取、以及「照 rules.yaml 读下来该命中哪个结论分支」（verdict_id）。
每份折算、NRV%、Mifflin-St Jeor 个人分母、过敏 direct/cross 分级、不确定边界、
**全部文案**都在本地算。理由：让模型照着规则算数是可靠性最低的用法
（`round(4.85, 1)` 换个模型就能换个答案），而算术恰恰是本项目最不能抖的部分。
模型说的每句话都从 `rules.yaml` 取，不让它自己造句。

**必须先知道的取舍**：结论分支由 Agent 选，**不保证两次运行一致**。
契约写 `judgment_source: "agent"`，看到它就别当确定性结果引用。
`REPORT.md` 里的质量维度测的是「给定固化的抽取，本地判得对」，
不覆盖「Agent 每次都抽得一样」——那本来就不可复现。

**自带的保险**：Agent 选完分支，本地会用 `judge.goal_verdict()` 再算一份，
不一致就写 `verdict_divergence: true` + `agent_vs_rules`（两边分支与标题）
并强制人工复核。实测它抓到过真实问题：`--serving-g 30` 后糖降到 9.7 g/份、
规则引擎算 `cut_ok`，而 Agent 按整包 60 g 选了 `cut_bad`——提示里会带上当前口径，一眼看出原因。
分歧率还是个免费的质量信号：跑一批图统计一下，就知道这个 Agent 读 rules.yaml 准不准。

完整 schema、填表纪律、退出码、专属契约字段见 `references/agent-mode.md`。
**`judge.py` / `serving.py` / `rules.yaml` 一行未改。**

**评测现在是回放模式**：第①②步的抽取结果固化成 `evals/fixtures/*.json`
（2026-09-25 用最后一次真实抽取采集），`run_evals.py` 把 fixture 喂给
`agent_mode`，整套十条 12 秒跑完、不调任何模型。要重新采集 fixture 见
`tools/capture_fixtures.py`。

---

## 6. 输出契约（铁纪律）

### 6.1 正常路径

最终回复的**最后一个非空行**必须是纯文本：

```
MEDIA:/绝对路径/result.jpg
```

- 生成了文件 ≠ 用户看到了图片，所以最后一行本身也是契约的一部分。
- `/绝对路径/` 必须是**真实存在的绝对路径**，不接受相对路径。
- 在此之前给人读的结论（目标 verdict、每条 flag、过敏命中、免责），再放契约 JSON。
- `evidence[].box` 是**原图像素坐标**；`box_norm_0_1000` 是 0–1000 归一化值，
  两者满足 `px = round(v / 1000 * W)`——这个关系很简单，任何人都能当场手算验证。

### 6.2 负向路径（重要，优先级高于 6.1）

输入不是食品包装标签、或定位不到配料表 / 营养成分表时：**不产出 result.jpg、
不输出 `MEDIA:` 行**，只返回一段拒判说明，并以退出码 `3` 结束。

理由：对非食品图，「正确答案是不调用该 skill / 不硬出结论」——对着一张风景图也渲染一张「分析结果」，本身就是错误的输出。
对着一张风景图也渲染一张「分析结果」，本身就是错误的输出。

### 6.3 契约字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `contract_version` | string | 契约版本 |
| `status` | string | `ok` / `rejected` |
| `product` | string | 从品名区抽取，非人工常量 |
| `goal` / `goal_label` | string | 用户手动选择 |
| `serving_g` | number | **一次吃的克数**。空 = 整包（默认）；手填则覆盖包装口径，`net_content.override` 为 true |
| `per_100g` / `per_serving` | object | **双口径**：能量/蛋白/脂肪/反式脂肪/碳水/糖/膳食纤维/钠 |
| `flags` | string[] | 基础 flag 的标题（糖 / 热量 / 蛋白质 / 脂肪 / 反式脂肪 / 碳水 / 钠 / 代糖 / 膳食纤维） |
| `allergen_hits` | string[] | 过敏命中（direct / cross） |
| `verdict` / `verdict_level` | string | 目标三态判定标题；`level` 为 `good` / `warn` / `bad` |
| `uncertain` | boolean | 存在不可辨或缺失字段 |
| `human_review_required` / `_reasons` / `_text` | boolean / array / string | **恒显式给出**（干净图也是 `false`），下游不必猜「缺字段」是否等于「不用复核」 |
| `disclaimer` | string | 免责声明，**必须出现在最终回复文本里** |
| `daily_reference` | object | 占比口径 + 分母数值（见 6.4），**不含任何个人原值** |
| `ingredients` / `claim_words` / `sweeteners` | array / array / string | 「为什么这么判」的原文证据：配料、包装话术、识别到的代糖 |
| `notes` | array | 单位换算、口径近似等如实说明（如「千焦按 GB 28050 口径换算为千卡」「能量分母按用户手填资料推算：BMR × 活动系数 ≈ N kcal/天」），**恒显式给出**（没有要说明的口径时为空数组） |
| `evidence` | array | 区域 / 像素框 / 0–1000 框 / score / double_check 状态 / 原文摘要 |
| `skill_pin` | string | 自研内容 SHA-256 前 8 位，内容变则 pin 变 |
| `seed` / `temperature` | number | 复现依据 |
| `backend` / `model` / `rules_version` | string | 现场复现留证 |
| `elapsed_seconds` / `generated_at` | number / string | 耗时与时间戳 |

**0 与缺失是两件事**：图上标 `0` 就填 `0`（例：无糖可乐能量 0），
只有图上**真的没有这一行**才填 `null`。`0` 会进规则判定，`null` 会触发 `uncertain`。
国产标签按 GB 28050 用千焦（kJ）标注能量，`resolve_energy()` 按 1 kcal = 4.184 kJ
换算成千卡并写入 `notes`；标签直接标千卡时原样采用、不做二次换算。

### 6.4 占比口径与 `daily_reference`（v1.3）

所有「占每日百分之几」共用一个分母，取值只有两种：

| `basis` | 分母 | 何时用 |
|---------|------|--------|
| `population_nrv` | 能量 2007.6 kcal、蛋白 60 g、脂肪 60 g、碳水 300 g、钠 2000 mg（GB 28050 人口 NRV） | 默认；用户没给个人资料时 |
| `personal` | 能量 = Mifflin-St Jeor BMR × 活动系数（久坐 1.3 / 一般健身 1.55 / 高强度 1.8） | 年龄 / 性别 / 体重 / 身高 / 活动水平五项齐全时 |

蛋白 / 脂肪 / 碳水 / 钠的参考值**始终用人口 NRV**：个人化「你该吃多少蛋白」属于饮食处方，
超出本 Skill「只做机械比对」的边界。只有能量会换成个人口径——因为它就是用户问的「我一天能吃多少」。

`daily_reference` 只写分母与推算过程（`daily_kcal` / `activity_factor` / `bmr_kcal` /
`goal_adjusted` / `goal_adjust_factor`），**不写年龄、性别、体重、身高的原值**。理由是判定可复现只需要分母本身：
拿到契约的人能重算每一个百分比（包括乘数），但不该看到用户的出生年份和体重。

---

## 7. 渐进披露（读文件的顺序）

启动时只加载 frontmatter 的 `description`（几十 token）。命中之后按需读：

1. `SKILL.md`（本文件）——契约与边界；
2. `scripts/rules.yaml`——要改阈值 / 改文案时；
3. `references/regulations.md`——要引 GB 7718 / GB 28050 依据时；
4. `references/allergen-map.md`——要加过敏原词表时；
5. `references/prompt-contract.md`——要调 grounding / referring 提示词时；
6. `references/agent-mode.md`——要用 Agent 模式（不调外部端点）时；
7. `evals/evals.json`——要跑评测时。

---

## 8. 可复现性

| 手段 | 落点 |
|------|------|
| 固定 seed | `IR_SEED=7`，随契约落盘 |
| 温度 0 | `IR_TEMPERATURE=0` |
| 内容指纹 | `skill_pin`（SHA-256 前 8 位），由 `pipeline.skill_fingerprint()` 现算 |
| 规则版本落盘 | `contract.rules_version` |
| 抽取来源落盘 | `contract.model` / `contract.backend` —— **2026-09-25 起这里记的是「第①②步是谁做的」，不是模型名**。Agent 模式下取 `judged_by`（fixture 回放时会原样带上「本次抽取由谁产出」的说明） |

现场两遍跑同一张图：只要 `skill_pin` + `seed` + `extraction_source` + `rules_version`
四项一致，结论必然一致。差异出现时先查这四项。

关于 `contract.model` 要说清楚：**它只说明抽取是谁做的，不保证结论相同**。
结论的第③④步全部由本地 `judge.py` / `serving.py` / `rules.yaml` 算出，
所以「换个 Agent 再抽一遍」可能给出不同的框、进而不同的数值——这与算术是否可复现是两件事。
2026-09-25 之前这里填的是端点模型名（如 `qwen3.6-35b`），当时「查模型服务是否被重启」是条有效的排查项；
现在没有模型服务了，这条排查项随之作废。

---

## 9. 已知边界（如实告知用户）

- `score` 是定位时的自报置信度，不是校准过的概率；不同模型之间不可比，只能看同一模型内的相对高低。
- 净含量按容量（ml）标注时，折算按 1 ml ≈ 1 g 近似，未做密度校正，会在 `notes` 里说明。
- 膳食纤维成分表未列时，**净碳水不可知**，此时按总碳水从严判断并在文案中声明。
- 反式脂肪「标 0」按 GB 28050 是 ≤ 0.3 g/100 g，不等于绝对为 0，文案已声明。
- 单张照片、单次推理；不追踪历史摄入，不给「一天还能吃多少」的累计结论。
- 每日所需是**估算**：Mifflin-St Jeor 是群体回归公式，个体差异可达 ±10% 以上，
  肌肉量、甲功、妊娠、药物都会让它偏；文案里只会说「约」，不会说「你应该吃」。
- 钠与热量除毫克 / 千卡外，同时给出「占每日 NRV 的百分之几」（钠 NRV 2000 mg、
  能量 NRV **8400 kJ ≈ 2007 kcal**——国标写的是 kJ，当 kcal 用会把占比算小 4.184 倍）——
  脱离占比谈「钠高不高」没有意义，判分按占比分档、给用户的标题仍是原单位。
- **verdict 是条件分支，不是一句话结论。** 生酮按碳水分三档（≤5 g 友好 / <20 g 谨慎 / ≥20 g 避雷）、
  减脂按糖与热量分档、增肌按蛋白分档。早期版本对生酮只有一句固定文案，
  于是无糖可乐「碳水 0 g」被判成「足以直接中断血酮 · 避雷」——与生酮的机制正好相反，
  这条坑写在了 `rules.yaml` 的注释里，改阈值前先读。
- **「蛋白质名不副实」只在包装真宣称过蛋白时才报**（`requires_claim`）。
  无糖可乐蛋白 0 g，但它从没宣称过蛋白，报这一条是无的放矢；没有蛋白宣称时，
  改为中性的 `protein_irrelevant` 分支说明「与蛋白补充无关」。
- 代糖（阿斯巴甜、安赛蜜、三氯蔗糖、甜菊糖苷、糖醇等）不升糖但个体反应差异大，
  识别到即单独提示；其中含苯丙氨酸的（阿斯巴甜 / 纽甜 / 阿力甜）会额外提示 PKU 患者避开。
