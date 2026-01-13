#!/bin/bash

# 1. Create the output folder
mkdir -p fuzz_benchmarks

# 2. Define the path to the fuzzer (Now it is in THIS folder)
# We use "./" which means "look inside the current folder"
FUZZER=./aiger/aigfuzz

echo "🏭 Starting Fuzzing Factory in 'myThesis'..."

# Batch 1: Tiny Circuits
for i in {1..5}; do
   $FUZZER 4 0 1 10 > fuzz_benchmarks/tiny_$i.aag
done

# Batch 2: The Redundant Trap (For the demo)
$FUZZER 8 0 1 100 > fuzz_benchmarks/force_redundant.aag

echo "✅ Success! Benchmarks created in ~/myThesis/fuzz_benchmarks"

