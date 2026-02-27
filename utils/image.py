from __future__ import annotations
from functools import lru_cache
from PIL import Image, ImageDraw


def create_tray_icon(color: str) -> Image.Image:
    """创建纯色圆形图标"""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, size - 8, size - 8), fill=color)
    return image


def create_progress_icon(progress: float, size: int = 64) -> Image.Image:
    """创建带有圆弧进度条的图标

    Args:
        progress: 进度值 0.0 - 1.0
        size: 图标尺寸
    """
    percent = int(progress * 100)
    return _create_progress_icon_cached(percent, size)


@lru_cache(maxsize=128)
def _create_progress_icon_cached(percent: int, size: int) -> Image.Image:
    """内部缓存实现：根据百分比整数生成图标"""
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
    progress = percent / 100.0
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
    percent_text = f"{percent}"

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
