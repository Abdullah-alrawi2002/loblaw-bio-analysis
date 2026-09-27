PRAGMA foreign_keys = ON;

CREATE TABLE projects (
    project TEXT PRIMARY KEY CHECK (length(project) > 0)
);
CREATE TABLE subjects (
    subject TEXT PRIMARY KEY CHECK (length(subject) > 0),
    sex TEXT NOT NULL CHECK (sex IN ('M', 'F'))
);
-- Trial attributes belong to an enrollment, allowing another project per subject.
CREATE TABLE enrollments (
    project TEXT NOT NULL REFERENCES projects(project),
    subject TEXT NOT NULL REFERENCES subjects(subject),
    condition TEXT NOT NULL,
    age INTEGER NOT NULL CHECK (typeof(age) = 'integer' AND age >= 0),
    treatment TEXT NOT NULL,
    response TEXT CHECK (response IN ('yes', 'no') OR response IS NULL),
    PRIMARY KEY (project, subject)
);
CREATE TABLE samples (
    sample TEXT PRIMARY KEY CHECK (length(sample) > 0),
    project TEXT NOT NULL,
    subject TEXT NOT NULL,
    sample_type TEXT NOT NULL,
    time_from_treatment_start INTEGER NOT NULL
        CHECK (typeof(time_from_treatment_start) = 'integer'),
    FOREIGN KEY (project, subject) REFERENCES enrollments(project, subject)
);
CREATE TABLE populations (
    population TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL UNIQUE
);
CREATE TABLE cell_counts (
    sample TEXT NOT NULL REFERENCES samples(sample),
    population TEXT NOT NULL REFERENCES populations(population),
    count INTEGER NOT NULL CHECK (typeof(count) = 'integer' AND count >= 0),
    PRIMARY KEY (sample, population)
);
CREATE TABLE load_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_enrollments_condition_treatment
    ON enrollments(condition, treatment, project, subject);
CREATE INDEX idx_samples_type_time
    ON samples(sample_type, time_from_treatment_start, project, subject);
CREATE INDEX idx_samples_enrollment ON samples(project, subject);

-- Exactly the five columns required for Part 2. A zero denominator yields NULL.
CREATE VIEW sample_frequencies AS
WITH counts AS (
    SELECT sample, population, count,
           SUM(count) OVER (PARTITION BY sample) AS total_count
    FROM cell_counts
)
SELECT sample, total_count, population, count,
       100.0 * count / NULLIF(total_count, 0) AS percentage
FROM counts;

CREATE VIEW sample_metadata AS
SELECT s.sample, s.project, s.subject, e.condition, e.age, u.sex,
       e.treatment, e.response, s.sample_type, s.time_from_treatment_start
FROM samples AS s
JOIN enrollments AS e USING (project, subject)
JOIN subjects AS u USING (subject);
