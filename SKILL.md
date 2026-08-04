---
name: anki-tv-vocab
description: >
  从美剧字幕创建 Anki 记忆卡片。用户只需报剧名+第几季第几集（如"做《绝望主妇》S07E09 的卡片"），
  AI 自动联网抓取该集剧本、提取生词、补全音标/词性/中文释义/例句翻译，再自动生成单词发音（TTS）
  和例句发音（TTS），并**通过 AnkiConnect 直接推送到用户正在运行的 Anki**（无需手动导入 .apkg）。
  若用户未装 AnkiConnect 或 Anki 未运行，则退化为生成 .apkg 文件交付。
  用户无需提供字幕文件、无需用豆包、无需粘贴文本。卡片含音标、词性、中文释义、双语例句、剧集来源，大留白排版。
  也支持从豆包等 AI 工具导出的 CSV 直接转换（备选流程）。
  解决无音频、排版紧凑、混入重复中文等问题。
  触发词："做单词卡片"、"Anki 导入"、"美剧学英语"、"字幕转 Anki"、
  "生成 apkg"、"记单词"、"追剧学英语"、"帮我做这一集的卡片"、"XX S07E09 的卡片"、"anki cards"、
  "推送到 Anki"、"直接导入 Anki"、"连上我的 Anki"。
metadata:
  python_deps: genanki, edge-tts
  requires: Anki + AnkiConnect 插件（直推模式）；否则纯 .apkg 模式可用
---

# Anki TV Vocabulary — 美剧字幕转 Anki 卡片

从美剧字幕创建高质量 Anki 记忆卡片，自带音频和整洁排版。

## 前置准备

> **路径约定（克隆到别的机器只需改这里）**：本 skill 所有脚本都在 `scripts/` 下，用相对路径 `$SKILL_DIR` 引用，不写死绝对路径。你只需把 `SKILL_DIR` 指向本 skill 根目录；`$PYTHON` 已在各处带默认值（你本机的 venv），若不对可先 `export PYTHON="你的解释器路径"` 再跑。

### Python 依赖

使用隔离的 Python venv（**必须用此路径**，不要用系统 Python）：

```bash
# Python 可执行文件
PYTHON="${PYTHON:-C:/Users/cmy/.workbuddy/binaries/python/envs/default/Scripts/python.exe}"

# 核心脚本（字幕解析、词典查询、TTS、apkg 构建）
SCRIPT="$SKILL_DIR/scripts/anki_tv_vocab.py"

# CSV 转换脚本（豆包/AI 导出格式 -> cards.json，备选流程用）
CSV_SCRIPT="$SKILL_DIR/scripts/csv_to_cards.py"

# 剧名 -> 字幕站 slug 映射表（抓取剧本时查这个）
SHOWS="$SKILL_DIR/scripts/shows.json"
```

如果依赖未安装，先安装（使用清华镜像）：

```bash
"$PYTHON" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple genanki edge-tts
```

### 验证安装

```bash
"$PYTHON" -c "import genanki; import edge_tts; print('OK')"
```

## 主工作流（默认）：你只报集数，AI 自动抓字幕 + 制卡

**用户唯一需要做的事**：告诉我剧名 + 第几季第几集。例如：
> "做《绝望主妇》S07E09 的单词卡片"
> "帮我做 Friends S03E12 的卡片"

用户**不需要**提供字幕文件、不需要用豆包、不需要粘贴任何文本——字幕由 AI 自己联网抓取。

AI 收到后执行以下完整流程：

### 第 1 步：抓取该集剧本（AI 联网）

1. **剧名 → slug 映射**：读取 `scripts/shows.json`，把用户给的剧名（中文/英文/别名）映射到 springfieldspringfield.co.uk 的 `tv-show` slug（如 `绝望主妇` → `desperate-housewives`）。
   - 若查不到，用英文名按 kebab-case 推导（小写、空格转连字符、去标点）；仍拿不准就 WebSearch `"剧名 season X episode Y transcript"` 确认 slug。
