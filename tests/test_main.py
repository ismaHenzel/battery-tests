import pytest

import subprocess

import main

# Distinctive duration so the test can find its own stand-in process and no other.
STANDIN_POWERSTAT = ["sleep", "637"]


def standin_is_running():
    found = subprocess.run(
        ["pgrep", "-f", " ".join(STANDIN_POWERSTAT)], capture_output=True, text=True
    )
    return found.returncode == 0


def test_a_failed_browser_launch_does_not_leave_powerstat_running(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(main, "powerstat_command", lambda *a, **k: STANDIN_POWERSTAT)
    monkeypatch.setattr(
        main, "start_browser", lambda browser: (_ for _ in ()).throw(RuntimeError("no browser"))
    )

    try:
        exit_code = main.measure("firefox", "orphan", 180, 1.0, 300, False)

        assert exit_code != 0
        assert not standin_is_running()
    finally:
        subprocess.run(["pkill", "-f", " ".join(STANDIN_POWERSTAT)])


TRUNCATED_OUTPUT = """Running for 300.0 seconds (300 samples at 1.0 second intervals).

  Time    User  Nice   Sys  Idle    IO  Run Ctxt/s  IRQ/s  Watts
10:44:13   2.3   0.0   0.8  96.7   0.3    2   4766   1883  28.35
-------- ----- ----- ----- ----- ----- ---- ------ ------ ------
 Average   2.4   0.0   0.9  96.3   0.3  1.8 5062.5 2081.0  28.37
  StdDev   0.2   0.0   0.2   0.5   0.1  0.4  255.0  192.9   0.03
 Minimum   2.2   0.0   0.8  95.7   0.3  1.0 4766.0 1883.0  28.35
 Maximum   2.8   0.0   1.2  96.8   0.5  2.0 5436.0 2384.0  28.41
Summary:
System:  28.37 Watts on average with standard deviation 0.03
"""


def test_a_measurement_killed_early_is_not_reported_as_a_result(tmp_path):
    path = tmp_path / "chrome_killed_20260919-104102.txt"
    path.write_text(TRUNCATED_OUTPUT)

    assert main.report_run(path) is False


def test_a_measurement_that_finished_is_reported_as_a_result(tmp_path):
    path = tmp_path / "chrome_good_20260919-104102.txt"
    path.write_text(TRUNCATED_OUTPUT.replace("300 samples", "1 samples"))

    assert main.report_run(path) is True


class FakeDriver:
    """Stands in for Selenium, failing on whichever tabs the test names."""

    def __init__(self, failing_handles=()):
        self.window_handles = ["tab-a", "tab-b", "tab-c"]
        self.failing = set(failing_handles)
        self.current = None
        self.attempted = []
        self.refreshed = []
        self.switch_to = self

    def window(self, handle):
        self.current = handle

    def refresh(self):
        self.attempted.append(self.current)
        if self.current in self.failing:
            # The failure actually observed in a real run: a urllib3 read
            # timeout, which is not a WebDriverException.
            raise OSError("HTTPConnectionPool(host='localhost'): Read timed out.")
        self.refreshed.append(self.current)

    def execute_script(self, script):
        return 100


def test_one_failing_tab_does_not_end_the_whole_measurement(monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    driver = FakeDriver(failing_handles=["tab-b"])

    cycles = main.run_workload(
        driver, driver.window_handles, lambda: len(driver.attempted) < 3
    )

    assert driver.refreshed == ["tab-a", "tab-c"]
    assert cycles == 1


def test_a_browser_failing_on_every_tab_aborts_the_measurement(monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    driver = FakeDriver(failing_handles=["tab-a", "tab-b", "tab-c"])

    with pytest.raises(RuntimeError, match="every tab"):
        main.run_workload(driver, driver.window_handles, lambda: True)
