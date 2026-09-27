#!/usr/bin/env python3
"""Validate cell-count.csv and atomically rebuild immune_cells.db.

Run directly: python load_data.py. No third-party packages or arguments required.
Paths resolve relative to this file, so running from another directory works.
"""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "cell-count.csv"
DB_PATH = ROOT / "immune_cells.db"
POPULATIONS = ("b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte")
LABELS = ("B cells", "CD8 T cells", "CD4 T cells", "NK cells", "Monocytes")
HEADERS = ("project", "subject", "condition", "age", "sex", "treatment",
           "response", "sample", "sample_type", "time_from_treatment_start", *POPULATIONS)


def integer(value: str, field: str, line: int, nonnegative: bool = True) -> int:
    try:
        number = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Line {line}: {field} must be an integer") from exc
    if nonnegative and number < 0:
        raise ValueError(f"Line {line}: {field} cannot be negative")
    if not -(2**63) <= number < 2**63:
        raise ValueError(f"Line {line}: {field} exceeds SQLite integer range")
    return number


def validate_csv(path: Path) -> list[dict]:
    records: list[dict] = []
    subjects: dict[str, str] = {}
    enrollments: dict[tuple, tuple] = {}
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or len(reader.fieldnames) != len(HEADERS) or set(reader.fieldnames) != set(HEADERS):
            raise ValueError(f"CSV must contain exactly these columns: {', '.join(HEADERS)}")
        for line, raw in enumerate(reader, start=2):
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError(f"Line {line}: incorrect number of fields")
            r = {k: v.strip() for k, v in raw.items()}
            for key in HEADERS:
                if key != "response" and not r[key]:
                    raise ValueError(f"Line {line}: missing {key}")
            r["response"] = r["response"] or None
            if r["response"] not in (None, "yes", "no"):
                raise ValueError(f"Line {line}: response must be yes, no, or blank")
            if r["sex"] not in ("M", "F"):
                raise ValueError(f"Line {line}: sex must be M or F in this dataset")
            for key in ("age", "time_from_treatment_start", *POPULATIONS):
                r[key] = integer(r[key], key, line, nonnegative=key != "time_from_treatment_start")
            if sum(r[p] for p in POPULATIONS) >= 2**63:
                raise ValueError(f"Line {line}: total cell count exceeds SQLite integer range")
            if r["sample"] in seen:
                raise ValueError(f"Line {line}: duplicate sample {r['sample']}")
            seen.add(r["sample"])
            subject = r["subject"]
            if subject in subjects and subjects[subject] != r["sex"]:
                raise ValueError(f"Line {line}: inconsistent sex for {subject}")
            subjects[subject] = r["sex"]
            key = (r["project"], subject)
            attributes = tuple(r[c] for c in ("condition", "age", "treatment", "response"))
            if key in enrollments and enrollments[key] != attributes:
                raise ValueError(f"Line {line}: inconsistent enrollment attributes for {key}")
            enrollments[key] = attributes
            records.append(r)
    if not records:
        raise ValueError("CSV contains no data rows")
    return records


def source_sha256(csv_path: Path = CSV_PATH) -> str:
    return hashlib.sha256(Path(csv_path).read_bytes()).hexdigest()


def database_matches_source(db_path: Path = DB_PATH, csv_path: Path = CSV_PATH) -> bool:
    """True when the DB exists and its stored SHA-256 matches the current CSV."""
    db_path, csv_path = Path(db_path), Path(csv_path)
    if not db_path.exists() or not csv_path.exists():
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT value FROM load_metadata WHERE key = 'source_sha256'").fetchone()
    except sqlite3.Error:
        return False
    return row is not None and row[0] == source_sha256(csv_path)


def ensure_database(csv_path: Path = CSV_PATH, db_path: Path = DB_PATH) -> dict | None:
    """Rebuild when the DB is missing or the CSV no longer matches load_metadata."""
    if database_matches_source(db_path, csv_path):
        return None
    return load_data(csv_path, db_path)


def load_data(csv_path: Path = CSV_PATH, db_path: Path = DB_PATH) -> dict:
    """Build a replacement only after complete validation; repeated runs are safe."""
    csv_path, db_path = Path(csv_path), Path(db_path)
    records = validate_csv(csv_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".immune-", suffix=".db", dir=db_path.parent)
    os.close(fd)
    temporary = Path(name)
    conn = None
    try:
        conn = sqlite3.connect(temporary)
        conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        with conn:
            conn.executemany("INSERT INTO populations VALUES (?, ?, ?)",
                             [(p, label, i) for i, (p, label) in enumerate(zip(POPULATIONS, LABELS))])
            projects = sorted({r["project"] for r in records})
            subjects = {r["subject"]: r["sex"] for r in records}
            enrollments = {(r["project"], r["subject"]): tuple(r[c] for c in ("condition", "age", "treatment", "response")) for r in records}
            conn.executemany("INSERT INTO projects VALUES (?)", [(p,) for p in projects])
            conn.executemany("INSERT INTO subjects VALUES (?, ?)", sorted(subjects.items()))
            conn.executemany("INSERT INTO enrollments VALUES (?, ?, ?, ?, ?, ?)",
                             [(*key, *value) for key, value in sorted(enrollments.items())])
            conn.executemany("INSERT INTO samples VALUES (?, ?, ?, ?, ?)",
                             [tuple(r[c] for c in ("sample", "project", "subject", "sample_type", "time_from_treatment_start")) for r in records])
            conn.executemany("INSERT INTO cell_counts VALUES (?, ?, ?)",
                             [(r["sample"], p, r[p]) for r in records for p in POPULATIONS])
            conn.executemany("INSERT INTO load_metadata VALUES (?, ?)", [
                ("source_file", csv_path.name),
                ("source_sha256", source_sha256(csv_path)),
                ("sample_count", str(len(records))), ("schema_version", "1")])
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign-key validation failed")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        conn.execute("PRAGMA optimize")
        conn.close()
        conn = None
        os.replace(temporary, db_path)
    finally:
        if conn is not None:
            conn.close()
        temporary.unlink(missing_ok=True)
    result = {"samples": len(records), "subjects": len(subjects),
              "projects": len(projects), "measurements": len(records) * len(POPULATIONS)}
    return result


if __name__ == "__main__":
    result = load_data()
    print(f"Created {DB_PATH.name}: {result['samples']:,} samples, "
          f"{result['subjects']:,} subjects, {result['measurements']:,} cell counts.")
