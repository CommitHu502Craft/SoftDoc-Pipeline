import fitz  # PyMuPDF
import os
import random
from pathlib import Path
from PIL import Image
import io

# 配置
SIGN_DIR = Path("签名")
PDF_DIR = Path("签章页")
OUTPUT_DIR = Path("已签名")

# 签名参数
DPI = 300  # 转换PDF为图片的DPI
SIGN_WIDTH_PX = 400  # 签名宽度（像素，在300 DPI下）
SIGN_HEIGHT_PX = 150  # 签名高度（像素，在300 DPI下）
OFFSET_Y_PX = 100  # 签名往上移动的像素数

def batch_sign_pdfs():
    print(f"{'='*60}")
    print(f"[工具] 批量自动签名工具（图片方法）")
    print(f"{'='*60}")

    # 1. 准备目录
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True)

    # 2. 获取资源
    pdf_files = list(PDF_DIR.glob("*.pdf"))
    sign_images = list(SIGN_DIR.glob("*.png")) + list(SIGN_DIR.glob("*.jpg"))

    if not pdf_files:
        print(f"[错误] 未在 {PDF_DIR} 找到 PDF 文件")
        return
    if not sign_images:
        print(f"[错误] 未在 {SIGN_DIR} 找到签名图片")
        return

    print(f"[资源] PDF数量: {len(pdf_files)}, 签名图数量: {len(sign_images)}")
    print(f"[配置] DPI: {DPI}, 签名尺寸: {SIGN_WIDTH_PX}x{SIGN_HEIGHT_PX}px")
    print(f"{'-'*60}")

    success_count = 0

    for i, pdf_path in enumerate(pdf_files):
        try:
            print(f"[{i+1}/{len(pdf_files)}] 正在处理: {pdf_path.name}")

            # 随机选一张签名
            sign_img_path = random.choice(sign_images)

            # === 步骤1: 将PDF页面转换为高分辨率图片 ===
            doc = fitz.open(pdf_path)
            page = doc[0]

            zoom = DPI / 72  # 72是默认DPI
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # 转换为PIL Image
            img_data = pix.tobytes("png")
            pdf_img = Image.open(io.BytesIO(img_data))

            # === 步骤2: 在PDF中查找"申请人签章"位置 ===
            keyword = "申请人签章"
            rects = page.search_for(keyword)

            if not rects:
                print(f"      [跳过] 未找到关键字 '{keyword}'")
                doc.close()
                continue

            text_rect = rects[0]

            # === 步骤3: 计算签名在图片中的位置 ===
            # 转换PDF坐标到图片坐标
            img_x0 = int(text_rect.x1 * zoom) + int(10 * zoom)  # 关键字右边
            img_y0 = int(text_rect.y0 * zoom)

            # 往上移动
            paste_x = img_x0
            paste_y = img_y0 - OFFSET_Y_PX

            # === 步骤4: 加载并调整签名图片 ===
            sign_img = Image.open(sign_img_path)

            # 调整签名大小
            sign_img = sign_img.resize((SIGN_WIDTH_PX, SIGN_HEIGHT_PX), Image.Resampling.LANCZOS)

            # === 步骤5: 将签名粘贴到PDF图片上 ===
            if sign_img.mode == 'RGBA':
                pdf_img.paste(sign_img, (paste_x, paste_y), sign_img)
            else:
                pdf_img.paste(sign_img, (paste_x, paste_y))

            # === 步骤6: 将合成后的图片转回PDF ===
            temp_img_path = Path(f"temp_signed_{i}.png")
            pdf_img.save(temp_img_path, "PNG")

            # 创建新PDF
            output_doc = fitz.open()
            output_page = output_doc.new_page(width=page.rect.width, height=page.rect.height)
            output_page.insert_image(output_page.rect, filename=str(temp_img_path))

            # 保存
            save_path = OUTPUT_DIR / pdf_path.name
            output_doc.save(save_path)
            output_doc.close()
            doc.close()

            # 清理临时文件
            temp_img_path.unlink()

            print(f"      [成功] 已保存到: {save_path}")
            success_count += 1

        except Exception as e:
            print(f"      [失败] 处理出错: {e}")
            import traceback
            traceback.print_exc()

    print(f"{'='*60}")
    print(f"[完成] 全部处理完毕。成功: {success_count}/{len(pdf_files)}")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"{'='*60}")

if __name__ == "__main__":
    batch_sign_pdfs()
