<div align="center">

# 医学智能体桌面工作台 (MedAgent Workbench)

**本地优先、模型无关的医学 AI 智能体研究工作台 — Windows / macOS / Linux**

基于开源项目 [Open Science Desktop](https://github.com/ai4s-research/open-science)(MIT)重构的医学领域版本。

</div>

---

## 这是什么

一个面向医学科研场景的桌面智能体工作台:临床证据检索与分级、诊断试验统计、
病例报告写作、文献综述,全部由本地运行的智能体完成,每个产物(图表、报告、
数据)可溯源、可复现。

| 能力 | 说明 |
|---|---|
| 🏥 医学连接器 | PubMed 摘要、biomcp(临床试验/ClinVar)、openFDA(药物/器械)、GEO 表达数据,一键启用 |
| 🧠 医学智能体技能 | 临床证据(PICO/CEBM/GRADE)、医学统计(诊断试验/样本量/生存分析)、CARE 病例报告、医学图表(ROC/森林图/KM 曲线) |
| 📋 报告规范 | 智能体自动按 STROBE / CONSORT / CARE / STARD / PRISMA 检查报告合规性 |
| 🔬 示例项目 | 内置 200 例模拟诊断试验数据集,一键跑通「数据 → 统计 → ROC 曲线 → 报告」全流程 |
| 🔒 本地优先 | 工作区、会话、溯源日志全部留在本机;模型可接任意 OpenAI 兼容接口 |
| 🌐 中文优先 | 简体中文为第一语言,另附 6 种语言 |

## 快速开始

```bash
# 依赖:Node 20+、pnpm 9、Rust(桌面包需要)
pnpm install

# 浏览器开发模式(需另行启动 opencode serve,或在桌面模式下自动拉起)
pnpm --filter @ai4s/desktop dev

# 完整桌面应用
pnpm --filter @ai4s/desktop tauri dev
```

配置模型:设置 → 提供商 → 添加自定义 OpenAI 兼容接口(如 GLM/DeepSeek),
填入 baseURL 与 API key 即可。

## 与上游的主要差异

- 品牌、图标、主题全面医学化(青绿色系)
- 连接器列表聚焦医学/生物(移除材料、经济、气象等)
- 新增 4 个医学技能 + 3 个补齐的文献技能,审稿智能体增加报告规范检查
- 4 个一键工作流与示例项目替换为医学版
- 移除无引用的 `xlsx` 直链依赖(sheetjs CDN 不稳定会导致安装卡住)
- 界面文案以简体中文为先,7 语言同步维护

上游语言版本(保留存档):[简体中文](./README.upstream-zh.md) · [日本語](./README.upstream-ja.md) · [Español](./README.upstream-es.md) · [Deutsch](./README.upstream-de.md) · [Français](./README.upstream-fr.md) · [한국어](./README.upstream-ko.md)

## 架构

Tauri 2 + React + TypeScript + Rust。OpenCode 作为智能体运行时
(单文件 sidecar,HTTP + SSE),SQLite + JSONL 溯源,技能/MCP/模型全部可插拔。
架构细节见 [AGENTS.md](./AGENTS.md) 与 [docs/](./docs)。

## 许可

MIT(继承自上游)。
