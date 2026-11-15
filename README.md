<div align="center">

# 医学智能体桌面工作台 (MedAgent Workbench)

**本地优先、模型无关的医学科研 AI 智能体工作台 — Windows / macOS / Linux**

基于开源项目 [Open Science Desktop](https://github.com/ai4s-research/open-science)(MIT)的医学领域分叉。

</div>

---

## 这是什么

一个面向**医学科研场景**的桌面智能体工作台:临床证据检索与分级、诊断试验统计、
病例报告与论文写作、文献综述,由本机运行的智能体完成;产物(图表、报告、数据)
随附溯源记录。

> **定位**:科研与教学工具,**不是医疗器械**,不提供诊疗建议,也不用于个体患者的
> 诊断或治疗决策。所有分析结论需由具备资质的研究者复核。

## 能力(并标注实现层次)

| 能力 | 说明 | 实现层次 |
|---|---|---|
| 🏥 医学连接器 | PubMed / 文献检索、biomcp(临床试验 / ClinVar)、GEO、openFDA,一键装入隔离环境 | 现成 MCP 服务器,接入即用 |
| 🧠 医学技能 | 临床证据(PICO / CEBM / GRADE)、医学统计(诊断试验 / 样本量 / 生存分析)、医学图表(ROC / 森林图 / KM)、CARE 病例报告、文献综述、引用核查、论文→报告 | **提示词级**;`diag_stats.py` 为确定性脚本 |
| 📋 报告规范 | 按 STROBE / CONSORT / CARE / STARD / PRISMA 逐条检查稿件**是否提到**必需项(伦理、知情同意、注册号、置信区间、缺失数据、去标识、流程、不良事件) | `check_report.py` 确定性 gate,输出 review 卡片 |
| 📊 诊断统计 | 灵敏度 / 特异度 / PPV / NPV + Wilson 95% CI、ROC / AUC(bootstrap CI)、Youden 最佳截断 | `analyze.py`、`diag_stats.py` 已实跑验证 |
| 🔬 示例项目 | 200 例**模拟**诊断试验数据,跑通「数据 → 统计 → ROC → 报告」 | 可一键安装并实跑 |
| 🔒 本地优先 | 工作区、会话、溯源日志留在本机;模型可接任意 OpenAI 兼容接口 | —— |
| 🌐 中文优先 | 简体中文为第一语言,另附 6 种语言 | —— |

**"本地优先"的边界**:工作区文件、会话记录、溯源日志都不出本机;但**模型推理经你
配置的接口出网** —— 发送的内容包括对话、被读取的文件片段,以及(启用浏览器或
Computer Use 时的)截图。涉及患者数据时请自行评估合规要求,优先使用本地模型。

## 快速开始

```bash
# 依赖:Node 20+、pnpm 9、Rust(桌面包需要)
pnpm install

# 浏览器开发模式(需另行启动 opencode serve,或在桌面模式下自动拉起)
pnpm --filter @ai4s/desktop dev

# 完整桌面应用
pnpm --filter @ai4s/desktop tauri dev
```

配置模型:设置 → 提供商 → 添加自定义 OpenAI 兼容接口(如 GLM / DeepSeek),
填入 baseURL 与 API key 即可。

## 与上游的主要差异

- 品牌、图标、主题医学化(青绿色系);简体中文为第一语言
- 连接器聚焦医学 / 生物(移除材料、经济、气象、水文等 5 个),新增 openFDA、PubMed
- 新增 8 个技能(5 医学 + 3 文献),其中 2 个带确定性脚本(诊断统计、报告规范检查);
  审稿智能体增加医学路由
- 4 个一键工作流改为医学场景,内置示例换成模拟诊断试验数据
- **App 身份独立**:bundle identifier 为 `com.medagent.workbench`,版本线从 0.8.0 起,
  应用内更新检查指向本仓库 —— 不会再被上游版本"更新"覆盖(旧版数据目录首次启动时自动迁移)
- 移除无引用的 `xlsx` 直链依赖;`.gitattributes` 固定换行为 LF

## 尚未完成(不隐瞒)

- 报告规范检查只判断"文本是否提到"某项,不判断写法是否合规;也不要把它当成投稿前的合规结论
- 医学图表(ROC / 森林图 / KM)由模型按技能说明生成,尚无脚本化图表生成器
- 引用核查(`citation-reviewer`)目前是流程说明,没有确定性脚本
- 诊断统计的**似然比只给点估计**,还没有 95% CI
- macOS / Linux 安装包在本分支尚未验证;已发布的只有 Windows 版
- 界面文案 7 语言同步维护,但除简体中文与英文外,其余语言的医学措辞未经母语者校对

上游语言版本(保留存档):[简体中文](./README.upstream-zh.md) · [日本語](./README.upstream-ja.md) · [Español](./README.upstream-es.md) · [Deutsch](./README.upstream-de.md) · [Français](./README.upstream-fr.md) · [한국어](./README.upstream-ko.md)

## 架构

Tauri 2 + React + TypeScript + Rust。OpenCode 作为智能体运行时
(单文件 sidecar,HTTP + SSE),SQLite + JSONL 溯源,技能 / MCP / 模型全部可插拔。
架构细节见 [AGENTS.md](./AGENTS.md) 与 [docs/](./docs)。

## 许可

MIT,继承自上游 [Open Science Desktop](https://github.com/ai4s-research/open-science)。
衍生关系与版权声明见 [NOTICE](./NOTICE)。