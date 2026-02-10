from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

import pystray
from PIL import Image, ImageDraw

from api.llm import clean_text, preprocess_text
from api.stt import preload_model, transcribe_audio
from app.state import AppState
from audio.recorder import Recorder, RecordingResult
from hotkey.listener import start_hotkey_listener, stop_hotkey_listener
from output.paste import write_clipboard, write_clipboard_and_paste
from ui.llm_prompt import show_llm_auth_error_dialog, show_missing_llm_config_dialog
from ui.update_prompt import prompt_update
from ui.settings import show_settings_window
from utils.config import AppConfig, save_config
from utils.notify import notify
from utils.sounds import play_busy_sound, play_processing_sound, play_start_sound, play_stop_sound
from utils.updater import (
    download_package,
    fetch_latest_update_info,
    launch_silent_installer,
    load_update_state,
    save_update_state,
    should_prompt_update,
)


class TrayApp:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._recorder = Recorder(max_seconds=state.config.max_seconds)
        self._llm_prompt_open = False
        self._settings_open = False
        Path(state.config.temp_dir).mkdir(parents=True, exist_ok=True)

        self._icons = {
            "idle": _create_icon("#35a853"),
            "recording": _create_icon("#d93025"),
            "busy": _create_icon("#f9ab00"),
        }
        self.icon = pystray.Icon(
            "audio_to_text",
            self._icons["idle"],
            self._build_tray_title(),
            menu=self._build_menu(),
        )

    def _build_tray_title(self) -> str:
        hotkey_label = _format_hotkey_for_display(self.state.config.hotkey)
        if hotkey_label:
            return f"语音转文字 ({hotkey_label})"
        return "语音转文字"

    def _build_menu(self) -> pystray.Menu:
        hotkey_label = _format_hotkey_for_display(self.state.config.hotkey)
        toggle_label = "开始/停止录音"
        if hotkey_label:
            toggle_label = f"{toggle_label} ({hotkey_label})"

        return pystray.Menu(
            pystray.MenuItem(toggle_label, self._on_toggle),
            pystray.MenuItem(
                "复制原始文本",
                self._on_copy_raw,
                enabled=lambda item: bool(self.state.last_raw_text),
            ),
            pystray.MenuItem(
                "复制整理文本",
                self._on_copy_clean,
                enabled=lambda item: bool(self.state.last_clean_text),
            ),
            pystray.MenuItem("设置", self._on_settings),
            pystray.MenuItem("检查更新", self._on_check_update),
            pystray.MenuItem("退出", self._on_exit),
        )

    def _refresh_hotkey_ui(self) -> None:
        try:
            self.icon.title = self._build_tray_title()
            self.icon.menu = self._build_menu()
            self.icon.update_menu()
        except Exception:
            logging.debug("[TrayApp] 刷新热键 UI 失败", exc_info=True)

    def _maybe_show_hotkey_hint(self) -> None:
        if not self.state.config.show_hotkey_hint_on_startup:
            return

        hotkey_label = _format_hotkey_for_display(self.state.config.hotkey)
        if hotkey_label:
            notify("快捷键提示", f"按 {hotkey_label} 开始/停止录音")
        else:
            notify("快捷键提示", "可在配置中设置快捷键")

        try:
            self.state.config.show_hotkey_hint_on_startup = False
            save_config(self.state.config)
        except Exception:
            logging.debug("[TrayApp] 写入快捷键提示状态失败", exc_info=True)

    def run(self) -> None:
        logging.info("[TrayApp] 应用启动...")
        try:
            start_hotkey_listener(self.toggle_recording, self.state.config.hotkey)
            logging.info("[TrayApp] 快捷键监听已启动: %s", self.state.config.hotkey)
            self._refresh_hotkey_ui()
            self._maybe_show_hotkey_hint()
        except Exception as exc:
            logging.exception("[TrayApp] 注册热键失败")
            notify("快捷键错误", f"注册热键失败: {exc}")

        if not self.state.model_ready and not self.state.model_error:
            self._start_model_preload()

        self._start_update_check(force_prompt=False)

        logging.info("[TrayApp] 开始运行托盘图标...")
        self.icon.run()

    def _start_update_check(self, *, force_prompt: bool) -> None:
        def _runner() -> None:
            try:
                self._check_for_updates(force_prompt=force_prompt)
            except Exception:
                logging.exception("[Updater] 更新检查失败")

        threading.Thread(target=_runner, daemon=True).start()

    def _check_for_updates(self, *, force_prompt: bool) -> None:
        state = load_update_state()
        info = fetch_latest_update_info()
        state.last_checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_update_state(state)

        if not info:
            if force_prompt:
                notify("检查更新", "暂时无法连接更新服务器")
            return

        if not should_prompt_update(info, state, force_prompt=force_prompt):
            if force_prompt:
                notify("检查更新", "当前已是最新版本")
            return

        result = prompt_update(info.version, info.notes)
        if result.action == "skip_version":
            state.skip_version = info.version
            state.remind_at = None
            save_update_state(state)
            return
        if result.action == "remind_later":
            # 默认 24 小时后再提示
            remind_ts = time.time() + 24 * 60 * 60
            state.remind_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(remind_ts))
            save_update_state(state)
            return

        try:
            installer = download_package(info.update_pkg, info.version, "update")
        except Exception as exc:
            logging.exception("[Updater] 下载更新包失败")
            notify("更新失败", f"下载更新包失败: {exc}")
            return

        try:
            notify("正在更新", "将自动安装新版本并重启")
            launch_silent_installer(installer)
        except Exception as exc:
            logging.exception("[Updater] 启动安装包失败")
            notify("更新失败", f"启动安装包失败: {exc}")
            return

        # 退出当前实例，避免文件占用导致更新失败
        self._exit_app()

    def toggle_recording(self) -> None:
        logging.info("[TrayApp] toggle_recording 被调用")
        logging.info("[TrayApp] 当前状态: is_recording=%s, is_busy=%s", 
                     self.state.is_recording, self.state.is_busy)
        with self._lock:
            logging.info("[TrayApp] 获取锁成功")
            if self.state.is_busy:
                logging.info("[TrayApp] 状态为忙碌，播放忙碌音效")
                play_busy_sound()
                return
            if not self.state.model_ready:
                if self.state.model_error:
                    notify("模型不可用", self.state.model_error)
                else:
                    notify("模型加载中", "请稍候再试")
                play_busy_sound()
                return
            if not self.state.is_recording:
                logging.info("[TrayApp] 开始录音...")
                self._start_recording()
            else:
                logging.info("[TrayApp] 停止录音并处理...")
                self._stop_and_process()
        logging.info("[TrayApp] toggle_recording 完成")

    def _start_recording(self) -> None:
        logging.info("[TrayApp] _start_recording 进入")
        if self.state.is_recording:
            logging.warning("[TrayApp] 已经在录音中，跳过")
            return
        self.state.is_recording = True
        try:
            logging.info("[TrayApp] 调用 recorder.start()...")
            self._recorder.start()
            logging.info("[TrayApp] recorder.start() 完成")
        except Exception as exc:
            logging.exception("[TrayApp] 录音启动失败")
            self.state.is_recording = False
            notify("录音失败", str(exc))
            return

        self._update_icon()
        logging.info("[TrayApp] 播放开始音效...")
        play_start_sound()
        self._timer = threading.Timer(self.state.config.max_seconds, self._auto_stop)
        self._timer.daemon = True
        self._timer.start()
        logging.info("[TrayApp] 录音已开始，定时器已设置 (%ds)", self.state.config.max_seconds)

    def _stop_and_process(self) -> None:
        logging.info("[TrayApp] _stop_and_process 进入")
        if not self.state.is_recording:
            logging.warning("[TrayApp] 没有在录音，跳过")
            return
        self.state.is_recording = False
        if self._timer:
            self._timer.cancel()
            self._timer = None

        logging.info("[TrayApp] 调用 recorder.stop()...")
        result = self._recorder.stop()
        logging.info("[TrayApp] recorder.stop() 完成, wav_bytes 大小: %d", 
                     len(result.wav_bytes) if result.wav_bytes else 0)
        self._update_icon()
        play_stop_sound()

        worker = threading.Thread(
            target=self._process_recording,
            args=(result,),
            daemon=True,
        )
        worker.start()
        logging.info("[TrayApp] 处理线程已启动")

    def _auto_stop(self) -> None:
        logging.info("[TrayApp] _auto_stop 被调用 (录音超时)")
        with self._lock:
            if self.state.is_recording:
                self._stop_and_process()

    def _process_recording(self, result: RecordingResult) -> None:
        with self._lock:
            self.state.is_busy = True
        
        # 开始处理 - 显示 0% 进度
        self._update_progress(0.0)
        play_processing_sound()

        # ========== 阶段1: 语音转文字 (0% -> 57%) ==========
        # 启动假进度动画 (7秒内从 0% 跑到 57%)
        progress_stop = threading.Event()
        progress_thread = threading.Thread(
            target=self._animate_progress,
            args=(0.0, 0.57, 7.0, progress_stop),
            daemon=True
        )
        progress_thread.start()
        
        try:
            raw_text = transcribe_audio(result.wav_bytes, result.temp_path, self.state.config).strip()
            # 本地预处理：去除连续重复的标点符号
            raw_text = preprocess_text(raw_text)
            # 避免在日志中记录用户的转写内容（可能包含敏感信息）
            logging.info("[TrayApp] 转写完成, 文本长度=%d", len(raw_text) if raw_text else 0)
        except Exception as exc:
            logging.exception("转写失败")
            progress_stop.set()
            notify("转写失败", str(exc))
            with self._lock:
                self.state.is_busy = False
            self._update_icon()
            return
        finally:
            progress_stop.set()
            progress_thread.join(timeout=0.5)

        # 转写完成 - 跳到 60%（留 3% 空隙）
        self._update_progress(0.60)

        with self._lock:
            self.state.last_raw_text = raw_text or None

        if not raw_text:
            logging.warning("[TrayApp] 转写结果为空")
            notify("转写完成", "未识别到有效文本")
            with self._lock:
                self.state.is_busy = False
            self._update_icon()
            return

        # ========== 阶段2: AI 整理 (60% -> 97%) ==========
        # 启动假进度动画 (3秒内从 60% 跑到 97%)
        progress_stop = threading.Event()
        progress_thread = threading.Thread(
            target=self._animate_progress,
            args=(0.60, 0.97, 3.0, progress_stop),
            daemon=True
        )
        progress_thread.start()
        
        clean_text_result = raw_text
        try:
            clean_text_result = clean_text(raw_text, self.state.config).strip() or raw_text
            # 避免在日志中记录用户内容
            logging.info("[TrayApp] LLM 整理完成, 文本长度=%d", len(clean_text_result) if clean_text_result else 0)
        except Exception as exc:
            logging.exception("LLM 整理失败")
            if "Missing Qwen Base URL or API Key" in str(exc):
                self._handle_missing_llm_config()
            elif "invalid_api_key" in str(exc) or "401" in str(exc):
                self._handle_llm_auth_error(str(exc))
            else:
                notify("整理失败", str(exc))
        finally:
            progress_stop.set()
            progress_thread.join(timeout=0.5)

        # AI 整理完成 - 跳到 100%
        self._update_progress(1.0)

        with self._lock:
            self.state.last_clean_text = clean_text_result
        
        # 阶段3: 粘贴
        logging.info("[TrayApp] 开始写入剪贴板并粘贴...")
        write_clipboard_and_paste(clean_text_result)
        
        logging.info("[TrayApp] 粘贴操作完成")
        notify("转写完成", "文本已粘贴")

        with self._lock:
            self.state.is_busy = False
        self._update_icon()
        
        # 刷新菜单，使"复制原始文本"和"复制整理文本"选项变为可用
        try:
            self.icon.update_menu()
            logging.info("[TrayApp] 菜单已刷新")
        except Exception as e:
            logging.debug("[TrayApp] 刷新菜单失败: %s", e)

    def _start_model_preload(self) -> None:
        worker = threading.Thread(target=self._preload_model, daemon=True)
        worker.start()

    def _preload_model(self) -> None:
        try:
            preload_model(self.state.config)
            self.state.model_ready = True
            notify("模型就绪", "本地语音模型已加载完成")
        except Exception as exc:
            self.state.model_error = str(exc)
            notify("模型加载失败", str(exc))
    
    def _animate_progress(self, start: float, end: float, duration: float, stop_event: threading.Event) -> None:
        """假进度动画：在 duration 秒内从 start 跑到 end
        
        Args:
            start: 起始进度 (0.0 - 1.0)
            end: 结束进度 (0.0 - 1.0)
            duration: 持续时间 (秒)
            stop_event: 停止事件
        """
        import time
        steps = int(duration * 10)  # 每 100ms 更新一次
        step_size = (end - start) / steps
        current = start
        
        for _ in range(steps):
            if stop_event.is_set():
                return
            current += step_size
            self._update_progress(min(current, end))
            time.sleep(0.1)

    def _on_toggle(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self.toggle_recording()

    def _on_copy_raw(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self.state.last_raw_text:
            write_clipboard(self.state.last_raw_text)
            notify("已复制", "原始文本已复制到剪贴板")

    def _on_copy_clean(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self.state.last_clean_text:
            write_clipboard(self.state.last_clean_text)
            notify("已复制", "整理文本已复制到剪贴板")

    def _on_settings(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        logging.info("[TrayApp] _on_settings 被调用")
        if self.state.is_recording or self.state.is_busy:
            logging.info("[TrayApp] 正在录音或处理中，无法打开设置")
            notify("无法设置", "正在录音或处理中")
            return

        self._open_settings_window()

    def _on_exit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._exit_app()

    def _exit_app(self) -> None:
        stop_hotkey_listener()
        if self.state.is_recording:
            try:
                self._recorder.stop()
            except Exception:
                logging.exception("停止录音失败")
        try:
            self.icon.stop()
        except Exception:
            pass

    def _on_check_update(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._start_update_check(force_prompt=True)

    def _handle_missing_llm_config(self) -> None:
        if self.state.config.suppress_missing_llm_prompt:
            return
        if self._llm_prompt_open:
            return
        self._llm_prompt_open = True
        try:
            dont_remind, open_settings = show_missing_llm_config_dialog()
        finally:
            self._llm_prompt_open = False
        if dont_remind:
            self.state.config.suppress_missing_llm_prompt = True
            save_config(self.state.config)
        if open_settings:
            self._open_settings_window()

    def _handle_llm_auth_error(self, message: str) -> None:
        if self._llm_prompt_open:
            return
        self._llm_prompt_open = True

        def _runner() -> None:
            try:
                show_llm_auth_error_dialog(message)
            finally:
                self._llm_prompt_open = False

        threading.Thread(target=_runner, daemon=True).start()

    def _open_settings_window(self) -> None:
        logging.info("[TrayApp] _open_settings_window 被调用, _settings_open=%s", self._settings_open)
        if self._settings_open:
            logging.info("[TrayApp] 设置窗口已打开，跳过")
            return
        self._settings_open = True

        def _runner() -> None:
            logging.info("[TrayApp] 设置窗口线程开始运行")
            try:
                new_config = show_settings_window(self.state.config)
                logging.info("[TrayApp] 设置窗口已关闭，应用新配置")
                self._apply_new_config(new_config)
            except Exception as e:
                logging.exception("[TrayApp] 设置窗口出错: %s", e)
            finally:
                self._settings_open = False
                logging.info("[TrayApp] 设置窗口线程结束")

        threading.Thread(target=_runner, daemon=True).start()
        logging.info("[TrayApp] 设置窗口线程已启动")

    def _apply_new_config(self, new_config: AppConfig) -> None:
        if new_config == self.state.config:
            return

        self.state.config = new_config
        save_config(new_config)
        self._recorder = Recorder(max_seconds=new_config.max_seconds)
        Path(new_config.temp_dir).mkdir(parents=True, exist_ok=True)
        try:
            start_hotkey_listener(self.toggle_recording, new_config.hotkey)
        except Exception as exc:
            notify("快捷键错误", f"注册热键失败: {exc}")
        self._refresh_hotkey_ui()

    def _update_icon(self) -> None:
        """更新托盘图标（不获取锁，因为可能在锁内被调用）"""
        # 直接读取状态，Python 的属性读取是原子的
        is_recording = self.state.is_recording
        is_busy = self.state.is_busy
        
        if is_recording:
            self.icon.icon = self._icons["recording"]
        elif is_busy:
            self.icon.icon = self._icons["busy"]
        else:
            self.icon.icon = self._icons["idle"]
    
    def _update_progress(self, progress: float) -> None:
        """更新进度图标 (0.0 - 1.0)"""
        try:
            self.icon.icon = _create_progress_icon(progress)
        except Exception as e:
            logging.debug("[TrayApp] 更新进度图标失败: %s", e)


def _create_icon(color: str) -> Image.Image:
    """创建纯色圆形图标"""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, size - 8, size - 8), fill=color)
    return image


def _create_progress_icon(progress: float, size: int = 64) -> Image.Image:
    """创建带有圆弧进度条的图标
    
    Args:
        progress: 进度值 0.0 - 1.0
        size: 图标尺寸
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 外圈边距
    margin = 4
    # 进度条宽度 (粗圆弧，约占半径的三分之二)
    arc_width = 18
    
    # 背景圆环 (灰色)
    draw.ellipse(
        (margin, margin, size - margin, size - margin),
        outline="#3a3a3a",
        width=arc_width
    )
    
    # 内圆填充 (深色)
    inner_margin = margin + arc_width
    draw.ellipse(
        (inner_margin, inner_margin, size - inner_margin, size - inner_margin),
        fill="#2a2a2a"
    )
    
    # 进度圆弧 (渐变色: 蓝->绿)
    if progress > 0:
        # 从顶部开始 (-90度)，顺时针方向
        start_angle = -90
        end_angle = start_angle + (progress * 360)
        
        # 根据进度变色: 0%-50% 蓝色渐变到青色, 50%-100% 青色渐变到绿色
        if progress < 0.5:
            # 蓝 -> 青
            r = int(59 + (0 - 59) * (progress * 2))
            g = int(130 + (200 - 130) * (progress * 2))
            b = int(246 + (200 - 246) * (progress * 2))
        else:
            # 青 -> 绿
            r = int(0 + (53 - 0) * ((progress - 0.5) * 2))
            g = int(200 + (168 - 200) * ((progress - 0.5) * 2))
            b = int(200 + (83 - 200) * ((progress - 0.5) * 2))
        
        progress_color = f"#{r:02x}{g:02x}{b:02x}"
        
        draw.arc(
            (margin, margin, size - margin, size - margin),
            start=start_angle,
            end=end_angle,
            fill=progress_color,
            width=arc_width
        )
    
    # 中心百分比文字
    percent_text = f"{int(progress * 100)}"
    
    # 使用默认字体，调整位置使其居中
    # 简单居中：对于2位数和3位数做不同处理
    if len(percent_text) == 1:
        text_x = size // 2 - 4
    elif len(percent_text) == 2:
        text_x = size // 2 - 7
    else:
        text_x = size // 2 - 10
    text_y = size // 2 - 6
    
    draw.text((text_x, text_y), percent_text, fill="#ffffff")
    
    return image


def _format_hotkey_for_display(hotkey: str) -> str:
    if not hotkey:
        return ""

    tokens = [t.strip().lower() for t in hotkey.split("+") if t.strip()]
    if not tokens:
        return ""

    has_ctrl = False
    has_shift = False
    has_alt = False
    has_win = False
    keys: list[str] = []

    key_map = {
        "space": "Space",
        "tab": "Tab",
        "enter": "Enter",
        "return": "Enter",
        "esc": "Esc",
        "escape": "Esc",
        "backspace": "Backspace",
        "delete": "Delete",
        "del": "Delete",
        "insert": "Insert",
        "ins": "Insert",
        "home": "Home",
        "end": "End",
        "pageup": "PageUp",
        "pgup": "PageUp",
        "pagedown": "PageDown",
        "pgdn": "PageDown",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
    }

    for t in tokens:
        if t in {"ctrl", "control"}:
            has_ctrl = True
            continue
        if t == "shift":
            has_shift = True
            continue
        if t in {"alt", "menu"}:
            has_alt = True
            continue
        if t in {"win", "windows"}:
            has_win = True
            continue

        if t in key_map:
            keys.append(key_map[t])
            continue

        if len(t) == 1 and t.isalnum():
            keys.append(t.upper())
            continue

        if t.startswith("f") and t[1:].isdigit():
            n = int(t[1:])
            if 1 <= n <= 24:
                keys.append(f"F{n}")
                continue

        keys.append(t)

    parts: list[str] = []
    if has_ctrl:
        parts.append("Ctrl")
    if has_shift:
        parts.append("Shift")
    if has_alt:
        parts.append("Alt")
    if has_win:
        parts.append("Win")

    parts.extend(keys)
    return "+".join(parts)


def run_tray(state: AppState) -> None:
    TrayApp(state).run()
