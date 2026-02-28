from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox

from utils.config import AppConfig


def show_settings_window(config: AppConfig) -> AppConfig:
    """显示设置窗口，直接创建独立的 Tk 实例
    
    在工作线程中创建 Tk 窗口需要使用 mainloop() 来处理事件。
    """
    logging.info("[Settings] 创建设置窗口...")
    result = {"config": config}
    
    try:
        root = tk.Tk()
        root.title("设置")
        root.resizable(False, False)
        logging.info("[Settings] Tk root 创建成功")
        
        # 直接在 root 上构建 UI，不使用 Toplevel
        _build_settings_ui(root, config, result)
        
        _center_window(root)
        logging.info("[Settings] 进入 mainloop...")
        root.mainloop()
        logging.info("[Settings] mainloop 已退出")
    except Exception as e:
        logging.exception("[Settings] 设置窗口出错: %s", e)
    
    return result["config"]


def _build_settings_ui(root: tk.Tk, config: AppConfig, result: dict) -> None:
    """直接在 root 窗口上构建设置 UI"""
    
    tk.Label(root, text="最大录音时长(秒)").grid(row=0, column=0, sticky="w", padx=10, pady=6)
    max_seconds_var = tk.StringVar(value=str(config.max_seconds))
    tk.Entry(root, textvariable=max_seconds_var, width=40).grid(row=0, column=1, padx=10, pady=6)

    tk.Label(root, text="更新源 latest.json（可选）").grid(row=1, column=0, sticky="w", padx=10, pady=6)
    update_urls_var = tk.StringVar(value=config.update_manifest_urls)
    tk.Entry(root, textvariable=update_urls_var, width=40).grid(row=1, column=1, padx=10, pady=6)
    tk.Label(root, text="多个地址用 ; 分隔，必须是 https。留空则使用内置默认源。", fg="#666666").grid(
        row=2, column=0, columnspan=3, sticky="w", padx=10, pady=4
    )

    tk.Label(root, text="OpenAI Base URL").grid(row=3, column=0, sticky="w", padx=10, pady=6)
    base_url_var = tk.StringVar(value=config.openai_base_url)
    tk.Entry(root, textvariable=base_url_var, width=40).grid(row=3, column=1, padx=10, pady=6)

    tk.Label(root, text="OpenAI API Key").grid(row=4, column=0, sticky="w", padx=10, pady=6)
    api_key_var = tk.StringVar(value=config.openai_api_key)
    api_key_entry = tk.Entry(root, textvariable=api_key_var, width=40, show="*")
    api_key_entry.grid(row=4, column=1, padx=10, pady=6)

    show_key_var = tk.BooleanVar(value=False)

    def toggle_key_visibility() -> None:
        api_key_entry.configure(show="" if show_key_var.get() else "*")

    tk.Checkbutton(root, text="显示", variable=show_key_var, command=toggle_key_visibility).grid(
        row=4, column=2, padx=0, pady=6
    )

    tk.Label(root, text="模型名").grid(row=5, column=0, sticky="w", padx=10, pady=6)
    qwen_model_var = tk.StringVar(value=config.qwen_model)
    tk.Entry(root, textvariable=qwen_model_var, width=40).grid(row=5, column=1, padx=10, pady=6)

    tk.Label(root, text="支持所有 OpenAI 兼容服务，推荐使用 Qwen。", fg="#666666").grid(
        row=6, column=0, columnspan=3, sticky="w", padx=10, pady=4
    )

    def _test_connection() -> None:
        base_url = base_url_var.get().strip()
        api_key = api_key_var.get().strip()
        model = qwen_model_var.get().strip() or config.qwen_model
        if not base_url or not api_key:
            messagebox.showerror("错误", "请先填写 OpenAI Base URL 和 API Key", parent=root)
            return

        def _worker() -> None:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key, base_url=base_url)
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )

                def _on_success() -> None:
                    test_btn.config(state="normal", text="测试连接")
                    messagebox.showinfo("测试成功", "连接正常，API Key 有效", parent=root)
                root.after(0, _on_success)
            except Exception as exc:
                err = str(exc)

                def _on_error() -> None:
                    test_btn.config(state="normal", text="测试连接")
                    messagebox.showerror("测试失败", err, parent=root)
                root.after(0, _on_error)

        test_btn.config(state="disabled", text="测试中...")
        threading.Thread(target=_worker, daemon=True).start()

    def on_save() -> None:
        try:
            max_seconds = int(max_seconds_var.get().strip())
            if max_seconds <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "最大录音时长必须是正整数", parent=root)
            return

        base_url = base_url_var.get().strip()
        api_key = api_key_var.get().strip()

        if not base_url or not api_key:
            messagebox.showerror("错误", "请填写 OpenAI Base URL 和 API Key", parent=root)
            return

        result["config"] = AppConfig(
            hotkey=config.hotkey,
            max_seconds=max_seconds,
            temp_dir=config.temp_dir,
            model_cache_dir=config.model_cache_dir,
            update_manifest_urls=update_urls_var.get().strip(),
            openai_base_url=base_url,
            openai_api_key=api_key,
            qwen_model=qwen_model_var.get().strip() or config.qwen_model,
            suppress_missing_llm_prompt=config.suppress_missing_llm_prompt,
            show_hotkey_hint_on_startup=config.show_hotkey_hint_on_startup,
        )
        root.destroy()

    def on_cancel() -> None:
        root.destroy()

    test_btn = tk.Button(root, text="测试连接", command=_test_connection, width=10)
    test_btn.grid(row=7, column=0, padx=10, pady=10)
    tk.Button(root, text="保存", command=on_save, width=10).grid(row=7, column=1, padx=10, pady=10, sticky="e")
    tk.Button(root, text="取消", command=on_cancel, width=10).grid(row=7, column=2, padx=10, pady=10, sticky="e")


def _center_window(root: tk.Tk) -> None:
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = max((screen_width - width) // 2, 0)
    y = max((screen_height - height) // 2, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")
