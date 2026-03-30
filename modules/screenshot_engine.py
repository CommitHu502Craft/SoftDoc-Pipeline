"""
截图引擎模块 (Refactored)
使用 Playwright 批量将 HTML 页面转换为高清截图
支持全页截图和组件级精细截图 (双重模式)
v2.0: 增强视口随机化和CSS微扰动，统一文件名哈希规则
"""
import asyncio
import random
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from playwright.async_api import async_playwright
from config import BASE_DIR

def add_window_shell(image_path: Path, url: str = "http://localhost:8080"):
    """
    给截图添加 MacOS 风格的窗口外壳 (Phase 2)
    """
    if not image_path.exists():
        return

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        # 如果未安装 PIL，跳过
        return

    try:
        # 1. 读取原始截图
        with Image.open(image_path) as img:
            original_w, original_h = img.size

            # 2. 设置外壳参数
            header_height = 40  # 标题栏高度
            border_color = (220, 220, 220) # 边框颜色
            bg_color = (255, 255, 255) # 背景色

            # 3. 创建新画布 (高度增加了 header_height)
            new_w = original_w
            new_h = original_h + header_height
            new_img = Image.new('RGB', (new_w, new_h), bg_color)
            draw = ImageDraw.Draw(new_img)

            # 4. 绘制标题栏背景 (浅灰)
            draw.rectangle([(0, 0), (new_w, header_height)], fill=(240, 240, 240))

            # 5. 绘制红黄绿按钮 (MacOS style)
            # 圆心 y = header_height / 2 = 20
            # x 坐标从左侧开始
            y_center = header_height // 2
            radius = 6

            # 红
            draw.ellipse([(15-radius, y_center-radius), (15+radius, y_center+radius)], fill=(255, 95, 86), outline=(224, 68, 62))
            # 黄
            draw.ellipse([(35-radius, y_center-radius), (35+radius, y_center+radius)], fill=(255, 189, 46), outline=(214, 161, 45))
            # 绿
            draw.ellipse([(55-radius, y_center-radius), (55+radius, y_center+radius)], fill=(39, 201, 63), outline=(35, 165, 53))

            # 6. 绘制地址栏 (模拟)
            bar_w = int(new_w * 0.6)
            bar_h = 24
            bar_x = (new_w - bar_w) // 2
            bar_y = (header_height - bar_h) // 2

            # 地址栏背景 (白)
            draw.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], fill=(255, 255, 255), outline=(200, 200, 200))

            # 地址栏文字
            try:
                # 尝试加载默认字体，如果失败则使用默认
                font = ImageFont.truetype("arial.ttf", 12)
            except:
                font = ImageFont.load_default()

            # 截断 URL 防止溢出
            display_url = url
            if len(display_url) > 80: display_url = display_url[:80] + "..."

            # 文字居中 (简单估算)
            text_x = bar_x + 10
            text_y = bar_y + 4 # 微调
            draw.text((text_x, text_y), display_url, fill=(80, 80, 80), font=font)

            # 7. 粘贴原始截图
            new_img.paste(img, (0, header_height))

            # 8. 保存覆盖
            new_img.save(image_path, quality=95)

    except Exception as e:
        print(f"  ⚠ 添加窗口外壳失败: {e}")


def _normalize_project_name_from_html_dir(html_dir: Path) -> str:
    try:
        return str(html_dir.parent.name)
    except Exception:
        return ""


def _default_contract_path(html_dir: Path) -> Path:
    project_name = _normalize_project_name_from_html_dir(html_dir)
    return BASE_DIR / "output" / project_name / "screenshot_contract.json"


def _load_contract(contract_path: Optional[Path], html_dir: Path) -> Dict[str, Any]:
    path = Path(contract_path) if contract_path else _default_contract_path(html_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _safe_file_token(text: str) -> str:
    token = str(text or "").strip().replace("\\", "_").replace("/", "_").replace(":", "_")
    token = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in token)
    token = "_".join([x for x in token.split("_") if x])
    return token[:80] if token else "claim"


def datetime_now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

