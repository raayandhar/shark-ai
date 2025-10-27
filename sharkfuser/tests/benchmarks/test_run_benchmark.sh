#!/bin/bash
set -e

# Arguments from CMake
RUN_BENCHMARK="$1"
DRIVER="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_COMMANDS="${SCRIPT_DIR}/test_commands.txt"
OUTPUT_CSV=$(mktemp)
python3 "${RUN_BENCHMARK}" \
  --commands-file "${TEST_COMMANDS}" \
  --csv "${OUTPUT_CSV}" \
  --driver "${DRIVER}"

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

echo "PASSED: batch_profile test"
rm -f "${OUTPUT_CSV}"
