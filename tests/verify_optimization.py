
import time
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from utils.image import create_progress_icon, _create_progress_icon_cached

def verify_optimization():
    # Sequence 1: 0.0 to 0.57 in 7.0s (10 steps per sec -> 70 steps)
    duration1 = 7.0
    start1, end1 = 0.0, 0.57
    steps1 = int(duration1 * 10)
    step_size1 = (end1 - start1) / steps1
    seq1 = [start1 + i * step_size1 for i in range(steps1)]

    # Sequence 2: 0.60 to 0.97 in 3.0s (30 steps)
    duration2 = 3.0
    start2, end2 = 0.60, 0.97
    steps2 = int(duration2 * 10)
    step_size2 = (end2 - start2) / steps2
    seq2 = [start2 + i * step_size2 for i in range(steps2)]

    full_sequence = seq1 + seq2
    iterations = 50

    print(f"Sequence length per iteration: {len(full_sequence)}")

    start_time = time.time()
    for _ in range(iterations):
        for p in full_sequence:
            create_progress_icon(p)
    end_time = time.time()

    total_calls = len(full_sequence) * iterations
    print(f"Total calls: {total_calls}")
    print(f"Total time: {end_time - start_time:.4f}s")

    # Check cache stats
    info = _create_progress_icon_cached.cache_info()
    print(f"Cache info: {info}")

    # Assertion: Cache hits should be high (near total_calls - 100)
    # 100 unique integer percentages max.
    if info.hits < (total_calls - 100):
        print("FAIL: Cache hits too low!")
        sys.exit(1)

    if info.misses > 100:
        print("FAIL: Cache misses too high!")
        sys.exit(1)

    print("SUCCESS: Optimization verified.")

if __name__ == "__main__":
    verify_optimization()
