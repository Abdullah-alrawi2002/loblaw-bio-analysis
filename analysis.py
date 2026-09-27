#!/usr/bin/env python3
"""Parts 2–4: query SQLite, test independent subjects, and export all results."""
from __future__ import annotations

import json
import platform
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from scipy.stats import mannwhitneyu

from load_data import ROOT, DB_PATH, POPULATIONS, LABELS, ensure_database

OUT = ROOT / "outputs"
ALPHA = 0.05
COLORS = {"yes": "#008879", "no": "#c97527"}
COHORT_WHERE = "condition = 'melanoma' AND treatment = 'miraclib' AND sample_type = 'PBMC'"
BASELINE_WHERE = COHORT_WHERE + " AND time_from_treatment_start = 0"


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)


def summary_table(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("""
        SELECT f.sample, f.total_count, f.population, f.count, f.percentage
        FROM sample_frequencies f JOIN populations p USING (population)
        ORDER BY f.sample, p.sort_order
    """, conn)


def cohort_table(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(f"""
        SELECT f.*, m.project, m.subject, m.response, m.time_from_treatment_start
        FROM sample_frequencies f JOIN sample_metadata m USING (sample)
        WHERE {COHORT_WHERE}
        ORDER BY m.subject, m.time_from_treatment_start, f.population
    """, conn)


def baseline_queries(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    """Every count in Part 4 is calculated in SQL, using DISTINCT for subjects."""
    conn.execute("DROP VIEW IF EXISTS baseline_subset")
    conn.execute(f"CREATE TEMP VIEW baseline_subset AS SELECT * FROM sample_metadata WHERE {BASELINE_WHERE}")
    # Group counts must not silently put the same person in two response groups.
    conflicts = conn.execute("""
        SELECT subject FROM baseline_subset GROUP BY subject
        HAVING COUNT(DISTINCT COALESCE(response, 'unknown')) > 1
    """).fetchall()
    if conflicts:
        raise ValueError("Conflicting baseline responses for the same subject")
    return {
        "samples": pd.read_sql_query("SELECT * FROM baseline_subset ORDER BY project, subject, sample", conn),
        "projects": pd.read_sql_query("""
            SELECT p.project, COUNT(b.sample) AS sample_count
            FROM projects p LEFT JOIN baseline_subset b USING (project)
            GROUP BY p.project ORDER BY p.project
        """, conn),
        "response": pd.read_sql_query("""
            SELECT COALESCE(response, 'unknown') AS response,
                   COUNT(DISTINCT subject) AS subject_count
            FROM baseline_subset GROUP BY response ORDER BY response
        """, conn),
        "sex": pd.read_sql_query("""
            SELECT COALESCE(sex, 'unknown') AS sex, COUNT(DISTINCT subject) AS subject_count
            FROM baseline_subset GROUP BY sex ORDER BY sex
        """, conn),
        "missing": pd.read_sql_query("""
            SELECT 'response' AS field,
                   COUNT(DISTINCT CASE WHEN response IS NULL THEN subject END) AS missing_subjects
            FROM baseline_subset
            UNION ALL
            SELECT 'sex', COUNT(DISTINCT CASE WHEN sex IS NULL THEN subject END)
            FROM baseline_subset
        """, conn),
    }


def holm_adjust(p_values: np.ndarray) -> np.ndarray:
    """Holm step-down FWER correction; valid for arbitrary dependence of tests."""
    p_values = np.asarray(p_values, dtype=float)
    if p_values.ndim != 1 or not np.isfinite(p_values).all() or ((p_values < 0) | (p_values > 1)).any():
        raise ValueError("Holm correction requires a vector of valid p-values")
    order = np.argsort(p_values, kind="stable")
    adjusted = np.empty_like(p_values)
    adjusted[order] = np.minimum(1, np.maximum.accumulate(p_values[order] * np.arange(len(p_values), 0, -1)))
    return adjusted


def independent_values(cohort: pd.DataFrame, day: int | None = None) -> pd.DataFrame:
    d = cohort.loc[cohort.response.isin(["yes", "no"]) & cohort.percentage.notna()].copy()
    if day is not None:
        d = d.loc[d.time_from_treatment_start == day]
    if (d.groupby("subject").response.nunique() > 1).any():
        raise ValueError("One subject has conflicting responses within the comparison cohort")
    # Equal weight to each person's mean of sample percentages, not pooled raw counts.
    return d.groupby(["subject", "response", "population"], as_index=False).agg(
        percentage=("percentage", "mean"), sample_count=("sample", "nunique"))


def compare(values: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for population in POPULATIONS:
        d = values.loc[values.population == population]
        yes = d.loc[d.response == "yes", "percentage"].to_numpy()
        no = d.loc[d.response == "no", "percentage"].to_numpy()
        if min(len(yes), len(no)) < 2:
            raise ValueError(f"{population}: need at least two independent subjects in each response group")
        test = mannwhitneyu(yes, no, alternative="two-sided", method="asymptotic", use_continuity=True)
        rows.append({
            "population": population,
            "n_responders": len(yes), "n_nonresponders": len(no),
            "median_responders_pct": float(np.median(yes)),
            "median_nonresponders_pct": float(np.median(no)),
            "q1_responders_pct": float(np.percentile(yes, 25)),
            "q3_responders_pct": float(np.percentile(yes, 75)),
            "q1_nonresponders_pct": float(np.percentile(no, 25)),
            "q3_nonresponders_pct": float(np.percentile(no, 75)),
            "median_difference_pp": float(np.median(yes) - np.median(no)),
            "u_statistic_responders": float(test.statistic),
            "p_value": float(test.pvalue),
            "rank_biserial": float(2 * test.statistic / (len(yes) * len(no)) - 1),
        })
    result = pd.DataFrame(rows)
    result["p_holm"] = holm_adjust(result.p_value.to_numpy())
    result["significant_holm_0_05"] = result.p_holm <= ALPHA
    return result


def boxplot(values: pd.DataFrame, output: Path, title: str, unit: str,
            statistics: pd.DataFrame | None = None) -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.5))
    for ax, population, label in zip(axes.flat, POPULATIONS, LABELS):
        d = values.loc[values.population == population]
        groups = [d.loc[d.response == r, "percentage"].dropna().to_numpy() for r in ("no", "yes")]
        tick_names = [f"Non-responders\nn={len(groups[0]):,}", f"Responders\nn={len(groups[1]):,}"]
        box_kwargs = dict(patch_artist=True, widths=0.48, whis=1.5,
                          medianprops={"color": "#152d42", "linewidth": 2},
                          flierprops={"markersize": 2, "alpha": 0.3})
        try:
            boxes = ax.boxplot(groups, tick_labels=tick_names, **box_kwargs)
        except TypeError:
            boxes = ax.boxplot(groups, labels=tick_names, **box_kwargs)
        for patch, color in zip(boxes["boxes"], [COLORS["no"], COLORS["yes"]]):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
        ax.set_title(label, fontweight="bold", loc="left")
        ax.set_ylabel("Relative frequency (%)")
        ax.margins(y=0.18)
        ax.grid(axis="y", alpha=0.16)
        ax.set_axisbelow(True)
        if statistics is not None:
            row = statistics.loc[statistics.population == population].iloc[0]
            ax.text(0.97, 0.97, f"Holm p = {row.p_holm:.4f}", transform=ax.transAxes,
                    ha="right", va="top", fontsize=9)
    axes.flat[-1].axis("off")
    axes.flat[-1].text(0, 0.85, f"Melanoma · miraclib · PBMC\n\n{unit}\n\nBoxes: 25th–75th percentiles\nLine: median\nWhiskers: within 1.5 × IQR\nPoints: observations beyond whiskers",
                      transform=axes.flat[-1].transAxes, va="top", linespacing=1.6)
    fig.suptitle(title, fontsize=17, fontweight="bold", x=0.06, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(output, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def markdown_table(frame: pd.DataFrame, columns: list[tuple[str, str, str]]) -> str:
    lines = ["| " + " | ".join(label for _, label, _ in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(format(row[key], fmt) if fmt else str(row[key]) for key, _, fmt in columns) + " |")
    return "\n".join(lines)


def write_report(audit: dict, stats: dict, subset: dict) -> str:
    primary = stats["mean"].copy()
    for group in ("responders", "nonresponders"):
        primary[f"{group}_summary"] = [
            f"{m:.3f} ({q1:.3f}–{q3:.3f})" for m, q1, q3 in zip(
                primary[f"median_{group}_pct"], primary[f"q1_{group}_pct"], primary[f"q3_{group}_pct"])]
    table = markdown_table(primary, [
        ("population", "Population", ""), ("n_responders", "n yes", "d"), ("n_nonresponders", "n no", "d"),
        ("responders_summary", "Responder median % (IQR)", ""),
        ("nonresponders_summary", "Non-responder median % (IQR)", ""),
        ("u_statistic_responders", "U (responders)", ".0f"), ("p_value", "Raw p", ".6f"),
        ("p_holm", "Holm p", ".6f"), ("rank_biserial", "Rank-biserial effect", ".4f")])
    missing = dict(subset["missing"][["field", "missing_subjects"]].values)
    baseline_table = markdown_table(stats["baseline"], [
        ("population", "Population", ""), ("u_statistic_responders", "U", ".0f"),
        ("p_value", "Raw p", ".6f"), ("p_holm", "Holm p", ".6f")])
    cd4 = primary.loc[primary.population == "cd4_t_cell"].iloc[0]
    significant = primary.loc[primary.significant_holm_0_05, "population"].tolist()
    finding = ("No cell population meets the reporting threshold of Holm-adjusted p ≤ 0.05."
               if not significant else "Populations with Holm-adjusted p ≤ 0.05: " + ", ".join(significant) + ".")
    return f"""# Loblaw Bio: immune cell analysis

## Findings for Bob Loblaw and Barry Zuckerkorn

{finding} The primary comparison uses each subject's average relative frequency across the available visits. In this file every eligible subject has the same three visits (days 0, 7, and 14). CD4 T cells have raw p={cd4.p_value:.6f}, but adjusted p={cd4.p_holm:.6f}; the median difference is {cd4.median_difference_pp:.3f} percentage points. This is exploratory evidence, not a validated predictor of response or proof that miraclib causes a change.

## Part 1: data and database

The input contains **{audit['samples']:,} samples, {audit['subjects']:,} subjects, {audit['projects']} projects, and {audit['measurements']:,} cell counts**. Samples are unique and all five counts are non-negative integers. There are {audit['missing_response_samples']:,} missing response labels, all in healthy, untreated records; they remain SQL NULL, never non-response. There are {audit['zero_total_samples']} zero-total samples in this file.

`schema.sql` separates projects, subjects, project enrollments, samples, populations, and cell counts. Enrollment attributes (age, condition, treatment, response) are stored once per project/subject; sex is stored on subjects. Composite enrollment foreign keys connect samples to their project and subject. Counts use a `(sample, population)` primary key. Database checks, indexes, and source SHA-256 metadata support integrity and reproducibility. The loader validates consistency, then replaces the database atomically; rerunning never appends duplicates.

Source SHA-256: `{audit['source_sha256']}`.

## Part 2: per-sample frequencies

For each sample, `total_count = b_cell + cd8_t_cell + cd4_t_cell + nk_cell + monocyte`; `percentage = 100 × count / total_count`. The denominator is these five measured populations, not necessarily every cell in the biological specimen. `outputs/sample_frequencies.csv` has **{audit['summary_rows']:,} rows** and exactly `sample, total_count, population, count, percentage`. Values are calculated before rounding. A zero total would yield a blank/NULL percentage and be excluded from inference, not assigned a fabricated zero percentage.

## Part 3: treatment-response comparison

The melanoma/miraclib/PBMC filter yields **{audit['cohort_samples']:,} samples from {audit['cohort_subjects']:,} subjects**: {audit['responder_subjects']} responders ({audit['responder_samples']} samples) and {audit['nonresponder_subjects']} non-responders ({audit['nonresponder_samples']} samples). Unknown-response samples excluded from comparison: {audit['cohort_unknown_response_samples']}.

**Response handling.** Responders have `response = "yes"` and non-responders `response = "no"`. A blank response is stored as SQL NULL and excluded from the comparison; it is never recoded as non-response. Any other value (for example `maybe`) is rejected by `load_data.py` with a validation error, and the existing database is left unchanged.

**Unit of analysis.** Each subject has repeated samples (days 0, 7, and 14), so visits are not independent. The primary analysis averages sample percentages within each subject and cell population, giving each subject equal weight and one value per population.

**Test choice and assumptions.** A two-sided Mann–Whitney U test (asymptotic, tie correction, continuity correction) compares the two independent groups of subjects. It was chosen because percentages are bounded, compositional, and not assumed to be normally distributed, and because it is robust to outliers. Its assumptions are independent observations within and between groups (satisfied by one value per subject; each subject has a single response label) and an ordinal or continuous outcome. The test compares rank distributions (stochastic dominance); it is a test of medians only if the two distributions have the same shape, so medians and IQRs are reported as descriptive summaries. U is oriented to responders.

**Significance and multiple comparisons.** The significance threshold is family-wise α = 0.05. **Holm correction across the five populations** controls family-wise error without requiring independence among the compositional cell populations; a population is significant when its Holm-adjusted p ≤ 0.05. Effect size is the rank-biserial correlation `2U/(n_yes × n_no) − 1` (range −1 to 1; positive values indicate higher responder ranks). All five populations were selected by the task, without outcome-based feature selection.

{table}

`outputs/sample_boxplots.png` shows the requested raw sample distributions; repeated samples are descriptive only. `outputs/subject_mean_boxplots.png` shows the independent subject-level observations used in the primary test. The dashboard offers both views and labels their unit of analysis.

**Baseline sensitivity analysis.** Day 0 uses one observation per subject in this file; none of the five baseline comparisons is significant after Holm correction. This avoids post-treatment information when assessing potential baseline associations.

{baseline_table}

Day 7 and day 14 results are also exported for exploration, with a separate five-test Holm family per visit. Those additional views are not independently confirmed findings and are not corrected jointly across all time views. Main conclusions above use the primary five-test family. No timepoint was selected because it had a favorable p-value.

## Part 4: baseline subset queried in SQLite

Filter: melanoma, PBMC, miraclib, and `time_from_treatment_start = 0`. There are **{len(subset['samples']):,} samples from {subset['samples'].subject.nunique():,} distinct subjects**. The drug **quintazide** does not occur in the supplied dataset; it is not included in this requested miraclib subset. The observed treatments are miraclib, phauximab, and none.

{markdown_table(subset['projects'], [('project','Project',''),('sample_count','Baseline samples','d')])}

{markdown_table(subset['response'], [('response','Response',''),('subject_count','Distinct subjects','d')])}

{markdown_table(subset['sex'], [('sex','Recorded sex',''),('subject_count','Distinct subjects','d')])}

Here F means female and M means male as encoded in the source. Project totals count samples; response and sex totals use `COUNT(DISTINCT subject)`. `queries.sql` contains the queries, and `outputs/baseline_samples.csv` lists every matching sample with its project, subject, age, sex, treatment, response, sample type, and time point. Baseline describes pretreatment composition; this query alone does not estimate early treatment effects.

**Missing values in this subset.** Subjects with a missing response: {missing['response']}. Subjects with a missing sex: {missing['sex']}. Missing values would be reported as `unknown` rather than dropped or merged into another group (`outputs/baseline_missing.csv`).

## Interpretation and limits

The averages combine baseline and post-treatment information and therefore cannot establish prospective predictive performance. Associations are unadjusted for age, sex, project, and other possible confounders; matched visit schedules remove unequal follow-up counts in this file, but do not eliminate confounding. Percentages are compositional and cannot distinguish an absolute cell increase from a decrease in another population. No randomized treatment-effect estimate, causal claim, or out-of-sample prediction model is fitted. Failure to detect significance is not evidence of equivalence. A prediction claim would require baseline-only modeling with subject-level held-out validation; a longitudinal treatment-effect question requires an explicit repeated-measures model and an appropriate comparator.

## Reproduction

From the repository root with Python 3.11 or later (Python 3.12 recommended), for example in GitHub Codespaces:

```bash
make setup      # install pinned dependencies
make pipeline   # CSV -> SQLite -> Parts 2-4 outputs, REPORT.md, dist/index.html
make dashboard  # serve the dashboard from that database at http://localhost:8501
```

Alternatively open `dist/index.html` directly for the self-contained snapshot. Run `make test` for integrity and statistical checks.

Tested runtime: Python {platform.python_version()}, pandas {pd.__version__}, NumPy {np.__version__}, SciPy {scipy.__version__}, Matplotlib {matplotlib.__version__}.

Method references: [SciPy Mann–Whitney U](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html); [Holm (1979), A Simple Sequentially Rejective Multiple Test Procedure](https://www.jstor.org/stable/4615733).
"""


def run_analysis(db_path: Path = DB_PATH, output_dir: Path = OUT) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        summary = summary_table(conn)
        cohort = cohort_table(conn)
        subset = baseline_queries(conn)
        metadata = pd.read_sql_query("SELECT * FROM sample_metadata ORDER BY sample", conn)
        counts = pd.read_sql_query("SELECT * FROM cell_counts", conn).pivot(index="sample", columns="population", values="count")
        raw = metadata.merge(counts.reset_index(), on="sample", validate="one_to_one")
        source_sha = conn.execute("SELECT value FROM load_metadata WHERE key='source_sha256'").fetchone()[0]
    summary.to_csv(output_dir / "sample_frequencies.csv", index=False)
    cohort.to_csv(output_dir / "cohort_frequencies.csv", index=False)
    for name, frame in subset.items():
        frame.to_csv(output_dir / f"baseline_{name}.csv", index=False)
    values, statistics = {}, {}
    for mode, day in (("mean", None), ("baseline", 0), ("day7", 7), ("day14", 14)):
        values[mode] = independent_values(cohort, day)
        statistics[mode] = compare(values[mode])
        values[mode].to_csv(output_dir / f"subject_frequencies_{mode}.csv", index=False)
        statistics[mode].to_csv(output_dir / f"statistics_{mode}.csv", index=False)
    known = cohort.loc[cohort.response.isin(["yes", "no"])]
    per_sample = cohort.drop_duplicates("sample")
    audit = {
        "samples": len(metadata), "subjects": metadata.subject.nunique(),
        "projects": metadata.project.nunique(), "measurements": len(summary),
        "summary_rows": len(summary), "source_sha256": source_sha,
        "missing_response_samples": int(metadata.response.isna().sum()),
        "zero_total_samples": int(summary.loc[summary.total_count == 0, "sample"].nunique()),
        "cohort_samples": per_sample.shape[0], "cohort_subjects": cohort.subject.nunique(),
        "responder_samples": int((per_sample.response == "yes").sum()),
        "nonresponder_samples": int((per_sample.response == "no").sum()),
        "responder_subjects": cohort.loc[cohort.response == "yes", "subject"].nunique(),
        "nonresponder_subjects": cohort.loc[cohort.response == "no", "subject"].nunique(),
        "cohort_unknown_response_samples": int(per_sample.response.isna().sum()),
    }
    audit = {k: int(v) if isinstance(v, (int, np.integer)) else v for k, v in audit.items()}
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    boxplot(known, output_dir / "sample_boxplots.png", "Cell frequencies by response · all samples", "Unit: sample; 3 visits per subject\nDescriptive view; observations are correlated")
    boxplot(values["mean"], output_dir / "subject_mean_boxplots.png", "Cell frequencies by response · subject averages", "Unit: subject; mean of days 0, 7, 14\nPrimary independent-subject analysis", statistics["mean"])
    boxplot(values["baseline"], output_dir / "baseline_boxplots.png", "Cell frequencies by response · baseline", "Unit: subject at day 0\nExploratory sensitivity analysis", statistics["baseline"])
    report = write_report(audit, statistics, subset)
    (ROOT / "REPORT.md").write_text(report, encoding="utf-8")
    # Compact rows keep the standalone browser artifact small; no CDN requests.
    columns = ["sample", "project", "subject", "condition", "age", "sex", "treatment", "response", "sample_type", "time_from_treatment_start", *POPULATIONS]
    raw = raw[columns].astype(object).where(pd.notna(raw[columns]), None)
    payload = {"columns": columns, "rows": raw.values.tolist(), "populations": list(POPULATIONS),
               "labels": dict(zip(POPULATIONS, LABELS)), "audit": audit,
               "statistics": {k: json.loads(v.to_json(orient="records", double_precision=15)) for k, v in statistics.items()},
               "baseline": {k: json.loads(v.to_json(orient="records")) for k, v in subset.items() if k != "samples"}}
    (output_dir / "dashboard_data.json").write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(json.dumps(audit, indent=2))
    print(statistics["mean"][["population", "u_statistic_responders", "p_value", "p_holm"]].to_string(index=False))
    return payload


if __name__ == "__main__":
    ensure_database()
    run_analysis()
