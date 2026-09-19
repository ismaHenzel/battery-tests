import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from powerstat_report import (
    build_output_path,
    RunStats,
    collect_runs,
    format_summary_table,
    parse_powerstat_output,
    powerstat_command,
    validate_run_length,
)


def test_output_path_combines_browser_label_and_timestamp():
    path = build_output_path(
        browser="firefox",
        label="optimized_hybrid",
        started_at=datetime(2026, 9, 19, 10, 15, 30),
        output_dir=Path("powerstat"),
    )

    assert path == Path("powerstat/firefox_optimized_hybrid_20260919-101530.txt")


def test_default_battery_run_is_long_enough():
    validate_run_length(delay=180, interval=1.0, samples=300, rapl=False)


def test_battery_run_under_480_seconds_is_rejected():
    with pytest.raises(ValueError, match="480"):
        validate_run_length(delay=0, interval=1.0, samples=300, rapl=False)


def test_rapl_run_needs_only_60_seconds():
    validate_run_length(delay=0, interval=1.0, samples=60, rapl=True)


def test_rapl_run_under_60_seconds_is_rejected():
    with pytest.raises(ValueError, match="60"):
        validate_run_length(delay=0, interval=1.0, samples=59, rapl=True)


RUN_OUTPUT = """Running for 300.0 seconds (300 samples at 1.0 second intervals).
Power measurements will start in 180 seconds time.

  Time    User  Nice   Sys  Idle    IO  Run Ctxt/s  IRQ/s  Watts
20:02:04  10.3   0.0   1.4  87.4   0.9    5  12285   4231  13.72
20:02:05  15.1   0.0   3.1  80.9   1.0    2  16479   8609  13.72
-------- ----- ----- ----- ----- ----- ---- ------ ------ ------
 Average   4.8   0.0   1.2  93.4   0.6  1.9 8394.3 3788.5  12.48
 GeoMean   3.3   0.0   0.9  93.2   0.0  1.6 7120.2 3170.9  11.68
  StdDev   4.1   0.0   1.0   5.4   0.7  1.4 4870.4 2549.3   5.42
-------- ----- ----- ----- ----- ----- ---- ------ ------ ------
 Minimum   0.4   0.0   0.1  74.7   0.0  1.0 1770.0 1160.0   7.49
 Maximum  18.6   0.0   6.4  99.4   3.1 10.0 24412.0 17348.0  36.46
-------- ----- ----- ----- ----- ----- ---- ------ ------ ------
Summary:
System:  12.48 Watts on average with standard deviation 5.42
"""


COMPLETE_OUTPUT = RUN_OUTPUT.replace("300 samples", "2 samples")


def test_parses_watts_statistics_from_a_completed_run():
    stats = parse_powerstat_output(RUN_OUTPUT)

    assert stats.average_watts == 12.48
    assert stats.stddev_watts == 5.42
    assert stats.minimum_watts == 7.49
    assert stats.maximum_watts == 36.46
    assert stats.samples == 300


def test_run_interrupted_before_the_summary_does_not_parse():
    truncated = RUN_OUTPUT.split("-------- -----")[0]

    assert parse_powerstat_output(truncated) is None


def test_every_measurement_committed_to_the_repo_parses():
    # Only committed files: an in-flight or interrupted run has no summary yet,
    # which collect_runs is expected to skip rather than parse.
    listed = subprocess.run(
        ["git", "ls-files", "powerstat/*.txt"],
        capture_output=True,
        text=True,
        check=True,
    )
    measurements = [Path(line) for line in listed.stdout.split()]
    assert measurements, "expected the committed powerstat measurements to be present"

    for path in measurements:
        stats = parse_powerstat_output(path.read_text(errors="replace"))
        assert stats is not None, f"{path} did not parse"
        assert stats.average_watts > 0
        assert stats.minimum_watts <= stats.average_watts <= stats.maximum_watts


def test_summary_table_lists_the_most_efficient_run_first():
    rows = [
        ("chrome_optimized_hybrid", RunStats(12.48, 5.42, 7.49, 36.46, 300)),
        ("firefox_optimized_hybrid", RunStats(9.10, 3.00, 6.00, 20.00, 300)),
    ]

    table = format_summary_table(rows)

    assert table.index("firefox_optimized_hybrid") < table.index("chrome_optimized_hybrid")
    assert "9.10" in table
    assert "12.48" in table


def test_summary_table_says_so_when_there_is_nothing_to_compare():
    assert "No" in format_summary_table([])


def test_collect_runs_separates_usable_measurements_from_unfinished_ones(tmp_path):
    (tmp_path / "chrome_good_20260919-101530.txt").write_text(COMPLETE_OUTPUT)
    (tmp_path / "firefox_aborted_20260919-104412.txt").write_text("interrupted early")

    usable, skipped = collect_runs(tmp_path)

    assert [name for name, _ in usable] == ["chrome_good_20260919-101530"]
    assert skipped == ["firefox_aborted_20260919-104412"]


def test_powerstat_command_matches_the_committed_runs():
    assert powerstat_command(delay=180, interval=1.0, samples=300, rapl=False) == [
        "powerstat",
        "-d",
        "180",
        "1.0",
        "300",
    ]


def test_rapl_runs_ask_powerstat_for_the_rapl_interface():
    command = powerstat_command(delay=0, interval=1.0, samples=60, rapl=True)

    assert "-R" in command


TRUNCATED_OUTPUT = """Running for 300.0 seconds (300 samples at 1.0 second intervals).
Power measurements will start in 180 seconds time.

  Time    User  Nice   Sys  Idle    IO  Run Ctxt/s  IRQ/s  Watts
10:44:13   2.3   0.0   0.8  96.7   0.3    2   4766   1883  28.35
10:44:14   2.4   0.0   1.2  96.1   0.3    1   4902   1950  28.35
-------- ----- ----- ----- ----- ----- ---- ------ ------ ------
 Average   2.4   0.0   0.9  96.3   0.3  1.8 5062.5 2081.0  28.37
 GeoMean   2.4   0.0   0.9  96.3   0.3  1.7 5056.1 2072.4  28.37
  StdDev   0.2   0.0   0.2   0.5   0.1  0.4  255.0  192.9   0.03
-------- ----- ----- ----- ----- ----- ---- ------ ------ ------
 Minimum   2.2   0.0   0.8  95.7   0.3  1.0 4766.0 1883.0  28.35
 Maximum   2.8   0.0   1.2  96.8   0.5  2.0 5436.0 2384.0  28.41
-------- ----- ----- ----- ----- ----- ---- ------ ------ ------
Summary:
System:  28.37 Watts on average with standard deviation 0.03
"""


def test_a_run_killed_early_still_reports_how_few_readings_it_got():
    stats = parse_powerstat_output(TRUNCATED_OUTPUT)

    assert stats.samples == 300
    assert stats.readings == 2
    assert not stats.is_complete


def test_a_run_that_took_all_its_samples_is_complete():
    stats = parse_powerstat_output(COMPLETE_OUTPUT)

    assert stats.readings == 2
    assert stats.samples == 2
    assert stats.is_complete


def test_summary_leaves_out_runs_that_were_killed_early(tmp_path):
    (tmp_path / "firefox_good_20260919-103244.txt").write_text(COMPLETE_OUTPUT)
    (tmp_path / "chrome_killed_20260919-104102.txt").write_text(TRUNCATED_OUTPUT)

    usable, skipped = collect_runs(tmp_path)

    assert [name for name, _ in usable] == ["firefox_good_20260919-103244"]
    assert skipped == ["chrome_killed_20260919-104102"]
