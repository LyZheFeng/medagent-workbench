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
| 🧠 医学技能 | 临床证据(PICO / CEBM / GRADE)、医学统计(诊断试验 / 样本量 / 生存分析)、医学图表(ROC / 森林图 / KM / Bland–Altman / 2×2 表 / 流程图)、CARE 病例报告、文献综述、引用核查、论文→报告 | 提示词级;`diag_stats.py`、`stats_power.py`、`med_figures.py`、`citation_check.py` 为确定性脚本;Windows 安装包内置 Python 运行时 |
| 🪪 去标识 | 病例报告 / 临床文本:姓名、住院号、身份证、电话、邮箱、地址、机构换成稳定令牌,日期整体偏移,≥90 岁归组 | `deidentify.py` 确定性脚本,输出 review 卡片;图像与 DICOM 不在范围内 |
| 📋 报告规范 | 按 STROBE / CONSORT / CARE / STARD / PRISMA 逐条检查稿件**是否提到**必需项(伦理、知情同意、注册号、置信区间、缺失数据、去标识、流程、不良事件);每条结论标出官方条目号与清单版本,可再要求条目落在 Methods/Results 段 | `check_report.py` 确定性 gate,输出 review 卡片;存在性检查,不是合规结论 |
| 📊 诊断统计 | 灵敏度 / 特异度 / PPV / NPV + Wilson 95% CI、ROC / AUC(bootstrap CI)、Youden 最佳截断 | `analyze.py`、`diag_stats.py`、`med_figures.py` 已实跑验证 |
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

配置模型:首次启动会有一个向导(供应商 → 密钥 → 默认模型 → 一条 30 秒测试消息)。
供应商列表里有「自定义端点」:填名称、baseURL、API 风格与模型即可(模型可留空,保存
密钥时向端点探测);key 和其他供应商一样存进系统凭据库。随时也可以在 设置 → 智能体
中修改。

## 与上游的主要差异

- 品牌、图标、主题医学化(青绿色系);简体中文为第一语言
- 连接器聚焦医学 / 生物(移除材料、经济、气象、水文等 5 个),新增 openFDA、PubMed
- 新增医学与文献技能,其中诊断统计、报告规范检查、医学图表、去标识与引用核查带确定性脚本;
  审稿智能体增加医学路由
- 4 个一键工作流改为医学场景,内置示例换成模拟诊断试验数据
- **App 身份独立**:bundle identifier 为 `com.medagent.workbench`,版本线从 0.8.0 起,
  应用内更新检查指向本仓库 —— 不会再被上游版本"更新"覆盖(旧版数据目录首次启动时自动迁移)
- **API key 不写进配置文件**:自定义端点 / 内置供应商 / 连接器的 key 都存进系统凭据库
  (Windows 凭据管理器 / macOS 钥匙串 / Linux libsecret),`opencode.json` 只保留
  `{env:MEDAGENT_KEY_…}` 引用,启动时注入;旧配置(含 OpenCode 自己的 `auth.json`)里
  已有的明文 key 在首次启动时自动迁移
- **合规声明在应用内**:首次启动一次性提示,`设置 → 关于` 常驻,导出的 Markdown
  页脚中英双写 —— 三处同一份文案
- **首次启动向导**:选供应商 → 填密钥 → 选默认模型 → 跑一条 30 秒测试消息;密钥仍走
  系统凭据库(配置文件只留 `{env:MEDAGENT_KEY_…}`),向导结束处直接引用
  `设置 → 隐私` 的同一句话。供应商列表里也能加「自定义端点」(名称 / baseURL / API
  风格 / 模型,模型留空则保存密钥时探测);已有供应商的旧安装不会看到向导
- **Windows 安装包内置医学 Python 运行时**:CPython 3.12 + matplotlib / numpy /
  openpyxl / python-docx / python-pptx / pypdf / pdfplumber 随包提供,OpenCode
  的 `python` 指向它。安装后只需配置模型 key,6 个确定性脚本、图表、Word/Excel
  基础能力即可使用(Excel 公式重算与 Office→PDF 仍需 LibreOffice)
- **移除内置 OpenCode Zen 免费模型**:运行时仍会把它报给应用,但 provider 列表
  入口统一过滤;首次启动、设置和模型选择器都不再出现,用户必须配置自己的模型 API
- 移除无引用的 `xlsx` 直链依赖;`.gitattributes` 固定换行为 LF

## 尚未完成(不隐瞒)

- 报告规范检查只判断"文本是否提到"某项,不判断写法是否合规;也不要把它当成投稿前的合规结论
- 去标识脚本只处理文本:图像、DICOM 元数据,以及没有标签可循的姓名/罕见职业仍需人工核对;它是第一遍,不是匿名保证
- 医学图表已覆盖 ROC / 森林图 / KM / Bland–Altman / 2×2 表与 STROBE·PRISMA·CONSORT 流程图,均由 `med_figures.py` 生成(流程图先校验计数,不成立拒绝出图);2×2 表一次画一张,多截断点比较用 `diag_stats.py`
- 引用核查脚本(`citation_check.py`)只核验 DOI/PMID 是否存在、PubMed 是否记录了撤稿 / 更正 / 关注声明:
  没有 PMID 时输出"撤稿状态未知"而不是"干净",也不判断文献是否支持引用它的论点,不替代全文阅读
- 安装包内置的 Python 只覆盖医学脚本用到的包(清单见 `scripts/dev/python-runtime-requirements.txt`);
  Excel 公式重算 / Office→PDF 仍需 LibreOffice;源码构建需先运行
  `scripts/dev/build-python-runtime.mjs`
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