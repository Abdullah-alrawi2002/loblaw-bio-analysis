"""Integrity checks for data ingestion and the statistical unit of analysis."""
import csv
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from load_data import CSV_PATH, DB_PATH, POPULATIONS, database_matches_source, ensure_database, load_data
from analysis import baseline_queries, cohort_table, compare, holm_adjust, independent_values, summary_table


class StudyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DB_PATH.exists():
            load_data()
        cls.raw = pd.read_csv(CSV_PATH)

    def test_every_input_count_and_sample_is_preserved(self):
        with sqlite3.connect(DB_PATH) as conn:
            summary = summary_table(conn)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(list(summary.columns), ["sample", "total_count", "population", "count", "percentage"])
        self.assertEqual(len(summary), 52500)
        self.assertTrue((summary.groupby("sample").size() == 5).all())
        actual = summary.pivot(index="sample", columns="population", values="count").sort_index()
        expected = self.raw.set_index("sample")[list(POPULATIONS)].sort_index()
        np.testing.assert_array_equal(actual[list(POPULATIONS)].to_numpy(), expected.to_numpy())
        np.testing.assert_allclose(summary.groupby("sample").percentage.sum(), 100, atol=1e-12)
        sample = summary[summary['sample'] == 'sample00000']
        self.assertTrue((sample.total_count == 93214).all())
        self.assertAlmostEqual(sample.loc[sample.population == 'b_cell', 'percentage'].iloc[0], 10908/93214*100)

    def test_null_response_not_recoded_as_no(self):
        with sqlite3.connect(DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sample_metadata WHERE response IS NULL").fetchone()[0], 1422)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sample_metadata WHERE response IS NULL AND (condition != 'healthy' OR treatment != 'none')").fetchone()[0], 0)

    def test_repeated_visits_do_not_become_independent_subjects(self):
        with sqlite3.connect(DB_PATH) as conn:
            cohort = cohort_table(conn)
        values = independent_values(cohort)
        self.assertEqual(cohort['sample'].nunique(), 1968)
        self.assertEqual(len(values), 656*5)
        self.assertTrue((values.sample_count == 3).all())
        self.assertFalse(values.duplicated(['subject','population']).any())
        repeated = independent_values(pd.concat([cohort,cohort], ignore_index=True))
        pd.testing.assert_frame_equal(values, repeated)
        stats = compare(values)
        self.assertTrue((stats.n_responders == 331).all())
        self.assertTrue((stats.n_nonresponders == 325).all())
        self.assertFalse(stats.significant_holm_0_05.any())
        cd4 = stats[stats.population == 'cd4_t_cell'].iloc[0]
        self.assertEqual(cd4.u_statistic_responders, 59855)
        self.assertLessEqual(cd4.q1_responders_pct, cd4.median_responders_pct)
        self.assertLessEqual(cd4.median_responders_pct, cd4.q3_responders_pct)
        self.assertLessEqual(cd4.q1_nonresponders_pct, cd4.median_nonresponders_pct)
        self.assertLessEqual(cd4.median_nonresponders_pct, cd4.q3_nonresponders_pct)
        self.assertAlmostEqual(cd4.p_holm, 0.06211053118714162, places=12)

    def test_holm_against_hand_calculated_values(self):
        # Ordered products: .01*4=.04, .02*3=.06, .03*2=.06, .20*1=.20.
        np.testing.assert_allclose(holm_adjust(np.array([.03,.01,.20,.02])), [.06,.04,.20,.06])
        # Cumulative maximum prevents adjusted p-values from decreasing by rank.
        np.testing.assert_allclose(holm_adjust(np.array([.03,.04,.045])), [.09,.09,.09])
        # Boundary: 0.01 × 5 = 0.05 is significant under the ≤ α rule used by compare().
        boundary = holm_adjust(np.array([0.01, 0.5, 0.5, 0.5, 0.5]))
        self.assertAlmostEqual(boundary[0], 0.05)
        self.assertTrue(bool(boundary[0] <= 0.05))
        self.assertFalse(bool(boundary[0] < 0.05))
        with self.assertRaises(ValueError):
            holm_adjust(np.array([float('nan')]))

    def test_baseline_counts(self):
        with sqlite3.connect(DB_PATH) as conn:
            b = baseline_queries(conn)
            again = baseline_queries(conn)
        self.assertEqual(len(b['samples']), 656)
        self.assertEqual(b['samples'].subject.nunique(), 656)
        self.assertEqual(dict(b['projects'].values), {'prj1':384,'prj2':0,'prj3':272})
        self.assertEqual(dict(b['response'].values), {'no':325,'yes':331})
        self.assertEqual(dict(b['sex'].values), {'F':312,'M':344})
        self.assertEqual(dict(b['missing'].values), {'response':0,'sex':0})
        pd.testing.assert_frame_equal(b['samples'], again['samples'])
        self.assertEqual(list(b['samples'].columns), [
            'sample', 'project', 'subject', 'condition', 'age', 'sex',
            'treatment', 'response', 'sample_type', 'time_from_treatment_start'])


class LoaderChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        with CSV_PATH.open(newline='') as f:
            reader = csv.DictReader(f)
            self.fields = reader.fieldnames
            self.row = next(reader)

    def write_csv(self, rows):
        p = self.path / 'source.csv'
        with p.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.fields)
            writer.writeheader()
            writer.writerows(rows)
        return p

    def test_reruns_are_idempotent(self):
        src = self.write_csv([self.row])
        db = self.path / 'data.db'
        load_data(src, db)
        load_data(src, db)
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM cell_counts').fetchone()[0], 5)

    def test_invalid_input_preserves_existing_database(self):
        src = self.write_csv([self.row]); db = self.path / 'data.db'
        load_data(src, db)
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        for bad_rows in ([self.row,self.row], [dict(self.row,b_cell='-1')],
                         [dict(self.row,b_cell='1.5')], [dict(self.row,response='maybe')],
                         [self.row,dict(self.row,sample='second',sex='F')]):
            with self.subTest(rows=bad_rows):
                src = self.write_csv(bad_rows)
                with self.assertRaises(ValueError):
                    load_data(src, db)
                self.assertEqual(before, hashlib.sha256(db.read_bytes()).hexdigest())

    def test_zero_total_is_undefined(self):
        src = self.write_csv([dict(self.row,**{p:'0' for p in POPULATIONS})])
        db = self.path/'data.db'; load_data(src,db)
        with sqlite3.connect(db) as conn:
            result = conn.execute('SELECT total_count, percentage FROM sample_frequencies').fetchall()
        self.assertEqual(result,[(0,None)]*5)

    def test_ensure_database_rebuilds_when_csv_sha_changes(self):
        src = self.write_csv([self.row])
        db = self.path / 'data.db'
        load_data(src, db)
        self.assertTrue(database_matches_source(db, src))
        self.assertIsNone(ensure_database(src, db))
        changed = dict(self.row, b_cell='1', cd8_t_cell='1', cd4_t_cell='1', nk_cell='1', monocyte='1')
        src = self.write_csv([changed])
        self.assertFalse(database_matches_source(db, src))
        result = ensure_database(src, db)
        self.assertIsNotNone(result)
        self.assertTrue(database_matches_source(db, src))
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute(
                "SELECT count FROM cell_counts WHERE population = 'b_cell'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
