# AI CODE GENERATED, I JUST USED TO MEASURE MY BATERY DISCHARGING USING POWERSTAT
"""Drive a browser workload while powerstat measures the battery drain it causes.

powerstat owns the clock: it is started first, the browser warms up during its
pre-measurement delay, and the workload loops until powerstat has taken all of
its samples.
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver

from powerstat_report import (
    build_output_path,
    collect_runs,
    format_summary_table,
    minimum_run_seconds,
    parse_powerstat_output,
    powerstat_command,
    validate_run_length,
)

# A list of safe, varied sites to keep open in tabs
URLS = [
    "https://en.wikipedia.org/wiki/Special:Random",
    "https://news.ycombinator.com",
    "https://github.com/trending",
    "https://stackoverflow.com",
    "https://www.bbc.com/news",
    "https://www.youtube.com",
    "https://www.youtube.com/watch?v=W5FI97ovWog",
    "https://medium.com/",
]

OUTPUT_DIR = Path(__file__).resolve().parent / "powerstat"


# Without these, a hung page blocks on Selenium's 120s command timeout and
# takes a chunk of the measurement window with it.
PAGE_LOAD_TIMEOUT = 60
SCRIPT_TIMEOUT = 30


def start_browser(browser):
    """Launch the browser under test; Selenium Manager supplies the driver."""
    if browser == "firefox":
        driver = webdriver.Firefox(options=webdriver.FirefoxOptions())
    else:
        driver = webdriver.Chrome(options=webdriver.ChromeOptions())

    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(SCRIPT_TIMEOUT)
    return driver


def open_tabs(driver, urls):
    """Open every URL in its own tab and return the tab handles."""
    for index, url in enumerate(urls):
        if index == 0:
            # First URL loads in the default open window
            driver.get(url)
        else:
            # Open a new tab and switch to it for subsequent URLs
            driver.switch_to.new_window("tab")
            driver.get(url)
        time.sleep(2)  # Give each tab a moment to start loading
    return driver.window_handles


def visit_tab(driver, tab_handle, still_measuring):
    """Refresh one tab and scroll it to the bottom."""
    driver.switch_to.window(tab_handle)
    driver.refresh()

    # Allow the page to load after refreshing
    time.sleep(3)

    scroll_height = driver.execute_script("return document.body.scrollHeight")
    for step in range(0, scroll_height, 400):
        if not still_measuring():
            break
        driver.execute_script(f"window.scrollTo(0, {step});")
        time.sleep(0.5)

    # Pause at the bottom of the page before switching tabs
    time.sleep(2)


def run_workload(driver, tabs, still_measuring):
    """Refresh and scroll each tab in turn for as long as powerstat is sampling.

    A single tab that hangs or errors must not throw away a measurement that
    takes eight minutes to collect, so failures are logged and the workload
    moves on. A browser that fails on every tab in a cycle is gone for good,
    though, and looping on it would leave powerstat measuring nothing.
    """
    cycle = 0
    while still_measuring():
        cycle += 1
        print(f"\n--- Cycle {cycle} ---")
        failures = 0

        for tab_index, tab_handle in enumerate(tabs):
            if not still_measuring():
                break

            print(f"Tab {tab_index + 1}: Refreshing and scrolling...")
            try:
                visit_tab(driver, tab_handle, still_measuring)
            except Exception as error:
                # Anything from a WebDriverException to a urllib3 read timeout.
                failures += 1
                print(f"Tab {tab_index + 1} failed, moving on: {error}")

        if failures == len(tabs):
            raise RuntimeError(
                f"the browser failed on every tab in cycle {cycle}; "
                "giving up rather than measuring an idle machine"
            )

    return cycle


def report_run(output_path):
    """Print what powerstat concluded, or say the run never got that far."""
    stats = parse_powerstat_output(output_path.read_text(errors="replace"))
    if stats is None:
        print(
            f"\n{output_path} holds no summary - the run was cut short before "
            "powerstat could finish measuring."
        )
        return False

    if not stats.is_complete:
        # powerstat prints a summary even when killed, and averaging a handful
        # of readings looks like a result while meaning nothing.
        print(
            f"\nAborted after {stats.readings} of {stats.samples} samples - "
            f"not a valid measurement. {output_path} is kept for inspection "
            "and left out of --summary."
        )
        return False

    print(
        f"\n{stats.average_watts:.2f} W on average "
        f"(stddev {stats.stddev_watts:.2f}, "
        f"min {stats.minimum_watts:.2f}, max {stats.maximum_watts:.2f})"
    )
    print(f"Saved to {output_path}")
    return True


def measure(browser, label, delay, interval, samples, rapl):
    """Run one measurement: powerstat plus the browser workload it is timing."""
    validate_run_length(delay, interval, samples, rapl)

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = build_output_path(browser, label, datetime.now(), OUTPUT_DIR)
    command = powerstat_command(delay, interval, samples, rapl)
    total_seconds = delay + interval * samples

    print(f"Starting {browser} battery drain test, label '{label}'.")
    print(f"powerstat: {' '.join(command)} -> {output_path}")
    print(
        f"Measuring for {total_seconds:.0f}s "
        f"({delay}s warm-up, then {samples} samples at {interval}s)."
    )

    driver = None
    with output_path.open("w") as output_file:
        process = subprocess.Popen(
            command, stdout=output_file, stderr=subprocess.STDOUT, text=True
        )
        try:
            # powerstat refuses some option combinations outright; catch that
            # before spending time launching a browser for nothing.
            time.sleep(1)
            if process.poll() is not None:
                print(f"\npowerstat exited immediately:\n{output_path.read_text()}")
                return 1

            driver = start_browser(browser)
            print("Opening initial tabs...")
            tabs = open_tabs(driver, URLS)

            cycles = run_workload(driver, tabs, lambda: process.poll() is None)
            process.wait()
            print(f"\nWorkload finished after {cycles} cycles.")
        except KeyboardInterrupt:
            print("\nTest interrupted by user.")
            process.terminate()
            process.wait()
        except Exception as error:
            # Never leave powerstat sampling on behalf of a workload that died.
            print(f"\nAn error occurred: {error}")
            process.terminate()
            process.wait()
        finally:
            if driver is not None:
                print("Closing browser and cleaning up...")
                driver.quit()

    return 0 if report_run(output_path) else 1


def summarise():
    """Compare every measurement saved in the powerstat folder."""
    usable, skipped = collect_runs(OUTPUT_DIR)
    print(format_summary_table(usable))
    if skipped:
        print(f"\nSkipped (incomplete or unfinished): {', '.join(skipped)}")
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Measure battery drain from a scripted browser workload."
    )
    parser.add_argument(
        "--browser",
        choices=("chrome", "firefox"),
        default="chrome",
        help="browser to drive (default: chrome)",
    )
    parser.add_argument(
        "--label",
        help="name for this hardware/power configuration, e.g. optimized_hybrid",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=180,
        help="seconds powerstat waits before sampling, used to warm up (default: 180)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="seconds between powerstat samples (default: 1.0)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=300,
        help="number of powerstat samples to take (default: 300)",
    )
    parser.add_argument(
        "--rapl",
        action="store_true",
        help=(
            "measure via the Intel RAPL counters instead of the battery gauge; "
            f"lowers powerstat's minimum run from {minimum_run_seconds(False)}s "
            f"to {minimum_run_seconds(True)}s, which is what makes a quick "
            "smoke test possible"
        ),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print a comparison of saved measurements and exit",
    )

    args = parser.parse_args(argv)
    if not args.summary and not args.label:
        parser.error("--label is required for a measurement run")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.summary:
        return summarise()

    try:
        return measure(
            browser=args.browser,
            label=args.label,
            delay=args.delay,
            interval=args.interval,
            samples=args.samples,
            rapl=args.rapl,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
