#!/usr/bin/env python3

import argparse
import csv
import glob
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple


class TimingStats(NamedTuple):
    min: float | str = "N.A."
    max: float | str = "N.A."
    mean: float | str = "N.A."
    stddev: float | str = "N.A."
    count: int | str = "N.A."


ALL_STATS = ["min", "max", "mean", "stddev", "count"]


def parse_rocprof_csv(output_dir: Path) -> TimingStats:
    kernel_trace_files = list(output_dir.rglob("*kernel_trace.csv"))

    if not kernel_trace_files:
        return TimingStats()

    durations = []

    for csv_file in kernel_trace_files:
        try:
            with open(csv_file, "r") as f:
                reader = csv.DictReader(f)
                # Each row represents a single kernel dispatch
                for row in reader:
                    if "Start_Timestamp" in row and "End_Timestamp" in row:
                        start = float(row["Start_Timestamp"])
                        end = float(row["End_Timestamp"])
                        # Convert from nanoseconds to microseconds
                        duration_us = (end - start) / 1000.0
                        durations.append(duration_us)
        except Exception as e:
            raise RuntimeError(
                f"Failed to parse rocprof CSV file {csv_file}: {e}"
            ) from e

    if not durations:
        return TimingStats()

    min_time = min(durations)
    max_time = max(durations)
    mean_time = statistics.mean(durations)
    stddev = statistics.stdev(durations) if len(durations) > 1 else 0.0
    count = len(durations)

    return TimingStats(
        min=min_time, max=max_time, mean=mean_time, stddev=stddev, count=count
    )


