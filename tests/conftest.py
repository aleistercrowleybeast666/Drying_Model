import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))


class TestResults:
    def __init__(self):
        self.reports=[]

    def pytest_runtest_logreport(self, report):
        if report.when=='call' or report.failed:
            self.reports.append(dict(test=report.nodeid,phase=report.when,outcome=report.outcome,
                duration_s=report.duration,error=str(report.longrepr) if report.failed else None))

    def pytest_sessionfinish(self,session,exitstatus):
        from drying.storage import Storage_WriteJson
        Storage_WriteJson(Path(__file__).resolve().parents[1]/'results/validation/program_tests.json',
            dict(exit_status=int(exitstatus),tests=self.reports))


def pytest_configure(config):
    config.pluginmanager.register(TestResults(),'drying-result-recorder')
