"""
一键签名+扫描效果处理
合并自动签名和应用扫描效果为一个步骤
流程: 签章页 → 已签名 → 最终提交
"""
import os
import sys
import random
import io
from pathlib import Path

# 将项目根目录添加到 python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import fitz  # PyMuPDF
    from PIL import Image
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请运行: pip install PyMuPDF Pillow")
    sys.exit(1)

from config import BASE_DIR

# ==========================================
# 配置区
# ==========================================
SIGN_DIR = BASE_DIR / "签名"           # 签名图片目录
PDF_DIR = BASE_DIR / "签章页"          # 输入: 签章页PDF
TEMP_SIGNED_DIR = BASE_DIR / "已签名"  # 中间: 签名后的PDF
OUTPUT_DIR = BASE_DIR / "最终提交"     # 输出: 最终提交的PDF

# 签名参数
DPI = 300
SIGN_WIDTH_PX = 400
SIGN_HEIGHT_PX = 150
OFFSET_Y_PX = 100

# 扫描效果参数
SCAN_DPI = 200
# ==========================================


def sign_single_pdf(pdf_path: Path, sign_images: list, output_dir: Path) -> bool:
    """对单个PDF进行签名"""
    try:
        # 随机选一张签名
        sign_img_path = random.choice(sign_images)

        # 将PDF页面转换为高分辨率图片
        doc = fitz.open(pdf_path)
        page = doc[0]

        zoom = DPI / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        # 转换为PIL Image
        img_data = pix.tobytes("png")
        pdf_img = Image.open(io.BytesIO(img_data))

        # 查找"申请人签章"位置
        keyword = "申请人签章"
        rects = page.search_for(keyword)

        if not rects:
            print(f"      [跳过] 未找到关键字 '{keyword}'")
            doc.close()
            return False

        text_rect = rects[0]

        # 计算签名位置
        img_x0 = int(text_rect.x1 * zoom) + int(10 * zoom)
        img_y0 = int(text_rect.y0 * zoom)
        paste_x = img_x0
        paste_y = img_y0 - OFFSET_Y_PX

        # 加载并调整签名图片
        sign_img = Image.open(sign_img_path)
        sign_img = sign_img.resize((SIGN_WIDTH_PX, SIGN_HEIGHT_PX), Image.Resampling.LANCZOS)

        # 粘贴签名
        if sign_img.mode == 'RGBA':
            pdf_img.paste(sign_img, (paste_x, paste_y), sign_img)
        else:
            pdf_img.paste(sign_img, (paste_x, paste_y))

        # 转回PDF
        temp_img_path = output_dir / f"temp_signed_{pdf_path.stem}.png"
        pdf_img.save(temp_img_path, "PNG")

        # 创建新PDF
        output_doc = fitz.open()
        output_page = output_doc.new_page(width=page.rect.width, height=page.rect.height)
        output_page.insert_image(output_page.rect, filename=str(temp_img_path))

        # 保存
        save_path = output_dir / pdf_path.name
        output_doc.save(save_path)
        output_doc.close()
        doc.close()

        # 清理临时文件
        temp_img_path.unlink()

        return True

    except Exception as e:
        print(f"      [签名失败] {e}")
        return False


def apply_scan_effect(input_path: Path, output_path: Path) -> bool:
    """对PDF应用扫描效果"""
    try:
        from modules.pdf_tools.scanner_effect import convert_pdf_to_scanned
        return convert_pdf_to_scanned(str(input_path), str(output_path), dpi=SCAN_DPI)
    except Exception as e:
        print(f"      [扫描效果失败] {e}")
        return False


def batch_sign_and_scan(progress_callback=None, sign_dir=None):
    """
    一键签名+扫描效果处理

    Args:
        progress_callback: 可选的进度回调函数 (current, total, message)
        sign_dir: 可选的签名图片目录，默认使用 BASE_DIR / "签名"

    Returns:
        tuple: (success_count, total_count, output_dir)
    """
    # 使用传入的签名目录或默认目录
    actual_sign_dir = Path(sign_dir) if sign_dir else SIGN_DIR

    print(f"{'='*60}")
    print(f"[工具] 一键签名+扫描效果处理")
    print(f"{'='*60}")
    print(f"流程: 签章页 → 已签名 → 最终提交")
    print(f"签名目录: {actual_sign_dir}")
    print(f"{'='*60}")

    # 1. 准备目录
    TEMP_SIGNED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 2. 检查资源
    pdf_files = list(PDF_DIR.glob("*.pdf")) if PDF_DIR.exists() else []
    sign_images = []
    if actual_sign_dir.exists():
        sign_images = list(actual_sign_dir.glob("*.png")) + list(actual_sign_dir.glob("*.jpg"))

    if not pdf_files:
        print(f"[错误] 未在 {PDF_DIR} 找到 PDF 文件")
        return 0, 0, OUTPUT_DIR

    if not sign_images:
        print(f"[错误] 未在 {actual_sign_dir} 找到签名图片 (*.png, *.jpg)")
        return 0, 0, OUTPUT_DIR

    total = len(pdf_files)
    print(f"[资源] PDF数量: {total}, 签名图数量: {len(sign_images)}")
    print(f"{'-'*60}")

    success_count = 0
    skip_count = 0

    for i, pdf_path in enumerate(pdf_files):
        print(f"\n[{i+1}/{total}] 处理: {pdf_path.name}")

        if progress_callback:
            progress_callback(i, total, f"正在处理: {pdf_path.name}")

        # 检查是否已经处理过（最终提交目录已存在）
        final_output = OUTPUT_DIR / pdf_path.name
        if final_output.exists():
            print(f"      [跳过] 最终文件已存在")
            skip_count += 1
            success_count += 1
            continue

        # 步骤1: 签名
        print(f"      [1/2] 正在签名...")
        signed_path = TEMP_SIGNED_DIR / pdf_path.name

        # 检查是否已签名
        if signed_path.exists():
            print(f"      [1/2] 已签名文件存在，跳过签名步骤")
            sign_ok = True
        else:
            sign_ok = sign_single_pdf(pdf_path, sign_images, TEMP_SIGNED_DIR)

        if not sign_ok:
            print(f"      [失败] 签名失败，跳过此文件")
            continue

        # 步骤2: 扫描效果
        print(f"      [2/2] 正在应用扫描效果...")
        scan_ok = apply_scan_effect(signed_path, final_output)

        if scan_ok:
            print(f"      [成功] 已保存到: {final_output.name}")
            success_count += 1
        else:
            print(f"      [失败] 扫描效果应用失败")

    print(f"\n{'='*60}")
    print(f"[完成] 全部处理完毕")
    print(f"  成功: {success_count}/{total}")
    print(f"  跳过(已存在): {skip_count}")
    print(f"  失败: {total - success_count}")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"{'='*60}")

    if progress_callback:
        progress_callback(total, total, "处理完成")

    return success_count, total, OUTPUT_DIR


if __name__ == "__main__":
    batch_sign_and_scan()
