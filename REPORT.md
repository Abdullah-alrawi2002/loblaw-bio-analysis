# Loblaw Bio: immune cell analysis

## Findings for Bob Loblaw and Barry Zuckerkorn

No cell population meets the reporting threshold of Holm-adjusted p ≤ 0.05. The primary comparison uses each subject's average relative frequency across the available visits. In this file every eligible subject has the same three visits (days 0, 7, and 14). CD4 T cells have raw p=0.012422, but adjusted p=0.062111; the median difference is 0.387 percentage points. This is exploratory evidence, not a validated predictor of response or proof that miraclib causes a change.

## Part 1: data and database

The input contains **10,500 samples, 3,500 subjects, 3 projects, and 52,500 cell counts**. Samples are unique and all five counts are non-negative integers. There are 1,422 missing response labels, all in healthy, untreated records; they remain SQL NULL, never non-response. There are 0 zero-total samples in this file.

`schema.sql` separates projects, subjects, project enrollments, samples, populations, and cell counts. Enrollment attributes (age, condition, treatment, response) are stored once per project/subject; sex is stored on subjects. Composite enrollment foreign keys connect samples to their project and subject. Counts use a `(sample, population)` primary key. Database checks, indexes, and source SHA-256 metadata support integrity and reproducibility. The loader validates consistency, then replaces the database atomically; rerunning never appends duplicates.

Source SHA-256: `011373475d37417d4131d4a06efeb58df89c4adc76451a5efa48a535ed293c82`.

## Part 2: per-sample frequencies

For each sample, `total_count = b_cell + cd8_t_cell + cd4_t_cell + nk_cell + monocyte`; `percentage = 100 × count / total_count`. The denominator is these five measured populations, not necessarily every cell in the biological specimen. `outputs/sample_frequencies.csv` has **52,500 rows** and exactly `sample, total_count, population, count, percentage`. Values are calculated before rounding. A zero total would yield a blank/NULL percentage and be excluded from inference, not assigned a fabricated zero percentage.

## Part 3: treatment-response comparison

The melanoma/miraclib/PBMC filter yields **1,968 samples from 656 subjects**: 331 responders (993 samples) and 325 non-responders (975 samples). Unknown-response samples excluded from comparison: 0.

**Response handling.** Responders have `response = "yes"` and non-responders `response = "no"`. A blank response is stored as SQL NULL and excluded from the comparison; it is never recoded as non-response. Any other value (for example `maybe`) is rejected by `load_data.py` with a validation error, and the existing database is left unchanged.

**Unit of analysis.** Each subject has repeated samples (days 0, 7, and 14), so visits are not independent. The primary analysis averages sample percentages within each subject and cell population, giving each subject equal weight and one value per population.

**Test choice and assumptions.** A two-sided Mann–Whitney U test (asymptotic, tie correction, continuity correction) compares the two independent groups of subjects. It was chosen because percentages are bounded, compositional, and not assumed to be normally distributed, and because it is robust to outliers. Its assumptions are independent observations within and between groups (satisfied by one value per subject; each subject has a single response label) and an ordinal or continuous outcome. The test compares rank distributions (stochastic dominance); it is a test of medians only if the two distributions have the same shape, so medians and IQRs are reported as descriptive summaries. U is oriented to responders.

**Significance and multiple comparisons.** The significance threshold is family-wise α = 0.05. **Holm correction across the five populations** controls family-wise error without requiring independence among the compositional cell populations; a population is significant when its Holm-adjusted p ≤ 0.05. Effect size is the rank-biserial correlation `2U/(n_yes × n_no) − 1` (range −1 to 1; positive values indicate higher responder ranks). All five populations were selected by the task, without outcome-based feature selection.

| Population | n yes | n no | Responder median % (IQR) | Non-responder median % (IQR) | U (responders) | Raw p | Holm p | Rank-biserial effect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b_cell | 331 | 325 | 9.671 (8.578–11.152) | 9.845 (8.656–11.080) | 51499 | 0.345796 | 0.793475 | -0.0425 |
| cd8_t_cell | 331 | 325 | 24.897 (22.965–26.751) | 25.010 (23.265–26.549) | 52591 | 0.622144 | 0.793475 | -0.0222 |
| cd4_t_cell | 331 | 325 | 30.210 (28.405–32.790) | 29.823 (27.850–31.555) | 59855 | 0.012422 | 0.062111 | 0.1128 |
| nk_cell | 331 | 325 | 14.740 (13.328–16.340) | 14.960 (13.784–16.455) | 50081 | 0.126745 | 0.506979 | -0.0689 |
| monocyte | 331 | 325 | 19.795 (17.862–21.753) | 20.277 (18.555–21.468) | 51079 | 0.264492 | 0.793475 | -0.0504 |

`outputs/sample_boxplots.png` shows the requested raw sample distributions; repeated samples are descriptive only. `outputs/subject_mean_boxplots.png` shows the independent subject-level observations used in the primary test. The dashboard offers both views and labels their unit of analysis.

**Baseline sensitivity analysis.** Day 0 uses one observation per subject in this file; none of the five baseline comparisons is significant after Holm correction. This avoids post-treatment information when assessing potential baseline associations.

| Population | U | Raw p | Holm p |
| --- | --- | --- | --- |
| b_cell | 55244 | 0.548541 | 1.000000 |
| cd8_t_cell | 52203 | 0.513956 | 1.000000 |
| cd4_t_cell | 54414 | 0.796450 | 1.000000 |
| nk_cell | 53437 | 0.885328 | 1.000000 |
| monocyte | 50754 | 0.211389 | 1.000000 |

Day 7 and day 14 results are also exported for exploration, with a separate five-test Holm family per visit. Those additional views are not independently confirmed findings and are not corrected jointly across all time views. Main conclusions above use the primary five-test family. No timepoint was selected because it had a favorable p-value.

## Part 4: baseline subset queried in SQLite

Filter: melanoma, PBMC, miraclib, and `time_from_treatment_start = 0`. There are **656 samples from 656 distinct subjects**. The drug **quintazide** does not occur in the supplied dataset; it is not included in this requested miraclib subset. The observed treatments are miraclib, phauximab, and none.

| Project | Baseline samples |
| --- | --- |
| prj1 | 384 |
| prj2 | 0 |
| prj3 | 272 |

| Response | Distinct subjects |
| --- | --- |
| no | 325 |
| yes | 331 |

| Recorded sex | Distinct subjects |
| --- | --- |
| F | 312 |
| M | 344 |

Here F means female and M means male as encoded in the source. Project totals count samples; response and sex totals use `COUNT(DISTINCT subject)`. `queries.sql` contains the queries, and `outputs/baseline_samples.csv` lists every matching sample with its project, subject, age, sex, treatment, response, sample type, and time point. Baseline describes pretreatment composition; this query alone does not estimate early treatment effects.

**Missing values in this subset.** Subjects with a missing response: 0. Subjects with a missing sex: 0. Missing values would be reported as `unknown` rather than dropped or merged into another group (`outputs/baseline_missing.csv`).

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

Tested runtime: Python 3.12.10, pandas 2.2.3, NumPy 2.3.5, SciPy 1.17.0, Matplotlib 3.10.8.

Method references: [SciPy Mann–Whitney U](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html); [Holm (1979), A Simple Sequentially Rejective Multiple Test Procedure](https://www.jstor.org/stable/4615733).