2. **构造 URL**（规律稳定）：
   `http://www.springfieldspringfield.co.uk/view_episode_scripts.php?tv-show={slug}&episode=s{SS}e{EE}`
   例如：`...?tv-show=desperate-housewives&episode=s07e09`
3. **用 WebFetch 抓取剧本**，prompt 要求**逐行原文返回**（每句 `角色: 台词`，不要总结、不要加注释、不要漏行）：
   > "Extract the full episode script verbatim. Return each spoken line as 'Character: line'. Do NOT summarize, do NOT add notes, do NOT skip any lines. Just the raw dialogue."
4. **兜底**：若 springfield 没有该剧，用 WebSearch 找备选源（如 subslikescript.com、tvfanatic、剧本站），再 WebFetch。

> 注意：本机直连字幕站会被网络拦截（DNS 污染跳百度），**必须用 WebFetch 工具抓取**（走云端代理，已验证可用）。不要尝试用 curl/Python 直连。

### 第 2 步：AI 提取生词 + 补全数据

AI 基于抓到的剧本完成所有工作：

> **选词标准（按用户英语水平）**：用户目前**大三、CET-4 已过、CET-6 未过、英语基础偏弱，目标是雅思（IELTS）**。因此选词要"够得着、用得上"：
> - **主选区间**：CET-4 已掌握范围**之上一点**、落在 CET-6 / 雅思核心的**中高频**词（即"稍微超出但可掌握"）。避免两类极端：① 过于生僻/专业（GRE 级、archaic、极冷门术语，如 bunion 拇囊炎、onesie 连体衣、diaper 尿布这类生活极用词——除非属于健康/育儿等雅思常见话题且剧情关键）；② 过于简单（CET-4 早已滚瓜烂熟的基础词，如 happy、water、go）。
> - **优先覆盖雅思常见话题**：教育、环境、社会、健康、科技、文化、心理/情感、工作/职业、犯罪/法律（本剧常涉及）。每个词尽量能归入一个话题，便于联想记忆。
> - **优先"对提分更有用"的词**：一词多义、易混词、拼写易错词、地道搭配/词组（phrasal verb、collocation）。
> - **数量**：每集 15-25 词，生词密度低时宁少勿滥，质量优先于数量。
> - 拿不准时倾向"选"——只要是中高频、能在雅思里用上就值得记；只有明显偏离上述区间才跳过。

1. **按上述标准浏览剧本**，挑选值得学习的生词/词组（排除极常见基础词，优先选有语境、能体现剧情或地道表达的）
2. **为每个词找一句剧本原句**作例句（优先简短、语境清晰的句子；同一词多次出现只选最典型的一句）
3. **补全每个词的**：
   - `phonetic`：IPA 音标（用 AI 自身知识，准确优先；不要因为拿不准就留空）
   - `pos`：词性（adj. / v. / n. / phrase 等）
   - `meaning`：简洁准确的中文释义
   - `example_translation`：例句的中文翻译
4. **去重**：同一单词只出一张卡片

> 注：词典 API（api.dictionaryapi.dev）在国内不通，AI **直接用自身知识补全音标和释义**，不依赖 lookup 命令。音频一律用 TTS 生成。

### 第 2.5 步：剧情简介（synopsis）—— **当前已关闭（用户偏好）**

> **用户偏好（2026-07-24）**：剧情简介太啰嗦、影响使用，**不要**在卡片上显示简介。所以：
> - `push_to_anki.py` 不再读取 `synopsis`/`source` 字段，卡片底部不渲染任何简介行。
> - 卡片模板已移除 Source 显示（更新模型用 `updateModelTemplates`）。
> - 若未来用户想恢复简介，再按下方"查证规则"写。

<details>
<summary>若需恢复简介，必须遵守的查证规则（默认不启用）</summary>

