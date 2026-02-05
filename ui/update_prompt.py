from __future__ import annotations

import ctypes
from dataclasses import dataclass


@dataclass(frozen=True)
class UpdatePromptResult:
    action: str  # "update_now" | "remind_later" | "skip_version"


def _message_box(title: str, message: str, flags: int) -> int:
    user32 = ctypes.windll.user32
    return user32.MessageBoxW(0, message, title, flags)


def prompt_update(version: str, notes: str) -> UpdatePromptResult:
    """
    三选一提示：
    - 是：立即更新
    - 否：跳过此版本（直到下个版本再提示）
    - 取消：稍后提醒（默认 24 小时）
    """
    MB_YESNOCANCEL = 0x00000003
    MB_ICONINFORMATION = 0x00000040
    IDYES = 6
    IDNO = 7

    safe_notes = notes.strip()
    notes_block = f"\n\n更新说明：\n{safe_notes}" if safe_notes else ""
    message = (
        f"发现新版本：{version}\n\n"
        "是否现在一键更新？\n"
        "【是】立即更新  【否】跳过此版本  【取消】稍后提醒（24 小时）"
        f"{notes_block}"
    )
    result = _message_box("发现新版本", message, MB_YESNOCANCEL | MB_ICONINFORMATION)
    if result == IDYES:
        return UpdatePromptResult(action="update_now")
    if result == IDNO:
        return UpdatePromptResult(action="skip_version")
    return UpdatePromptResult(action="remind_later")

