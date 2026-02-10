#!/usr/bin/env python3
"""
检查系统可用的中文字体
"""

import subprocess
import os

def check_chinese_fonts():
    """检查系统中可用的中文字体"""
    print("=" * 60)
    print("系统中文字体检查")
    print("=" * 60)

    # 常见中文字体路径
    common_fonts = [
        ("文泉驿正黑", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ("文泉驿微米黑", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        ("Noto Sans CJK", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        ("Droid Sans Fallback", "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    ]

    print("\n1. 检查常见中文字体文件：")
    found_fonts = []
    for name, path in common_fonts:
        if os.path.exists(path):
            print(f"  ✓ {name}: {path}")
            found_fonts.append((name, path))
        else:
            print(f"  ✗ {name}: {path} (不存在)")

    print("\n2. 使用 fc-list 搜索所有中文字体：")
    try:
        result = subprocess.run(['fc-list', ':lang=zh'], capture_output=True, text=True)
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            print(f"  找到 {len(lines)} 个中文字体：")
            for line in lines[:10]:  # 只显示前10个
                print(f"    {line}")
            if len(lines) > 10:
                print(f"    ... 还有 {len(lines) - 10} 个字体")
        else:
            print("  未找到中文字体")
    except Exception as e:
        print(f"  错误: {e}")

    print("\n3. 推荐使用的字体：")
    if found_fonts:
        for name, path in found_fonts:
            print(f"  - {name}: {path}")
    else:
        print("  未找到中文字体，建议安装：")
        print("    sudo apt-get install -y fonts-wqy-zenhei fonts-wqy-microhei")

    print("\n" + "=" * 60)

    return found_fonts

if __name__ == "__main__":
    check_chinese_fonts()