async def capture_screenshots(
    html_dir: Path,
    output_dir: Path = None,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    timeout: int = 30000,
    contract_path: Optional[Path] = None,
) -> Path:
    """
    批量截图 HTML 页面 (全页 + 组件)

    Args:
        html_dir: HTML 文件所在目录
        output_dir: 截图输出目录
        viewport_width: 基础视口宽度 (会被随机化微调)
        viewport_height: 基础视口高度
        timeout: 超时时间（毫秒）

    Returns:
        截图输出目录路径
    """
    print(f"\n{'='*60}")
    print(f"开始批量截图 (双重模式)")
    print(f"{'='*60}\n")

    # 设置输出目录
    if output_dir is None:
        output_dir = BASE_DIR / "output" / "screenshots"

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"HTML 目录: {html_dir}")
    print(f"输出目录: {output_dir}")

    # 获取所有 HTML 文件
    html_files = list(html_dir.glob("*.html"))
    if not html_files:
        print("⚠ 警告: 未找到 HTML 文件")
        return output_dir

    print(f"找到 {len(html_files)} 个 HTML 文件\n")

    contract = _load_contract(contract_path=contract_path, html_dir=html_dir)
    contract_pages = contract.get("pages") if isinstance(contract, dict) else {}
    if not isinstance(contract_pages, dict):
        contract_pages = {}

    project_name = _normalize_project_name_from_html_dir(html_dir) or "unknown_project"
    capture_report: Dict[str, Any] = {
        "project_name": project_name,
        "generated_at": datetime_now_iso(),
        "contract_path": str((Path(contract_path) if contract_path else _default_contract_path(html_dir))),
        "pages": {},
    }

    # 视口尺寸池 (用于增加截图指纹差异)
    viewports = [
        {'width': 1920, 'height': 1080},
        {'width': 1680, 'height': 1050},
        {'width': 1440, 'height': 900},
        {'width': 2560, 'height': 1440},
        {'width': 1366, 'height': 768}
    ]

    # 启动 Playwright
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)

        total_screenshots = 0

        for html_file in html_files:
            page_id = html_file.stem
            print(f"处理页面: {html_file.name}")

            # 随机选择视口
            current_viewport = random.choice(viewports)
            context = await browser.new_context(
                viewport=current_viewport,
                device_scale_factor=2, # 高DPI
                color_scheme='light'   # 强制浅色模式，忽略系统设置
            )
            page = await context.new_page()

            try:
                # 1. 加载页面
                file_url = f"file:///{html_file.as_posix()}"
                await page.goto(file_url, wait_until='domcontentloaded', timeout=timeout)

                # 2. 注入全局样式优化 (隐藏滚动条，禁用动画，添加微扰动)
                # 微扰动：随机微调字间距 (0px - 0.5px) 和 细微的容器圆角
                letter_spacing = random.uniform(0, 0.5)
                await page.add_style_tag(content=f"""
                    * {{ transition: none !important; animation: none !important; letter-spacing: {letter_spacing}px; }}
                    body::-webkit-scrollbar {{ display: none; }}
                """)

                # 3. 智能等待 (ECharts 渲染完成)
                try:
                    await page.wait_for_function(
                        """
                        () => {
                            if (window.echarts_rendering_finished !== true) return false;
                            const boxes = document.querySelectorAll('[id^="widget_chart_"]');
                            if (!boxes.length) return true;
                            let rendered = 0;
                            boxes.forEach((el) => {
                                if (el.querySelector('canvas, svg')) rendered += 1;
                            });
                            const diag = window.__chart_render_diagnostics || {};
                            const placeholders = Number(diag.placeholder || 0);
                            const required = Math.max(1, Math.ceil(boxes.length * 0.6));
                            return (rendered + placeholders) >= required;
                        }
                        """,
                        timeout=12000  # 给图表渲染留出更多时间
                    )
                    print(f"  ✓ ECharts 渲染就绪")
                except Exception:
                    print(f"  ⚠ 等待渲染标记超时，尝试直接截图")

                # 额外缓冲
                await asyncio.sleep(0.5)

                try:
                    diag = await page.evaluate("() => window.__chart_render_diagnostics || null")
                    if isinstance(diag, dict):
                        print(
                            "  > 渲染诊断: "
                            f"total={diag.get('total', 0)}, "
                            f"success={diag.get('success', 0)}, "
                            f"fallback={diag.get('fallback_option', 0)}, "
                            f"placeholder={diag.get('placeholder', 0)}, "
                            f"duration_ms={diag.get('duration_ms', '-')}"
                        )
                except Exception:
                    pass

                # ==========================================
                # 模式 A: 全页截图（文件名差异化）
                # ==========================================
                # 使用项目名哈希前缀避免文件名雷同
                project_hash = hashlib.md5(str(project_name).encode()).hexdigest()[:6]

                full_screenshot_path = output_dir / f"{project_hash}_{page_id}_full.png"
                await page.screenshot(path=str(full_screenshot_path), full_page=True)

                # [Phase 2] 添加窗口外壳
                add_window_shell(full_screenshot_path, url=f"http://localhost:8080/app/{page_id}")

                print(f"  ✓ 全页截图: {full_screenshot_path.name} (Viewport: {current_viewport['width']}x{current_viewport['height']})")
                total_screenshots += 1

                page_report = capture_report["pages"].setdefault(
                    page_id,
                    {
                        "full_screenshot": full_screenshot_path.name,
                        "components": [],
                        "claims": [],
                        "selector_hits": 0,
                        "selector_total": 0,
                    },
                )

                # ==========================================
                # 模式 B: 组件级截图
                # ==========================================
                # 查找所有图表和表格组件
                # 约定 ID 格式: widget_chart_X, widget_table_X (由 chart_injector.py 注入)
                components = await page.query_selector_all('[id^="widget_chart_"], [id^="widget_table_"]')

                if components:
                    print(f"  > 发现 {len(components)} 个组件，开始单独截图...")

                    for index, component in enumerate(components):
                        try:
                            # 获取组件 ID 用于命名，如果获取失败则用索引
                            comp_id = await component.get_attribute("id") or f"comp_{index+1}"

                            # 截图命名差异化: project_hash_page_id_component_X.png
                            filename = f"{project_hash}_{page_id}_{comp_id}.png"
                            comp_path = output_dir / filename

                            await component.screenshot(path=str(comp_path))
                            # 组件通常不需要窗口外壳，保持原样（或者可以加一个细微的边框，这里暂时不加）

                            print(f"    - 组件截图: {filename}")
                            total_screenshots += 1
                            page_report["components"].append(
                                {
                                    "component_id": comp_id,
                                    "file": filename,
                                }
                            )
                        except Exception as e:
                            print(f"    ⚠ 组件 {index+1} 截图失败: {e}")
                else:
                    print(f"  > 未发现可独立截图的组件 (widget_*)")

                # ==========================================
                # 模式 C: 合同选择器截图（claim 级证据）
                # ==========================================
                page_contract = contract_pages.get(page_id) or {}
                selector_specs = page_contract.get("required_selectors") or []
                if selector_specs:
                    print(f"  > 按合同执行 claim 截图: {len(selector_specs)} 条")
                selector_hits = 0
                selector_total = len(selector_specs)
                for sel_idx, spec in enumerate(selector_specs, start=1):
                    if isinstance(spec, dict):
                        selector = str(spec.get("selector") or "").strip()
                        claim_id = str(spec.get("claim_id") or "").strip() or f"claim_{sel_idx}"
                        block_id = str(spec.get("block_id") or "").strip()
                    else:
                        selector = str(spec or "").strip()
                        claim_id = f"claim_{sel_idx}"
                        block_id = ""
                    if not selector:
                        continue
                    try:
                        element = await page.query_selector(selector)
                        if not element:
                            page_report["claims"].append(
                                {
                                    "claim_id": claim_id,
                                    "block_id": block_id,
                                    "selector": selector,
                                    "captured": False,
                                    "file": "",
                                }
                            )
                            continue
                        token = _safe_file_token(claim_id)
                        claim_name = f"{project_hash}_{page_id}_claim_{sel_idx}_{token}.png"
                        claim_path = output_dir / claim_name
                        await element.screenshot(path=str(claim_path))
                        print(f"    - claim截图: {claim_name}")
                        total_screenshots += 1
                        selector_hits += 1
                        page_report["claims"].append(
                            {
                                "claim_id": claim_id,
                                "block_id": block_id,
                                "selector": selector,
                                "captured": True,
                                "file": claim_name,
                            }
                        )
                    except Exception as e:
                        print(f"    ⚠ claim截图失败({selector}): {e}")
                        page_report["claims"].append(
                            {
                                "claim_id": claim_id,
                                "block_id": block_id,
                                "selector": selector,
                                "captured": False,
                                "file": "",
                            }
                        )

                page_report["selector_hits"] = int(selector_hits)
                page_report["selector_total"] = int(selector_total)
                page_report["selector_hit_ratio"] = round(
                    float(selector_hits) / float(selector_total), 3
                ) if selector_total > 0 else 1.0

                print("") # 空行分隔

            except Exception as e:
                print(f"  ✗ 页面处理错误: {e}\n")

            finally:
                await context.close()

        await browser.close()

    # 总结
    print(f"{'='*60}")
    print(f"截图任务完成!")
    print(f"{'='*60}")
    print(f"累计生成截图: {total_screenshots} 张")
    print(f"输出目录: {output_dir}")
    print(f"{'='*60}\n")

    # 输出 capture report，供 claim-evidence 编译器复用。
    report_path = output_dir.parent / "screenshot_capture_report.json"
    summary_pages = capture_report.get("pages") or {}
    selector_total = sum(int((v or {}).get("selector_total") or 0) for v in summary_pages.values())
    selector_hits = sum(int((v or {}).get("selector_hits") or 0) for v in summary_pages.values())
    capture_report["summary"] = {
        "page_count": len(summary_pages),
        "selector_total": selector_total,
        "selector_hits": selector_hits,
        "selector_hit_ratio": round(float(selector_hits) / float(selector_total), 3) if selector_total > 0 else 1.0,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(capture_report, f, ensure_ascii=False, indent=2)
    print(f"截图报告: {report_path}")

    return output_dir


def capture_screenshots_sync(
    html_dir: Path,
    output_dir: Path = None,
    contract_path: Optional[Path] = None,
    **kwargs
) -> Path:
    """
    同步调用入口
    使用子进程运行，完全隔离事件循环
    """
    import sys
    import subprocess
    import os

    resolved_contract = Path(contract_path) if contract_path else _default_contract_path(Path(html_dir))
    script = f'''
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, r"{BASE_DIR}")
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from modules.screenshot_engine import capture_screenshots

async def _run():
    html_dir = Path(r"{html_dir}")
    output_dir = Path(r"{output_dir}") if {output_dir is not None} else None
    contract_path = Path(r"{resolved_contract}") if {resolved_contract.exists()} else None
    result = await capture_screenshots(
        html_dir=html_dir,
        output_dir=output_dir,
        contract_path=contract_path,
    )
    print(f"RESULT_PATH:{{result}}")

if __name__ == "__main__":
    asyncio.run(_run())
'''

    # 运行子进程
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env["PYTHONUTF8"] = "1"  # 强制 UTF-8 编码

    try:
        print(f"启动截图子进程 (Real-time Streaming)...")
        # 使用 Popen 替代 run 以便实时获取输出
        process = subprocess.Popen(
            [sys.executable, '-c', script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 将 stderr 合并到 stdout
            text=True,
            cwd=str(BASE_DIR),
            env=env,
            bufsize=1,  # 行缓冲
            encoding='utf-8'
        )

        result_path = None

        # 实时读取输出
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                # 打印子进程输出 (带前缀以便区分)
                print(f"  [Screenshot] {line.strip()}")

                # 捕获结果路径
                if line.startswith('RESULT_PATH:'):
                    try:
                        path_str = line.replace('RESULT_PATH:', '').strip()
                        result_path = Path(path_str)
                    except:
                        pass

        # 等待进程结束
        process.wait()

        if process.returncode != 0:
            raise Exception(f"截图子进程异常退出 (Code: {process.returncode})")

        if result_path:
            return result_path

        if output_dir:
            return Path(output_dir)
        return BASE_DIR / "output" / "screenshots"

    except Exception as e:
        print(f"截图执行出错: {e}")
        raise e


if __name__ == "__main__":
    # 简单的本地测试逻辑
    import sys
    test_project = "测试项目"
    if len(sys.argv) > 1:
        test_project = sys.argv[1]

    test_html_dir = BASE_DIR / "temp_build" / test_project / "html"
    if test_html_dir.exists():
        capture_screenshots_sync(test_html_dir)
    else:
        print(f"测试目录不存在: {test_html_dir}")