> **重要**：AI 写剧情时容易自信地"幻觉"——把没发生过的事写得像真的（曾把 S07E09 简介写成「Susan 安慰思念 Mike 的 Renee」，实际剧情里根本没有）。所以 synopsis **不能凭模型记忆写**。

正确做法：
1. **先确认集的真实标题**（避免把 S07E09 "Pleasant Little Kingdom" 误称 "Beautiful Girls"——后者是 S03E09 的标题）。可用 WebSearch 查证。
2. **基于第 1 步抓到的真实剧本**写简介——只写剧本里实际发生的情节，最多 4-6 句，覆盖主要人物。
3. **若对某个情节拿不准，宁可不写**也不要补上看起来合理但剧本里没有的剧情。

</details>

### 第 3 步：写出 cards.json

AI 把数据写成如下 JSON（用 Write 工具存到临时文件，如 `/tmp/cards.json`）：

```json
{
  "deck_name": "绝望主妇 S07E09",
  "synopsis": "Renee 生日晚宴上醉酒向 Susan 吐露一生的挚爱是 Tom（Lynette 的丈夫）；Gaby 设计让移民局抓走 Carmen 以挽留 Grace，但 Carmen 当晚带 Grace 逃往德州；Keith 准备向 Bree 求婚，被临时邀来同席的 Keith 父亲 Richard 搅黄；Paul 用冤狱和解金买下紫藤巷 7 栋房产，欲开罪犯中途之家，遭 Lynette 牵头业委会反对。",
  "cards": [
    {
      "word": "available",
      "phonetic": "/əˈveɪləbl/",
      "pos": "adj.",
      "meaning": "有空的；可获得的",
      "example": "Are you available tonight?",
      "example_translation": "你今晚有空吗？"
    }
  ]
}
```

**字段说明**：
- `deck_name`：牌组名，惯例为 "剧名 SxxExx"
- `synopsis`（必填，顶层）：**本集剧情简介**（1-3 句中文），会渲染在每张卡片底部"剧情简介"一行。从剧本/剧情提炼，帮助回忆语境。**不要**写成 "追剧学英语" 这类无意义标注。
- `cards`：卡片数组
  - `word`（必填）：要记的单词或词组
  - `phonetic`：IPA 音标，如 /əˈveɪləbl/
  - `pos`：词性，如 adj. / v. / n. / phrase
  - `meaning`：中文释义，简洁准确（贴近雅思释义）
  - `example`：来自剧本的英文例句（保留原句，不加额外翻译）
  - `example_translation`：例句的中文翻译

**注意事项**：
- 例句只保留英文原文，**不要混入中文**
- 中文释义要精炼，不要冗长或重复
- 同一单词只出现一次，避免重复卡片
- 一集通常挑 15-25 个词，**严格按上文"选词标准"筛选**（CET-4 之上一点、雅思中高频、覆盖常见话题）

### 第 4 步（默认·推荐）：直接推送到 Anki（AnkiConnect）

前提是用户电脑上 **Anki 正在运行且已装 AnkiConnect 插件**（详见文末「直推 Anki 的关键坑」）。

```bash
PUSH="$SKILL_DIR/scripts/push_to_anki.py"

# 直接把卡片推送进用户正在运行的 Anki（自动建牌组/模型、生成并附带 TTS 音频）
"$PYTHON" -u "$PUSH" -c cards.json --skip-dict
```

脚本会自动：
1. 用 Edge TTS（en-US-JennyNeural）为每个单词 + 例句合成发音（**文件名带本集唯一哈希前缀**，避免和别的集撞名）
2. 通过 AnkiConnect 创建模型 `TV Vocabulary` 与牌组 `绝望主妇 S07E09`（若已存在则跳过）
3. `addNote` 把每张卡片加进 Anki，并把音频用 `audio` 参数挂到对应字段（**不要**自己预先写 `[sound:]` 标签）
4. 因为本机 Anki 版本会忽略 `addNote` 的 `deckName`（卡片会落进"系统默认"牌组），最后用 `changeDeck` 把卡片移动到正确的牌组