def run_profiled_command(
    command: str,
    driver_path: str,
    output_dir: Path | None,
    iter_count: int,
    rocprof_args: list[str],
    verbose: bool,
    cmd_num: int,
    use_tempdir: bool,
) -> TimingStats:

    driver_args = command.split()
    if not driver_args:
        if verbose:
            print(f">>> Failed to parse command: {command}")
        return TimingStats()

    driver_cmd = [driver_path, "--iter", str(iter_count)] + driver_args

    # Use either temporary directory or persistent directory
    if use_tempdir:
        tmpdir_context = tempfile.TemporaryDirectory()
        cmd_output_dir = Path(tmpdir_context.__enter__())
    else:
        tmpdir_context = None
        cmd_output_dir = output_dir / f"command_{cmd_num}"
        cmd_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        rocprof_cmd = (
            [
                "rocprofv3",
                "--output-format",
                "csv",
                "--output-directory",
                str(cmd_output_dir),
            ]
            + rocprof_args
            + ["--"]
            + driver_cmd
        )

        if verbose:
            print(f">>> {shlex.join(rocprof_cmd)}\n")

        result = subprocess.run(
            rocprof_cmd,
            check=True,
            capture_output=True,
            text=True,
        )

        if verbose and result.stdout:
            print(result.stdout)

        stats = parse_rocprof_csv(cmd_output_dir)

        if verbose:
            print(
                f">>> Stats: min={stats.min}, max={stats.max}, mean={stats.mean}, count={stats.count}"
            )

        return stats

    except subprocess.CalledProcessError as e:
        if verbose:
            print(f">>> Command failed with exit code {e.returncode}")
            if e.stderr:
                print(f">>> stderr: {e.stderr}")
        return TimingStats()
    except Exception as e:
        if verbose:
            print(f">>> Exception: {e}")
        return TimingStats()
    finally:
        # Cleanup temporary directory if used
        if tmpdir_context is not None:
            tmpdir_context.__exit__(None, None, None)


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="""
Run Fusilli benchmarks with rocprofv3 profiling and aggregate results.

Commands are read from a file (one per line). Each command is run through
rocprofv3, and timing statistics are collected and written to a CSV file.

Command format example:
  conv --bf16 -n 16 -c 64 -H 48 -W 32 -k 64 -y 3 -x 3 -p 1 -q 1 -u 1 -v 1 -l 1 -j 1 --in_layout NHWC --out_layout NHWC --fil_layout NHWC --spatial_dim 2

The script will:
  1. Run each command under rocprofv3
  2. Extract timing statistics from rocprof CSV outputs
  3. Aggregate results into a single output CSV
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--commands-file",
        type=str,
        required=True,
        help="File containing benchmark commands (one per line)",
    )

    parser.add_argument(
        "--csv",
        type=str,
        default="profile_results.csv",
        help="Output CSV file for aggregated results (default: profile_results.csv)",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="profile_results",
        help="Directory to store rocprof outputs (default: profile_results/). Ignored if --use-tempdir is set.",
    )

    parser.add_argument(
        "--driver",
        type=str,
        default="build/bin/benchmarks/fusilli_benchmark_driver",
        help="Path to fusilli_benchmark_driver binary",
    )

    parser.add_argument(
        "--iter",
        type=int,
        default=10,
        help="Number of iterations for each benchmark (default: 10)",
    )

    parser.add_argument(
        "--rocprof-args",
        type=str,
        default="--runtime-trace",
        help="Arguments for rocprofv3 (default: --runtime-trace)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        default=None,
        help="Print detailed output",
    )

    parser.add_argument(
        "--no-verbose",
        action="store_false",
        dest="verbose",
        help="Disable detailed output",
    )

    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running even if a command fails",
    )

    parser.add_argument(
        "--use-tempdir",
        action="store_true",
        help="Use temporary directories for rocprof outputs (auto-cleanup after parsing)",
    )

    return parser


def main():
    parser = get_parser()
    args = parser.parse_args()

    if args.verbose is None:
        args.verbose = args.csv is None

    commands_file = Path(args.commands_file)
    if not commands_file.exists():
        print(f"Error: Commands file not found: {commands_file}")
        return 1

    with open(commands_file, "r") as f:
        commands = [
            line.strip()
            for line in f.readlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    if not commands:
        print("Error: No commands found in file")
        return 1

    print(f"Found {len(commands)} commands")

    # Setup output directory (only if not using tempdir)
    output_dir = None
    if not args.use_tempdir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    rocprof_args = (
        args.rocprof_args.split() if args.rocprof_args else ["--runtime-trace"]
    )

    if args.verbose:
        print(f"Rocprof args: {' '.join(rocprof_args)}")
        if args.use_tempdir:
            print(f"Using temporary directories (auto-cleanup)")
        else:
            print(f"Output directory: {output_dir.absolute()}")
        print(f"Results will be written to: {args.csv}\n")

    csv_file = csv.writer(open(args.csv, "w", newline=""))
    csv_headers = ["command"] + [f"{stat} (us)" for stat in ALL_STATS]
    csv_file.writerow(csv_headers)

    cmd_count = 0
    success_count = 0
    failed_count = 0

    for command in commands:
        cmd_count += 1

        if args.verbose:
            print(f"\n{'='*80}")
            print(f"Command {cmd_count}/{len(commands)}: {command}")
            print(f"{'='*80}")
        else:
            print(f"Running command {cmd_count}/{len(commands)}")

        stats = run_profiled_command(
            command,
            args.driver,
            output_dir,
            args.iter,
            rocprof_args,
            args.verbose,
            cmd_count,
            args.use_tempdir,
        )

        csv_row = [command]
        for stat in ALL_STATS:
            value = getattr(stats, stat)
            csv_row.append(f"{value:.2f}" if isinstance(value, float) else str(value))
        csv_file.writerow(csv_row)

        if isinstance(stats.mean, float):
            success_count += 1
        else:
            failed_count += 1
            if not args.continue_on_error:
                print("\nStopping due to error. Use --continue-on-error to continue.")
                break

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total commands: {cmd_count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failed_count}")
    print(f"Results CSV: {args.csv}")
    if not args.use_tempdir:
        print(f"Rocprof outputs: {output_dir.absolute()}")
    print(f"{'='*80}\n")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
