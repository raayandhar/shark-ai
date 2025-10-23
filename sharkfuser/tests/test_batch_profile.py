#!/usr/bin/env python3

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

batch_profile = Path(__file__).parent.parent / "benchmarks" / "batch_profile.py"

with tempfile.TemporaryDirectory() as tmpdir:
    tmpdir = Path(tmpdir)

    cmd_file = tmpdir / "cmd.txt"
    cmd_file.write_text(
        "conv --bf16 -n 16 -c 64 -H 48 -W 32 -k 64 -y 3 -x 3 -p 1 -q 1 -u 1 -v 1 -l 1 -j 1 "
        "--in_layout NHWC --out_layout NHWC --fil_layout NHWC --spatial_dim 2\n"
    )

    out = tmpdir / "out.csv"

    result = subprocess.run(
        [
            sys.executable,
            str(batch_profile),
            "--commands-file",
            str(cmd_file),
            "--csv",
            str(out),
            "--use-tempdir",
        ],
        capture_output=True,
    )

    assert result.returncode == 0, "batch_profile failed"
    assert out.exists(), "no output CSV"

    with open(out) as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1, "wrong row count"
    assert rows[0]["count (us)"] == "10", "wrong kernel count"

print("PASSED")