> **验证推送结果**（可选但建议）：用 AnkiConnect 查一下牌组卡片数、确认音频字段是单个 `[sound:]` 标签且文件存在：
> ```bash
> "$PYTHON" -c "import json,urllib.request;u='http://127.0.0.1:8765';\
> r=lambda a,p={}:json.loads(urllib.request.urlopen(urllib.request.Request(u,data=json.dumps({'action':a,'version':6,'params':p}).encode(),timeout=10)).read())['result'];\
> print('牌组卡片数:',len(r('findCards',{'query':'deck:\"绝望主妇 S07E09\"'})))"
> ```

### 第 4 步（备选/兜底）：生成 .apkg 文件

如果 Anki 没开、没装 AnkiConnect，或用户就想要 .apkg，退化为生成文件交付：

```bash
"$PYTHON" -u "$SCRIPT" build -c cards.json -o deck.apkg -d "绝望主妇 S07E09" --skip-dict
```

脚本会自动：对每个单词/例句用 Edge TTS 合成发音，批量并发生成（最多 3 个同时），打包为 .apkg。
生成进度会实时打印，20 张卡片约需 2-3 分钟（TTS 生成时间）。然后用 present_files 把 .apkg 交给用户，提示双击导入。

### 第 5 步：交付

- **直推模式**：告诉用户卡片已进 Anki，牌组名 `剧名 SxxExx`，列出本次挑选的单词方便增减；无需交付文件。
- **apkg 模式**：用 present_files 呈现 .apkg，提示双击导入。

---

## 直推 Anki（AnkiConnect）的关键坑（必读）

这套直推流程踩过的坑，改脚本时务必保留对应处理，否则会产出生病卡片：

1. **`addNote` 的 `deckName` 在本机 Anki 版本被忽略** —— 卡片一律落进当前牌组（"系统默认"）。必须在 `addNote` 之后收集新增 note 的 card id，再调用 `changeDeck(cards, deck)` 移到目标牌组。已封装在 `push_to_anki.py` 里。
2. **不要自己预先写 `[sound:]` 标签** —— 若字段里先写了 `[sound:word.mp3]` 又传了 `audio` 参数，AnkiConnect 会把同一文件导入两遍，字段里出现**双标签** `[sound:a.mp3][sound:a-<hash>.mp3]`。正确做法：字段 `WordAudio`/`SentenceAudio` 留空，把 `audio` 条目的 `fields` 指向它们，让 AnkiConnect 自己写标签。
3. **音频文件名要按集唯一** —— 用 `deck_name` 的 md5 前 10 位作前缀（`tv_<hash>_000.mp3` / `tvs_<hash>_000.mp3`），否则不同集都用 `word_0000.mp3` 会**撞名**：后导入的集把文件改名成哈希名，而字段里那个旧 `[sound:word_0000.mp3]` 标签却指向了**上一集**的音频（串台）。这是最容易翻车的一点。
4. **AnkiConnect 必须重启 Anki 才生效** —— 装好插件后让用户彻底关闭再重开 Anki。探测是否就绪：`urllib` 连 `http://127.0.0.1:8765` 发 `{"action":"version","version":6}`，返回 `{"result":6}` 即正常。
5. **首次推送会顺带在 Anki 里建好模型 `TV Vocabulary` 和牌组**；之后再次推送时，`ensure_model` 会用 `updateModelTemplates` + `updateModelStyling` **同步**最新模板和 CSS（保证改动 CARD_MODEL 后旧 Anki 也能跟上），`push_to_anki.py` 已封装。
6. **重复推送**：`push_to_anki.py` 用 `allowDuplicate:false` + `duplicateScope:"deck"`，同一集重复跑会自动跳过已存在的单词；用 `--replace` 则先清空该牌组再推（会丢失已学进度，慎用）。
7. **改完脚本先跑 smoke test**（见文末「测试」）。



