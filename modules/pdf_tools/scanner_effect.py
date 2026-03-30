import sys
import os
import shutil
import random
import numpy as np
from PIL import Image, ImageFilter, ImageChops
from pdf2image import convert_from_path

def check_poppler_dependency():
    """
    检查系统路径中是否存在 Poppler 工具 (pdftoppm)
    """
    if not shutil.which("pdftoppm"):
        print("=" * 60)
        print("[错误] 未检测到 Poppler 环境！")
        print("=" * 60)
        print("`pdf2image` 库需要依赖 Poppler 才能运行。请根据您的操作系统进行安装：\n")

        print("【Windows 用户】")
        print("1. 访问 https://github.com/oschwartz10612/poppler-windows/releases/ 下载最新压缩包")
        print("2. 解压文件，并将解压目录下的 'bin' 文件夹路径添加到系统的 '环境变量 PATH' 中")
        print("3. 重启命令行窗口重试\n")

        print("【Mac 用户】")
        print("执行命令: brew install poppler\n")

        print("【Linux 用户】")
        print("执行命令: sudo apt-get install poppler-utils\n")
        print("=" * 60)
        sys.exit(1)

def apply_scanner_effect_to_image(image):
    """
    对单张图片应用扫描仪特效：灰度 -> 随机倾斜 -> 模糊 -> 噪点
    """
    # 1. 灰度化 (Grayscale)
    img = image.convert('L')

    # 2. 随机倾斜 (Skew) -0.5 到 0.5 度 (恢复微小角度)
    angle = random.uniform(-0.5, 0.5)
    # resample=Image.BICUBIC 保证旋转质量
    # fillcolor=255 保证旋转后的空隙填充为白色
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)

    # --- 新增：模拟纸张褶皱 (明暗阴影) ---
    # 原理：生成一张低频噪声图，模拟纸张表面的大块明暗变化

    # 1. 生成低分辨率的随机噪声 (比如原图的 1/20)
    w, h = img.size
    low_res_size = (max(1, w // 20), max(1, h // 20))
    shadow_array = np.random.uniform(200, 255, (low_res_size[1], low_res_size[0])).astype('uint8')
    shadow_img = Image.fromarray(shadow_array, mode='L')

    # 2. 强力模糊，使噪点变成云雾状的阴影
    shadow_img = shadow_img.resize((w, h), resample=Image.BICUBIC)
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=50))

    # 3. 将阴影叠加到原图 (Multiply 正片叠底模式)
    # 这样纸张就会出现不均匀的“脏”和“暗”
    img = ImageChops.multiply(img, shadow_img)
    # -----------------------------------

    # 3. 轻微模糊 (Blur) 0.5-0.8
    blur_radius = random.uniform(0.5, 0.8)
    img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    # 4. 添加噪点 (Noise)
    img_array = np.array(img)

    # 生成高斯噪声 (均值0，标准差3-6之间)
    noise_sigma = random.uniform(3, 6)
    noise = np.random.normal(0, noise_sigma, img_array.shape)

    # 将噪声叠加到图像上
    noisy_img_array = img_array + noise

    # 将数值限制在 0-255 之间，并转回 uint8 类型
    noisy_img_array = np.clip(noisy_img_array, 0, 255).astype('uint8')

    # 转回 PIL Image 对象
    final_img = Image.fromarray(noisy_img_array)

    return final_img

def convert_pdf_to_scanned(input_path, output_path, dpi=200):
    """
    核心转换函数：将普通PDF转换为扫描风格PDF

    Args:
        input_path: 输入PDF路径
        output_path: 输出PDF路径
        dpi: 转换分辨率 (默认200)

    Returns:
        bool: 是否成功
    """
    # 检查依赖
    check_poppler_dependency()

    if not os.path.exists(input_path):
        print(f"[错误] 找不到输入文件: {input_path}")
        return False

    print(f"[开始] 正在处理: {input_path}")
    print(f"[配置] 设置分辨率: {dpi} DPI")

    try:
        # 1. 转换 PDF 为图片
        print("[1/3] 正在将 PDF 页面转换为图像...")
        # fmt='jpeg' 可以减小中间过程的内存占用
        pages = convert_from_path(input_path, dpi=dpi, fmt='jpeg')

        if not pages:
            print("[错误] PDF 文件似乎是空的或无法读取")
            return False

        processed_pages = []
        total_pages = len(pages)

        # 2. 应用特效
        print(f"[2/3] 正在应用扫描特效 (共 {total_pages} 页)...")
        for i, page in enumerate(pages):
            print(f"   正在处理第 {i+1}/{total_pages} 页...")
            scanned_page = apply_scanner_effect_to_image(page)
            processed_pages.append(scanned_page)

        # 3. 保存
        print(f"[3/3] 正在合成并保存 PDF: {output_path}")
        if processed_pages:
            # save_all=True 表示保存多页，append_images 放入剩余页面
            processed_pages[0].save(
                output_path,
                "PDF",
                resolution=100.0,
                save_all=True,
                append_images=processed_pages[1:]
            )
            print("[完成] 转换成功！")
            return True
        else:
            print("[错误] 未能生成任何页面")
            return False

    except Exception as e:
        print(f"\n[错误] 发生未预期的错误: {str(e)}")
        # 为了调试方便，打印堆栈
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 简单的命令行入口，用于测试
    import argparse
    parser = argparse.ArgumentParser(description="PDF 扫描件模拟工具 - 将电子 PDF 转换为扫描件风格")
    parser.add_argument("input_file", help="输入的 PDF 文件路径")
    parser.add_argument("-o", "--output", help="输出的 PDF 文件路径 (默认在文件名后加 _scanned)")
    parser.add_argument("--dpi", type=int, default=200, help="扫描分辨率 (DPI)，默认 200")

    args = parser.parse_args()

    out_path = args.output
    if not out_path:
        base, ext = os.path.splitext(args.input_file)
        out_path = f"{base}_scanned{ext}"

    convert_pdf_to_scanned(args.input_file, out_path, args.dpi)
