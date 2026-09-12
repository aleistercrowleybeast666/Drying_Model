"""Reassess existing 2D evidence without solving, exporting Excel or drawing."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'src'))
from drying.auxiliary2d import Auxiliary_Evaluate, Auxiliary_Publish
from drying.studies.baseline import Baseline_Check

if __name__ == '__main__':
    Baseline_Check(ROOT)
    report = Auxiliary_Evaluate(ROOT)
    Auxiliary_Publish(ROOT, report)
    Baseline_Check(ROOT)
    for case, row in report['cases'].items():
        print(case, row['two_dimensional_validation_status'], row['gates'], flush=True)
    sys.exit(0 if report['two_dimensional_auxiliary_validation_passed'] else 1)
