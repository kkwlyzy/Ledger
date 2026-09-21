"""一次性安装脚本：生成软件图标、启动脚本、桌面快捷方式。

使用：python make_shortcut.py
重复运行是幂等的，会覆盖旧图标与快捷方式。
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent
ICON_PATH = ROOT / "data" / "app.ico"
LAUNCHER_PATH = ROOT / "launch.bat"


def make_icon() -> Path:
    """用 Pillow 生成 ¥ 主题图标，保存为多尺寸 .ico。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[skip] Pillow 未安装，跳过图标生成")
        return Path("")

    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    size = 256
    img = Image.new("RGBA", (size, size), (44, 62, 80, 255))  # 深蓝 #2c3e50
    draw = ImageDraw.Draw(img)

    # 画一个圆形高亮区
    cx, cy, r = size // 2, size // 2, size // 2 - 12
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=(52, 152, 219, 255),  # #3498db
    )

    # 写 ¥ 符号
    text = "¥"
    font_size = 160
    font = None
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    # 计算文本居中
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(text, font=font)
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1] - 6
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    img.save(
        ICON_PATH,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"[ok] 图标已生成: {ICON_PATH}")
    return ICON_PATH


def make_launcher() -> Path:
    """创建无黑窗启动脚本。"""
    # 用 pythonw.exe 启动，避免弹出命令行窗口
    LAUNCHER_PATH.write_text(
        '@echo off\r\n'
        f'cd /d "{ROOT}"\r\n'
        'start "" pythonw main.py\r\n',
        encoding="ascii",
    )
    print(f"[ok] 启动脚本已生成: {LAUNCHER_PATH}")
    return LAUNCHER_PATH


def make_desktop_shortcut(icon: Path, launcher: Path) -> None:
    """通过 PowerShell + WScript.Shell 创建桌面快捷方式。"""
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
    if not desktop.exists():
        # 中文 Windows 桌面路径兜底
        desktop = Path(os.environ["USERPROFILE"]) / "桌面"
    lnk = desktop / "记账本.lnk"
    icon_str = str(icon) if icon.exists() else ""
    launcher_str = str(launcher)
    root_str = str(ROOT)
    lnk_str = str(lnk).replace("'", "''")

    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$s = $ws.CreateShortcut('{lnk_str}');"
        f"$s.TargetPath = '{launcher_str}';"
        f"$s.WorkingDirectory = '{root_str}';"
        f"$s.IconLocation = '{icon_str},0';"
        f"$s.Description = '基于 PySide6 的本地记账软件';"
        "$s.Save();"
        "Write-Output 'shortcut_saved';"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="gbk",
        errors="replace",
    )
    if result.returncode == 0 and "shortcut_saved" in result.stdout:
        print(f"[ok] 桌面快捷方式已创建: {lnk}")
    else:
        print("[error] 创建快捷方式失败")
        print("stdout:", result.stdout)
        print("stderr:", result.stderr)


def main() -> int:
    print("=== 开始安装记账本桌面图标 ===")
    icon = make_icon()
    launcher = make_launcher()
    make_desktop_shortcut(icon, launcher)
    print("=== 完成。双击桌面「记账本」即可启动应用 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
