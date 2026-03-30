import asyncio
import sys
import os
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright

# 将项目根目录添加到 python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import BASE_DIR, OUTPUT_DIR

# ==========================================
# 👇 配置区
# ==========================================
CONFIG_PATH = BASE_DIR / "config" / "submit_config.json"
SIGN_OUTPUT_DIR = BASE_DIR / "签章页"
MAX_PAGES = 10  # 最大翻页数，防止无限循环
# ==========================================


def get_downloaded_flow_numbers() -> set:
    """获取已下载的流水号集合，用于去重"""
    downloaded = set()
    if SIGN_OUTPUT_DIR.exists():
        for file in SIGN_OUTPUT_DIR.glob("*.pdf"):
            # 文件名格式: 流水号.pdf 或 流水号_项目名.pdf
            flow_number = file.stem.split("_")[0]
            downloaded.add(flow_number)
    return downloaded


async def batch_download_signs():
    print(f"{'='*60}")
    print(f"[工具] 批量签章页下载器 (支持多页)")
    print(f"{'='*60}")

    # 1. 准备目录
    if not SIGN_OUTPUT_DIR.exists():
        SIGN_OUTPUT_DIR.mkdir(parents=True)
        print(f"[目录] 已创建保存目录: {SIGN_OUTPUT_DIR}")
    else:
        print(f"[目录] 保存目录: {SIGN_OUTPUT_DIR}")

    # 2. 获取已下载的流水号
    downloaded_set = get_downloaded_flow_numbers()
    if downloaded_set:
        print(f"[去重] 已检测到 {len(downloaded_set)} 个已下载的签章页，将自动跳过")

    print(f"[配置] 配置文件: {CONFIG_PATH}")
    print(f"{'-'*60}")

    async with async_playwright() as p:
        print("[启动] 正在启动浏览器...")
        browser = await p.chromium.launch(headless=False, args=['--start-maximized'])
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()

        try:
            # 加载配置文件
            import json
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 获取账号密码
            username = config.get('username', '')
            password = config.get('password', '')
            wait_captcha_seconds = config.get('wait_captcha_seconds', 60)

            print("[登录] 正在打开登录页面...")
            await page.goto("https://register.ccopyright.com.cn/login.html")
            await asyncio.sleep(5)

            # 自动填充账号密码
            if username and password:
                print(f"[登录] 账号: {username[:3]}***")

                # 填充账号
                username_filled = False
                try:
                    username_locators = [
                        page.locator("input[placeholder*='手机']"),
                        page.locator("input[placeholder*='用户']"),
                        page.locator("input[placeholder*='账号']"),
                    ]
                    for loc in username_locators:
                        if await loc.count() > 0:
                            await loc.first.fill(username)
                            print("[登录] ✓ 已填充账号")
                            username_filled = True
                            break
                except:
                    pass

                if not username_filled:
                    all_inputs = await page.locator("input").all()
                    for inp in all_inputs:
                        try:
                            input_type = await inp.get_attribute("type")
                            is_visible = await inp.is_visible()
                            if input_type in ["text", "tel", None] and is_visible:
                                await inp.fill(username)
                                print("[登录] ✓ 已填充账号")
                                username_filled = True
                                break
                        except:
                            continue

                # 填充密码
                await asyncio.sleep(0.5)
                try:
                    pwd_input = page.locator("input[type='password']")
                    if await pwd_input.count() > 0:
                        await pwd_input.first.fill(password)
                        print("[登录] ✓ 已填充密码")
                except:
                    pass

                # 尝试点击登录按钮
                await asyncio.sleep(1)
                try:
                    login_btn_selectors = [
                        "button:has-text('登录')",
                        "button[type='submit']",
                        ".login-btn",
                    ]
                    for selector in login_btn_selectors:
                        try:
                            btn = page.locator(selector).first
                            if await btn.count() > 0 and await btn.is_visible():
                                await btn.click()
                                print("[登录] ✓ 已点击登录按钮")
                                break
                        except:
                            continue
                except:
                    pass

            # 等待用户完成验证码
            print(f"\n{'='*50}")
            print(f"请在 {wait_captcha_seconds} 秒内完成验证码...")
            print(f"{'='*50}\n")

            # 等待登录成功
            is_logged_in = False
            for i in range(wait_captcha_seconds):
                await asyncio.sleep(1)
                current_url = page.url
                if "account.html" in current_url or "/index" in current_url:
                    print(f"\n[登录] ✓ 登录成功！")
                    is_logged_in = True
                    break
                if i > 0 and i % 10 == 0:
                    print(f"[登录] 等待中... 剩余 {wait_captcha_seconds - i} 秒")

            if not is_logged_in:
                print(f"\n[失败] 登录超时，停止脚本。")
                return

            # 导航到用户中心
            target_url = "https://register.ccopyright.com.cn/account.html?current=soft_register"
            await page.goto(target_url)
            await asyncio.sleep(2)

            # 登录成功后，开始多页下载
            total_success = 0
            total_skipped = 0
            total_failed = 0
            current_page_num = 1

            while current_page_num <= MAX_PAGES:
                print(f"\n{'='*60}")
                print(f"[第 {current_page_num} 页] 正在处理...")
                print(f"{'='*60}")

                # 等待列表加载
                print("[等待] 正在加载项目列表...")
                try:
                    await page.wait_for_selector(".hd-table-body", timeout=15000)
                except:
                    pass

                await page.wait_for_load_state('networkidle')
                await asyncio.sleep(3)  # 给足时间让页面渲染

                # 查找所有的 "打印签章页" 按钮
                print("[扫描] 正在扫描当前页面的可打印项目...")
                print_btns = await page.get_by_text("打印签章页").all()

                page_count = len(print_btns)
                if page_count == 0:
                    print(f"[提示] 第 {current_page_num} 页没有找到任何 '打印签章页' 按钮")
                    print("[完成] 没有更多需要下载的签章页了，退出")
                    break

                print(f"[发现] 本页找到 {page_count} 个可打印项目")

                # 遍历下载当前页的项目
                page_success = 0
                page_skipped = 0
                page_failed = 0

                for index in range(page_count):
                    try:
                        # 每次重新获取按钮列表（因为DOM可能变化）
                        print_btns = await page.get_by_text("打印签章页").all()
                        if index >= len(print_btns):
                            print(f"      [警告] 按钮索引超出范围，跳过")
                            break

                        btn = print_btns[index]

                        print(f"\n[{index+1}/{page_count}] 正在处理第 {index+1} 个项目...")

                        # 先尝试获取流水号（通过按钮的父元素或相关属性）
                        flow_number = await get_flow_number_from_row(page, btn)

                        # 检查是否已下载
                        if flow_number and flow_number in downloaded_set:
                            print(f"      [跳过] 流水号 {flow_number} 已下载过")
                            page_skipped += 1
                            total_skipped += 1
                            continue

                        # 点击按钮，预期打开新页面
                        try:
                            async with context.expect_page(timeout=30000) as new_page_info:
                                await btn.click()
                            print_page = await new_page_info.value
                        except Exception as e:
                            print(f"      [失败] 打开签章页超时: {e}")
                            page_failed += 1
                            total_failed += 1
                            continue

                        await print_page.wait_for_load_state('networkidle')
                        await asyncio.sleep(2)

                        # --- 打印页逻辑 ---

                        # 1. 再次点击内部的 "打印" 按钮 (如果有)
                        try:
                            final_print_btn = print_page.get_by_text("打印", exact=True)
                            if await final_print_btn.count() > 0:
                                await final_print_btn.click()
                                await asyncio.sleep(2)
                        except:
                            pass

                        # 2. 获取流水号（从URL）
                        if not flow_number or flow_number == "unknown":
                            try:
                                parsed_url = urlparse(print_page.url)
                                params = parse_qs(parsed_url.query)
                                if 'flowNumber' in params:
                                    flow_number = params['flowNumber'][0]
                            except:
                                flow_number = f"unknown_{int(asyncio.get_event_loop().time())}"

                        # 3. 再次检查是否已下载（以URL中的流水号为准）
                        if flow_number in downloaded_set:
                            print(f"      [跳过] 流水号 {flow_number} 已下载过")
                            await print_page.close()
                            page_skipped += 1
                            total_skipped += 1
                            continue

                        # 4. 生成文件名
                        file_name = f"{flow_number}.pdf"
                        save_path = SIGN_OUTPUT_DIR / file_name

                        # 5. 保存 PDF
                        print(f"      流水号: {flow_number}")
                        print(f"      正在保存到: {file_name}")

                        try:
                            await print_page.emulate_media(media="print")
                            await print_page.pdf(path=save_path, format="A4", print_background=True)
                            print(f"      [成功] 下载完成")
                            page_success += 1
                            total_success += 1
                            downloaded_set.add(flow_number)  # 添加到已下载集合
                        except Exception as e:
                            print(f"      [失败] PDF保存失败: {e}")
                            page_failed += 1
                            total_failed += 1

                        await print_page.close()

                        # 稍作休息，防止请求过快
                        await asyncio.sleep(1.5)

                    except Exception as e:
                        print(f"      [失败] 处理出错: {e}")
                        page_failed += 1
                        total_failed += 1

                print(f"\n[第 {current_page_num} 页统计] 成功: {page_success}, 跳过: {page_skipped}, 失败: {page_failed}")

                # 尝试翻到下一页
                has_next = await try_goto_next_page(page)
                if has_next:
                    current_page_num += 1
                    await asyncio.sleep(2)  # 等待页面加载
                else:
                    print("\n[完成] 没有更多页面了")
                    break

            print(f"\n{'='*60}")
            print(f"[全部完成] 总计处理了 {current_page_num} 页")
            print(f"  成功下载: {total_success}")
            print(f"  跳过(已存在): {total_skipped}")
            print(f"  失败: {total_failed}")
            print(f"文件保存在: {SIGN_OUTPUT_DIR}")
            print(f"{'='*60}")

            print("浏览器将在 5 秒后关闭...")
            await asyncio.sleep(5)

        except Exception as e:
            print(f"\n[错误] 程序运行出错: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()


async def get_flow_number_from_row(page, btn) -> str:
    """尝试从按钮所在行获取流水号"""
    try:
        # 尝试获取按钮的父元素（表格行）
        # 通常流水号会在同一行的某个单元格中
        row = btn.locator("xpath=ancestor::tr | ancestor::div[contains(@class, 'row')]").first
        if await row.count() > 0:
            row_text = await row.inner_text()
            # 尝试匹配流水号格式（通常是数字开头）
            match = re.search(r'(\d{10,20})', row_text)
            if match:
                return match.group(1)
    except:
        pass
    return "unknown"


async def try_goto_next_page(page) -> bool:
    """尝试点击下一页按钮，返回是否成功"""
    try:
        # 首先尝试：软著中心特有的分页结构 (.hd-pagination)
        # 结构: <span class="pages active">1</span><span class="pages">2</span>
        # 右侧箭头: <svg class="icon"> (没有 left 和 disabled)
        try:
            # 方式1: 点击下一个页码数字
            current_page = page.locator(".hd-pagination .pages.active").first
            if await current_page.count() > 0:
                current_num = int((await current_page.inner_text()).strip())
                next_num = current_num + 1

                # 查找下一页的页码（在同一个分页容器内）
                next_page_btn = page.locator(f".hd-pagination .pages:not(.active)").filter(has_text=str(next_num)).first
                if await next_page_btn.count() > 0 and await next_page_btn.is_visible():
                    print(f"[翻页] 点击页码 {next_num}...")
                    await next_page_btn.click()
                    await asyncio.sleep(3)
                    try:
                        await page.wait_for_load_state('networkidle', timeout=10000)
                    except:
                        pass
                    return True

            # 方式2: 点击右侧箭头 (没有 left 类且没有 disabled 类的 svg)
            right_arrow = page.locator(".hd-pagination svg.icon:not(.left):not(.disabled)").first
            if await right_arrow.count() > 0:
                # 检查是否禁用
                class_attr = await right_arrow.get_attribute("class") or ""
                if "disabled" not in class_attr:
                    print("[翻页] 点击右侧箭头...")
                    await right_arrow.click()
                    await asyncio.sleep(3)
                    try:
                        await page.wait_for_load_state('networkidle', timeout=10000)
                    except:
                        pass
                    return True
                else:
                    print("[翻页] 右侧箭头已禁用，当前是最后一页")
                    return False
        except Exception as e:
            print(f"[翻页] 软著分页方式失败: {e}")

        # 备用：通用分页选择器
        next_page_selectors = [
            ".el-pagination .btn-next:not(.disabled)",
            ".ant-pagination-next:not(.ant-pagination-disabled)",
            "button:has-text('下一页'):not([disabled])",
            "a:has-text('下一页'):not(.disabled)",
            ".pagination .next:not(.disabled)",
            ".ivu-page-next:not(.ivu-page-disabled)",
        ]

        for selector in next_page_selectors:
            try:
                next_btn = page.locator(selector).first
                if await next_btn.count() > 0 and await next_btn.is_visible():
                    is_disabled = await next_btn.get_attribute("disabled")
                    class_attr = await next_btn.get_attribute("class") or ""

                    if is_disabled or "disabled" in class_attr:
                        continue

                    print(f"[翻页] 找到下一页按钮，正在点击...")
                    await next_btn.click()
                    await asyncio.sleep(3)
                    return True
            except:
                continue

        print("[翻页] 未找到下一页按钮或已是最后一页")
        return False

    except Exception as e:
        print(f"[翻页] 翻页操作出错: {e}")
        return False


if __name__ == "__main__":
    # Windows 下 Playwright 需要 ProactorEventLoop
    asyncio.run(batch_download_signs())