### 备选工作流：用户已有豆包/AI 导出的 CSV

如果用户手上已有豆包等工具整理好的单词 CSV（word / html背面 / source 三列），可直接转换（跳过抓取与提取）：

```bash
PYTHON="${PYTHON:-C:/Users/cmy/.workbuddy/binaries/python/envs/default/Scripts/python.exe}"
CSV_SCRIPT="$SKILL_DIR/scripts/csv_to_cards.py"
BUILD_SCRIPT="$SKILL_DIR/scripts/anki_tv_vocab.py"

# Step 1: CSV -> cards.json
"$PYTHON" "$CSV_SCRIPT" -i "input.csv" -o "/tmp/cards.json" -d "剧名 SxxExx"

# Step 2: cards.json -> .apkg（自动生成单词+例句音频）
"$PYTHON" -u "$BUILD_SCRIPT" build -c "/tmp/cards.json" -o "/tmp/output.apkg" -d "剧名 SxxExx"
```

**CSV 解析器自动处理**：
- 提取音标（英 /xxx/ 美 /yyy/ 格式）
- 提取词性+释义（如 `adv. 假设地`）
- 提取例句（`例句：` 开头的行）
- 清除 emoji 标记（🔊📝💡 等）
- 自动去重（同一单词只保留一张）
- 分隔符自动检测（Tab 或逗号）

## 卡片模板设计

### 正面（问题）

```
        available
        /əˈveɪləbl/
        [▶ 发音]
```

### 背面（答案）

```
        available
        /əˈveɪləbl/
        [▶ 发音]

        ─────────────────

        adj.  有空的；可获得的

        ─────────────────

        Are you available tonight?
        [▶ 例句发音]
        你今晚有空吗？

        ─────────────────
        剧情简介：Susan 安慰思念 Mike 的 Renee；Gaby 帮 Carmen 与女儿 Grace 躲避移民局；……
```

### 排版特点（解决"紧凑"问题）
- 上下左右大留白（padding: 48px 32px）
- 单词 40px 大字号，视觉突出
- 各区块之间用分隔线和 28px 间距隔开
- 例句用浅蓝底色卡片包裹，与释义区分
- 底部"剧情简介"用浅灰色小字（带"剧情简介"标签），不抢视觉焦点，帮助回忆剧情语境

## 可选配置

### TTS 语音选择

默认使用 `en-US-JennyNeural`（女声，自然亲切）。其他可选：

| 语音 | 风格 |
|------|------|
| en-US-JennyNeural | 女声，自然亲切（默认） |
| en-US-GuyNeural | 男声 |
| en-US-AriaNeural | 女声，温暖 |
| en-US-DavisNeural | 男声，沉稳 |

在 build 命令中用 `--voice` 指定。

### 跳过音频生成

如果只需要卡片不需要音频（测试时有用）：

```bash
"$PYTHON" "$SCRIPT" build -c "/tmp/cards.json" -o "/tmp/output.apkg" --no-audio
```

## 常见问题

### Q: 剧本/字幕怎么抓到的
- AI 用 **WebFetch 工具**抓取 springfieldspringfield.co.uk 的剧本（走云端代理，国内可直连访问）
- **本机直连（curl/Python）会被网络拦截**（DNS 污染跳转到百度），所以抓取必须由 WebFetch 完成，不要用脚本直连
- 若某剧 springfield 没有，用 WebSearch 找备选源（subslikescript.com、tvfanatic 等）再 WebFetch

### Q: 词典 API 在国内连不上
- 构建时统一用 `--skip-dict`，所有单词发音都走 TTS（en-US-JennyNeural），不需要词典 API
- AI 直接用自身知识补全音标和释义，不依赖外部 API
- 音频质量足够日常记忆使用

### Q: TTS 生成失败
- 检查网络连接（edge-tts 需要访问微软服务）
- 确认 edge-tts 已正确安装
- 可以用 `--no-audio` 先生成无音频版本

