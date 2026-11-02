# 示例项目:诊断试验准确度分析(clinical-diagnostics)

一个**模拟的**诊断准确度研究数据集,用于演示本工作台的完整医学分析闭环:
探索数据 → 计算 2×2 诊断指标(含 95% CI)→ ROC 曲线与最佳截断 → 可溯源报告。

> ⚠️ 数据为程序模拟(`seed=2026`,n=200),仅用于演示与教学,不代表任何真实
> 器械或人群的性能。

## 数据

`data/diagnostic_test.csv` — 每行一位患者:

| 列 | 含义 |
|---|---|
| `patient_id` | 模拟编号 P001–P200 |
| `age`, `sex` | 基线协变量 |
| `gold_standard` | 金标准诊断(1=患病,0=健康),患病率约 0.41 |
| `test_score` | 指标试验连续评分,0–1(模拟:患病组均值≈0.72,健康组≈0.45,同方差 0.13) |

在截断 0.5 处的约定 2×2(供核对):TP=79 FP=45 TN=72 FN=4
→ 灵敏度≈0.952,特异度≈0.615。你的数字若不同,先检查截断方向。

## 建议分析(`analyze.py`)

```bash
python analyze.py            # 需要 numpy/matplotlib(或让智能体用 stdlib 重算)
```

流程:逐截断扫描 → Youden 指数选最佳点 → ROC/AUC(bootstrap CI)→
`roc_curve.png` → `report.md`(STARD 风格,每个数字均可溯源到代码)。

## 工作台提示词

直接点开新会话中的「示例项目:诊断试验数据分析」卡片,或发送:

> 分析 clinical-diagnostics/data/diagnostic_test.csv:计算候选截断下的
> 灵敏度/特异度/PPV/NPV/似然比及 95% CI,用 Youden 指数选择最佳截断,
> 绘制 ROC 曲线保存为 roc_curve.png,并写 report.md 报告结论。

## 溯源

`provenance.jsonl` 记录本数据集的生成参数(seed、分布、患病率),符合
工作台的"每个产物可复现"原则。
