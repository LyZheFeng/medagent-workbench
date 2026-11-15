import { useTranslation } from "react-i18next";
import { ChevronRight, FileSearch, FlaskConical, LineChart, Stethoscope } from "lucide-react";
import { installExample, isTauri } from "@/lib/tauri";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/cn";

export interface WorkflowStarter {
  id: string;
  icon: React.ReactNode;
  /** The instruction sent to the agent, authored per language. Chinese and
   *  English are written by hand; a locale with no text of its own gets the
   *  English one — a machine-translated research prompt (STROBE, Youden, PPV,
   *  likelihood ratio) is worse than an honest English one, and the *display*
   *  copy for every locale is translated separately below.
   *  The card's title/description live in `session:starters.<id>.*`. */
  prompts: { en: string; "zh-Hans": string };
  /** Side effect to run before sending the prompt (e.g. install example files). */
  prepare?: () => Promise<void>;
}

/** The prompt to send for a UI language (i18next's `i18n.language`). */
export function promptForLocale(starter: WorkflowStarter, language: string): string {
  return language.toLowerCase().startsWith("zh") ? starter.prompts["zh-Hans"] : starter.prompts.en;
}

/** One-click full-workflow prompts (P0-1): a single request that carries the
 *  agent through data → code → figure → report, all inside the app. */
export const WORKFLOW_STARTERS: WorkflowStarter[] = [
  {
    id: "demo",
    icon: <FlaskConical size={17} strokeWidth={1.75} />,
    prompts: {
      en:
        "Run a complete diagnostic-accuracy demo analysis end to end: simulate a small " +
        "diagnostic-test dataset in Python (index test result vs gold standard, e.g. 200 patients " +
        "with disease status), compute sensitivity, specificity, PPV, NPV and likelihood ratios " +
        "with 95% confidence intervals, save one publication-quality figure (ROC curve) as " +
        "demo_analysis/figure1.png, and write demo_analysis/report.md summarizing the findings " +
        "following STARD-style reporting — every number in the report must come from the code you " +
        "ran. Keep all files in the workspace.",
      "zh-Hans":
        "端到端跑一个完整的诊断准确性演示分析:用 Python 模拟一个小型诊断试验数据集" +
        "(指标检测结果 vs 金标准,例如 200 名有明确疾病状态的患者),计算灵敏度、特异度、" +
        "PPV、NPV 与似然比(均含 95% 置信区间),画一张达到出版质量的图(ROC 曲线)保存为 " +
        "demo_analysis/figure1.png,并按 STARD 规范撰写 demo_analysis/report.md 总结结论——" +
        "报告里的每个数字都必须来自你实际运行的代码。所有文件都放在工作区内。",
    },
  },
  {
    id: "analyze",
    icon: <LineChart size={17} strokeWidth={1.75} />,
    prompts: {
      en:
        "Analyze the clinical data file I added to the workspace end to end: explore it (cohort " +
        "characteristics, missing data), run the analysis in code (baseline table, outcome " +
        "analysis, at least one figure saved as a PNG), and write report.md with the findings in " +
        "STROBE-aligned structure — every number traced to the code that produced it. Ask me which " +
        "file to use if there is more than one candidate.",
      "zh-Hans":
        "分析我添加到工作区里的临床数据文件:先探索数据(队列特征、缺失情况),再用代码完成分析" +
        "(基线表、结局分析、至少一张 PNG 图),按 STROBE 结构写 report.md,每个数字都要能追溯到" +
        "产出它的代码。如果候选文件不止一个,先问我要用哪个。",
    },
  },
  {
    id: "audit",
    icon: <FileSearch size={17} strokeWidth={1.75} />,
    prompts: {
      en:
        "Use the traceability-review skill to audit the medical report or manuscript in my " +
        "workspace: resolve every citation, flag statistics with no traceable source (sensitivity, " +
        "p-values, hazard ratios, confidence intervals), and check figures against the code that " +
        "generated them. Then run the reporting-guidelines gate for the study design (STROBE for " +
        "observational, CONSORT for trials, CARE for case reports) and report its findings as they " +
        "are. Ask me which document to audit if there is more than one candidate.",
      "zh-Hans":
        "用 traceability-review 技能审查我工作区里的医学报告或稿件:逐条核实引用,标出没有可追溯" +
        "来源的统计量(灵敏度、p 值、风险比、置信区间),并核对图表与生成它的代码是否一致。然后用 " +
        "reporting-guidelines 技能按研究设计跑一次规范检查(观察性研究用 STROBE、试验用 CONSORT、" +
        "病例报告用 CARE),如实报告它给出的结果。如果需要审查的文档不止一个,先问我是哪一个。",
    },
  },
  {
    id: "example-clinical",
    icon: <Stethoscope size={17} strokeWidth={1.75} />,
    prompts: {
      en:
        "Analyze the diagnostic-accuracy dataset at clinical-diagnostics/data/diagnostic_test.csv " +
        "(simulated study: 200 patients, index test score vs gold-standard disease status — see " +
        "clinical-diagnostics/README.md). Compute sensitivity, specificity, PPV, NPV and the " +
        "likelihood ratios, all with 95% confidence intervals, across candidate cutoffs; choose " +
        "an optimal cutoff with Youden's index, plot the ROC curve as " +
        "clinical-diagnostics/roc_curve.png, and write clinical-diagnostics/report.md citing the " +
        "dataset provenance — every number must come from the code you ran.",
      "zh-Hans":
        "分析 clinical-diagnostics/data/diagnostic_test.csv 这个诊断准确性数据集" +
        "(模拟研究:200 名患者,指标检测得分 vs 金标准疾病状态——见 clinical-diagnostics/README.md)。" +
        "计算候选截断下的灵敏度、特异度、PPV、NPV 和似然比,都带 95% 置信区间;用 Youden 指数选出" +
        "最佳截断,把 ROC 曲线画到 clinical-diagnostics/roc_curve.png,并写 " +
        "clinical-diagnostics/report.md,引用数据集来源——每个数字都必须来自你运行的代码。",
    },
    prepare: async () => {
      if (isTauri) await installExample("clinical-diagnostics");
    },
  },
];

