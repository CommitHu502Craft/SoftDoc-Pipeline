import os
import sys
from pathlib import Path

# 将项目根目录添加到 python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from modules.pdf_tools.scanner_effect import convert_pdf_to_scanned

# 配置
INPUT_DIR = Path("已签名")
OUTPUT_DIR = Path("最终提交")
DPI_VALUE = 200 # 分辨率

def batch_process_scan_effect():
    print(f"{'='*60}")
    print(f"[工具] 批量 PDF 扫描特效处理器")
    print(f"{'='*60}")

    # 1. 准备目录
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True)
        print(f"[目录] 已创建输出目录: {OUTPUT_DIR}")
    else:
        print(f"[目录] 输出目录: {OUTPUT_DIR}")

    # 2. 获取源文件
    if not INPUT_DIR.exists():
        print(f"[错误] 输入目录不存在: {INPUT_DIR}")
        return

    pdf_files = list(INPUT_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"[错误] 输入目录下没有任何 PDF 文件")
        return

    print(f"[任务] 待处理文件数: {len(pdf_files)}")
    print(f"[配置] DPI: {DPI_VALUE}")
    print(f"{'-'*60}")

    success_count = 0

    for i, input_path in enumerate(pdf_files):
        filename = input_path.name
        output_path = OUTPUT_DIR / filename

        print(f"[{i+1}/{len(pdf_files)}] 正在处理: {filename}")

        # 调用转换函数
        result = convert_pdf_to_scanned(str(input_path), str(output_path), dpi=DPI_VALUE)

        if result:
            print(f"      [成功] 已保存")
            success_count += 1
        else:
            print(f"      [失败] 转换出错")

    print(f"{'='*60}")
    print(f"[完成] 全部处理完毕。成功: {success_count}/{len(pdf_files)}")
    print(f"文件保存在: {OUTPUT_DIR}")
    print(f"{'='*60}")

# 添加别名以保持兼容性
def batch_apply_scan_effect():
    """别名函数，用于GUI调用"""
    return batch_process_scan_effect()

if __name__ == "__main__":
    batch_process_scan_effect()
