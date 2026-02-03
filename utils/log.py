from __future__ import annotations

import logging



from pathlib import Path
import sys

def setup_logging() -> None:
    # 确保日志文件写在应用根目录（方便查找）
    log_file = Path(sys.executable).parent / "run.log" if getattr(sys, 'frozen', False) else Path("run.log")
    
    handlers = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except Exception:
        pass # 如果没权限写文件，至少保留控制台输出

    logging.basicConfig(
        level=logging.INFO, 
        format="[%(asctime)s] %(levelname)s %(message)s",
        handlers=handlers,
        force=True
    )

