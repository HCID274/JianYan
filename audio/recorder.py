from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import sounddevice as sd


@dataclass
class RecordingResult:
    pcm_bytes: Optional[bytes] = None
    temp_path: Optional[str] = None


class Recorder:
    def __init__(self, max_seconds: int, sample_rate: int = 16000) -> None:
        self.max_seconds = max_seconds
        self.sample_rate = sample_rate
        self._is_recording = False
        self._stream: Optional[sd.InputStream] = None
        self._chunks: list[bytes] = []
        self._max_frames = int(self.sample_rate * self.max_seconds)
        self._frames_written = 0

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            pass
        if not self._is_recording:
            raise sd.CallbackStop()
        self._chunks.append(indata.tobytes())
        self._frames_written += frames
        if self._frames_written >= self._max_frames:
            raise sd.CallbackStop()

    def start(self) -> None:
        if self._is_recording:
            return
        self._chunks = []
        self._frames_written = 0
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()
        self._is_recording = True

    def stop(self) -> RecordingResult:
        if not self._is_recording:
            return RecordingResult()
        self._is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        pcm_bytes = b"".join(self._chunks)
        return RecordingResult(pcm_bytes=pcm_bytes)