/**
 * Empty-session welcome: a quiet, centered composition in the app's paper
 * aesthetic. The conversation is the point, so the copy invites a message
 * first; the starters below are an optional on-ramp, not a dashboard.
 */
export function WorkflowStarters({
  onPick,
  showCards = true,
}: {
  onPick: (prompt: string) => void;
  /** False when the pane is too short for the cards (a stacked split): only
   *  the invitation stays, and nothing makes the welcome scroll. */
  showCards?: boolean;
}) {
  const { t, i18n } = useTranslation(["session", "common"]);
  // Display copy per starter id — t()'s generated key type rejects a dynamic
  // `starters.${id}.title` template, so each card's copy is looked up by id
  // from this literal-keyed map instead.
  const starterCopy: Record<string, { title: string; description: string }> = {
    demo: { title: t("starters.demo.title"), description: t("starters.demo.description") },
    analyze: { title: t("starters.analyze.title"), description: t("starters.analyze.description") },
    audit: { title: t("starters.audit.title"), description: t("starters.audit.description") },
    "example-clinical": {
      title: t("starters.example-clinical.title"),
      description: t("starters.example-clinical.description"),
    },
  };
  return (
    <div className={cn("flex flex-col items-center justify-center", showCards ? "min-h-[62vh]" : "py-6")}>
      <div className="w-full max-w-[500px]">
        <div className="text-center">
          <div className="text-[10.5px] font-medium uppercase tracking-[0.2em] text-muted">
            {t("starters.newSession")}
          </div>
          <h2 className="mt-2.5 font-serif text-[26px] leading-tight text-text">
            {t("starters.heading")}
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            {showCards ? t("starters.subheading") : t("starters.subheadingNoCards")}
          </p>
        </div>

        {showCards && (

        <div className="mt-7 overflow-hidden rounded-card border border-border bg-surface shadow-card">
          {WORKFLOW_STARTERS.map((s) => (
            <button
              key={s.id}
              onClick={() => {
                void (async () => {
                  try {
                    await s.prepare?.();
                  } catch (e) {
                    toast.error(
                      t("starters.error.setup", {
                        message: e instanceof Error ? e.message : String(e),
                      }),
                    );
                    return;
                  }
                  // The instruction follows the UI language: a Chinese card must
                  // not hand the agent an English request (that is how every
                  // answer came back in English).
                  onPick(promptForLocale(s, i18n.language));
                })();
              }}
              className="group flex w-full items-center gap-3.5 border-t border-border px-4 py-3.5 text-left transition-colors first:border-t-0 hover:bg-surface-2"
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-surface-2 text-accent ring-1 ring-border transition-colors group-hover:bg-surface">
                {s.icon}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-medium text-text">
                  {starterCopy[s.id]?.title}
                </span>
                <span className="mt-0.5 block text-xs leading-snug text-muted">
                  {starterCopy[s.id]?.description}
                </span>
              </span>
              <ChevronRight
                size={16}
                className="shrink-0 text-muted/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-muted"
              />
            </button>
          ))}
        </div>
        )}
      </div>
    </div>
  );
}