"""Pure helpers for driving powerstat runs and reporting on their output."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

# powerstat rejects runs shorter than these, since it needs enough readings to
# see a trend: 480s from the battery gauge, 60s from the RAPL counters.
BATTERY_MINIMUM_SECONDS = 480
RAPL_MINIMUM_SECONDS = 60


def build_output_path(
    browser: str, label: str, started_at: datetime, output_dir: Path
) -> Path:
    """Name a run's output file after its browser, config label and start time."""
    stamp = started_at.strftime(TIMESTAMP_FORMAT)
    return output_dir / f"{browser}_{label}_{stamp}.txt"


def minimum_run_seconds(rapl: bool) -> int:
    """powerstat's floor: 480s off the battery gauge, 60s off the RAPL counters."""
    return RAPL_MINIMUM_SECONDS if rapl else BATTERY_MINIMUM_SECONDS


def validate_run_length(
    delay: int, interval: float, samples: int, rapl: bool = False
) -> None:
    """Reject runs powerstat itself would refuse as too short to measure."""
    minimum = minimum_run_seconds(rapl)
    total = delay + interval * samples
    if total < minimum:
        raise ValueError(
            f"powerstat needs at least {minimum}s of run time "
            f"(delay + interval x samples), got {total:.0f}s. "
            f"Raise --samples/--delay."
        )


@dataclass(frozen=True)
class RunStats:
    """The watts figures powerstat reports at the end of a completed run."""

    average_watts: float
    stddev_watts: float
    minimum_watts: float
    maximum_watts: float
    samples: int | None = None
    readings: int = 0

    @property
    def is_complete(self) -> bool:
        """True when powerstat took every sample it set out to take.

        A run cut short still prints a full summary, so the declared sample
        count has to be checked against the readings actually recorded.
        """
        return self.samples is None or self.readings >= self.samples


_SUMMARY = re.compile(
    r"System:\s+([\d.]+) Watts on average with standard deviation ([\d.]+)"
)
_SAMPLES = re.compile(r"\((\d+) samples at")
_READING = re.compile(r"^\d{2}:\d{2}:\d{2}\s")


# Watts is the rightmost column of powerstat's default table, and stays rightmost
# unless an option such as -D adds columns after it.
_LAST_COLUMN = -1


def _watts_column(text: str) -> int:
    """Locate the Watts column, whose position shifts with powerstat's options."""
    for line in text.splitlines():
        if "Watts" in line and "Time" in line:
            return line.split().index("Watts")
    return _LAST_COLUMN


def _row_watts(text: str, row_label: str, column: int) -> float | None:
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == row_label and len(fields) > column:
            return float(fields[column])
    return None


def parse_powerstat_output(text: str) -> RunStats | None:
    """Read a run's watts statistics, or None if the run never reached its summary."""
    summary = _SUMMARY.search(text)
    if summary is None:
        return None

    column = _watts_column(text)
    minimum = _row_watts(text, "Minimum", column)
    maximum = _row_watts(text, "Maximum", column)
    if minimum is None or maximum is None:
        return None

    samples = _SAMPLES.search(text)
    readings = sum(1 for line in text.splitlines() if _READING.match(line))
    return RunStats(
        average_watts=float(summary.group(1)),
        stddev_watts=float(summary.group(2)),
        minimum_watts=minimum,
        maximum_watts=maximum,
        samples=int(samples.group(1)) if samples else None,
        readings=readings,
    )


def collect_runs(output_dir: Path) -> tuple[list[tuple[str, RunStats]], list[str]]:
    """Read every saved run in a folder, reporting which ones never completed."""
    usable: list[tuple[str, RunStats]] = []
    skipped: list[str] = []

    for path in sorted(output_dir.glob("*.txt")):
        stats = parse_powerstat_output(path.read_text(errors="replace"))
        if stats is None or not stats.is_complete:
            skipped.append(path.stem)
        else:
            usable.append((path.stem, stats))

    return usable, skipped


_SUMMARY_COLUMNS = ("Run", "Avg W", "StdDev", "Min W", "Max W", "Samples")


def format_summary_table(rows: list[tuple[str, RunStats]]) -> str:
    """Render runs as a table, lowest average power first."""
    if not rows:
        return "No completed measurements found."

    ordered = sorted(rows, key=lambda row: row[1].average_watts)
    name_width = max(len(name) for name, _ in ordered)
    name_width = max(name_width, len(_SUMMARY_COLUMNS[0]))

    header = (
        f"{_SUMMARY_COLUMNS[0]:<{name_width}}  "
        f"{_SUMMARY_COLUMNS[1]:>7}  {_SUMMARY_COLUMNS[2]:>7}  "
        f"{_SUMMARY_COLUMNS[3]:>7}  {_SUMMARY_COLUMNS[4]:>7}  "
        f"{_SUMMARY_COLUMNS[5]:>7}"
    )
    lines = [header, "-" * len(header)]

    for name, stats in ordered:
        samples = "-" if stats.samples is None else str(stats.samples)
        lines.append(
            f"{name:<{name_width}}  "
            f"{stats.average_watts:>7.2f}  {stats.stddev_watts:>7.2f}  "
            f"{stats.minimum_watts:>7.2f}  {stats.maximum_watts:>7.2f}  "
            f"{samples:>7}"
        )

    return "\n".join(lines)


def powerstat_command(
    delay: int, interval: float, samples: int, rapl: bool = False
) -> list[str]:
    """Build the powerstat invocation, matching the form used for earlier runs."""
    command = ["powerstat", "-d", str(delay)]
    if rapl:
        command.append("-R")
    command += [str(interval), str(samples)]
    return command
