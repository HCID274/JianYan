
## 2025-02-28 - Avoid soundfile WAV serialization loop
**Learning:** `soundfile.write` to `BytesIO` creates an unnecessary in-memory WAV file when the STT module just needs to load PCM bytes into a `float32` numpy array. For an 16kHz audio stream over 5 minutes, doubling the memory usage for a temporary WAV file, creating a large buffer object, and re-parsing that buffer using `soundfile.read()` causes huge CPU and memory overhead (~300+ ms overhead and multi-MB unnecessary allocations per transcription).
**Action:** When working with raw PCM bytes captured from a mic, decode them directly via `numpy.frombuffer(..., dtype=np.int16).astype(np.float32) / 32768.0` without formatting them as an intermediate WAV stream unless actually writing to disk.
