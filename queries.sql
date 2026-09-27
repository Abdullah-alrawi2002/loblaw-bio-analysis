-- Part 2: strict five-column output.
SELECT sample, total_count, population, count, percentage
FROM sample_frequencies ORDER BY sample, population;

-- Part 3: requested cohort. Unknown outcomes stay excluded from comparisons.
SELECT f.*, m.project, m.subject, m.response, m.time_from_treatment_start
FROM sample_frequencies AS f JOIN sample_metadata AS m USING (sample)
WHERE m.condition = 'melanoma' AND m.treatment = 'miraclib'
  AND m.sample_type = 'PBMC' AND m.response IN ('yes', 'no');

-- Part 4: the common subset is materialized once for the following SQL queries.
DROP VIEW IF EXISTS baseline_subset;
CREATE TEMP VIEW baseline_subset AS
SELECT * FROM sample_metadata
WHERE condition = 'melanoma' AND treatment = 'miraclib'
  AND sample_type = 'PBMC' AND time_from_treatment_start = 0;

SELECT * FROM baseline_subset ORDER BY project, subject, sample;

-- Samples, including zero for projects with no eligible sample.
SELECT p.project, COUNT(b.sample) AS sample_count
FROM projects AS p LEFT JOIN baseline_subset AS b USING (project)
GROUP BY p.project ORDER BY p.project;

-- Distinct subjects, not sample counts.
SELECT COALESCE(response, 'unknown') AS response,
       COUNT(DISTINCT subject) AS subject_count
FROM baseline_subset GROUP BY response ORDER BY response;

SELECT COALESCE(sex, 'unknown') AS sex, COUNT(DISTINCT subject) AS subject_count
FROM baseline_subset GROUP BY sex ORDER BY sex;

-- Missing response or sex, reported separately rather than dropped.
SELECT 'response' AS field,
       COUNT(DISTINCT CASE WHEN response IS NULL THEN subject END) AS missing_subjects
FROM baseline_subset
UNION ALL
SELECT 'sex', COUNT(DISTINCT CASE WHEN sex IS NULL THEN subject END)
FROM baseline_subset;
