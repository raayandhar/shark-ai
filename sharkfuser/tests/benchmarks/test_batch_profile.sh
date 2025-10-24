#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_COMMANDS="${SCRIPT_DIR}/test_commands.txt"
# We are running from the build directory (where ctest runs)
BATCH_PROFILE="${SCRIPT_DIR}/../../benchmarks/batch_profile.py"
DRIVER="bin/benchmarks/fusilli_benchmark_driver"
OUTPUT_CSV="test_batch_profile_out.csv"

# Any artifacts from a previous test
rm -f "${OUTPUT_CSV}"
python3 "${BATCH_PROFILE}" \
  --commands-file "${TEST_COMMANDS}" \
  --csv "${OUTPUT_CSV}" \
  --driver "${DRIVER}" \
  --use-tempdir \
  --iter 10

if [ ! -f "${OUTPUT_CSV}" ]; then
  echo "ERROR: Output CSV not created"
  exit 1
fi
# Count number of rows
NUM_ROWS=$(tail -n +2 "${OUTPUT_CSV}" | wc -l)
EXPECTED_ROWS=$(grep -c . "${TEST_COMMANDS}")
if [ "${NUM_ROWS}" -ne "${EXPECTED_ROWS}" ]; then
  echo "ERROR: Expected ${EXPECTED_ROWS} rows, got ${NUM_ROWS}"
  exit 1
fi
# Using --iter 10, check column exists and has value 10
if ! grep -q "count (us)" "${OUTPUT_CSV}"; then
  echo "ERROR: 'count (us)' column not found in CSV"
  exit 1
fi
# Verify at least one row has count=10
if ! tail -n +2 "${OUTPUT_CSV}" | cut -d',' -f6 | grep -q "10"; then
  echo "ERROR: Expected count=10 not found"
  exit 1
fi
# There's a better way to indicate that the test has passed? Outside of just timeout in the CMake file?
echo "PASSED: batch_profile test"
rm -f "${OUTPUT_CSV}"