### Q: 直推 Anki 失败（push_to_anki.py 报 "AnkiConnect 未连接"）
按顺序排查：
1. **Anki 是否在运行**？任务管理器应有 `Anki.exe` 进程。
2. **是否装了 AnkiConnect**？插件目录 `C:\Users\cmy\AppData\Roaming\Anki2\addons21\2055492155\` 下应有 `__init__.py` 等文件（没有就用 `git clone https://github.com/FooSoft/ankiconnect` 把 `plugin/` 整目录复制进去）。
3. **装插件后是否重启过 Anki**？插件只在启动时加载，必须彻底关闭再重开。
4. **端口 8765 是否被占用**？`python -c "import socket;s=socket.socket();s.connect(('127.0.0.1',8765))"` 不通就是没起来。
5. 以上都不行 → 退化为生成 .apkg 文件交付，让用户手动导入。

### Q: 推送后卡片出现在"系统默认"牌组而不是正确牌组
这是本机 Anki 版本忽略 `addNote` 的 `deckName` 所致，属已知行为；`push_to_anki.py` 已用 `changeDeck` 在推送后把卡片移动到正确牌组。若仍错位，多半是 AnkiConnect 版本差异，按上文「关键坑」第 1 点处理即可。

### Q: 双语字幕中混入中文
剧本多为纯英文，若有中文：AI 在准备 cards.json 时 `example` 字段只放英文原句，`example_translation` 放中文翻译，不要把中文混进英文例句。

### Q: 重复卡片
AI 在准备 cards.json 时应去重：
- 同一单词只保留一张卡片
- 如果同一单词在剧本中出现多次，选最典型的一句作为例句

### Q: 想换剧名但 shows.json 里没有
- 先 WebSearch `"剧名 season X episode Y script/transcript"` 确认 springfield 上的 slug
- 或直接告诉我英文名，AI 按 kebab-case 推导（如 "The Bear" → `the-bear`）
- 也可以把新剧名→slug 补进 `scripts/shows.json` 方便以后复用

## 测试

改完 `scripts/` 下任何脚本，跑一次 smoke test 验证没回归（无需 Anki、无需 TTS 网络）：

```bash
"${PYTHON:-C:/Users/cmy/.workbuddy/binaries/python/envs/default/Scripts/python.exe}" \
    tests/smoke.py
```

覆盖 3 个用例：build_apkg 出牌组、push 流程命中 createDeck/addNote/changeDeck、ensure_model 同步已有模型（修过的回归 bug）。

## 快速参考

```bash
PYTHON="${PYTHON:-C:/Users/cmy/.workbuddy/binaries/python/envs/default/Scripts/python.exe}"
SCRIPT="$SKILL_DIR/scripts/anki_tv_vocab.py"
PUSH="$SKILL_DIR/scripts/push_to_anki.py"
CSV_SCRIPT="$SKILL_DIR/scripts/csv_to_cards.py"

# === 主流程：用户报集数 → AI 用 WebFetch 抓剧本 → 提取 → 写 cards.json → 直推 Anki ===
# 1) AI 用 WebFetch 抓剧本（见 SKILL 第1步，必须用 WebFetch 工具，不能直连）
# 2) AI 阅读剧本 → 写 cards.json（用 Write 工具）
# 3) 直推 Anki（AnkiConnect 就绪时首选，自动建牌组/模型并附带 TTS 音频）
"$PYTHON" -u "$PUSH" -c cards.json --skip-dict
#   兜底：若 Anki/AnkiConnect 不可用，改生成 apkg 交付
"$PYTHON" -u "$SCRIPT" build -c cards.json -o deck.apkg -d "剧名 SxxExx" --skip-dict

# === 备选：用户已有豆包 CSV ===
"$PYTHON" "$CSV_SCRIPT" -i input.csv -o cards.json -d "剧名 SxxExx"
"$PYTHON" -u "$PUSH" -c cards.json --skip-dict
```
