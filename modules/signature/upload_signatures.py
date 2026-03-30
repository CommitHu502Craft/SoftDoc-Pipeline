import asyncio
import sys
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright

# 将项目根目录添加到 python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import BASE_DIR

# ==========================================
# 👇 配置区
# ==========================================
CONFIG_PATH = BASE_DIR / "config" / "submit_config.json"
SIGNATURE_DIR = BASE_DIR / "最终提交"  # 已签名并应用扫描效果的PDF目录
# ==========================================

async def batch_upload_signatures():
    """批量上传签章页到版权中心"""
    print(f"{'='*60}")
    print(f"[工具] 批量签章页上传器")
    print(f"{'='*60}")

    # 1. 检查目录
    if not SIGNATURE_DIR.exists():
        print(f"[错误] 签章页目录不存在: {SIGNATURE_DIR}")
        return

    # 2. 扫描所有签章页PDF
    signature_files = list(SIGNATURE_DIR.glob("*.pdf"))
    if not signature_files:
        print(f"[警告] 在 {SIGNATURE_DIR} 中没有找到任何PDF文件")
        return

    print(f"[发现] 找到 {len(signature_files)} 个签章页PDF文件")

    # 3. 提取流水号作为字典键
    # 文件名格式: 2026R11L0125852.pdf
    flow_number_map = {}
    for pdf_file in signature_files:
        flow_number = pdf_file.stem  # 去掉.pdf后缀
        flow_number_map[flow_number] = pdf_file
        print(f"      - {flow_number}")

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

            print("[登录] 正在执行登录...")
            await page.goto("https://register.ccopyright.com.cn/login.html")

            # 等待页面加载
            print("等待登录页面完全加载（10秒）...")
            await asyncio.sleep(10)

            # 自动填充账号密码
            try:
                if username and password:
                    print(f"开始自动填充 - 账号: {username[:3]}***")

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
                                print(f"✓ 已填充账号")
                                username_filled = True
                                break
                    except:
                        pass

                    if not username_filled:
                        # 查找所有文本输入框
                        all_inputs = await page.locator("input").all()
                        for inp in all_inputs:
                            try:
                                input_type = await inp.get_attribute("type")
                                is_visible = await inp.is_visible()
                                if input_type in ["text", "tel", None] and is_visible:
                                    await inp.fill(username)
                                    print(f"✓ 已填充账号")
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
                            print("✓ 已填充密码")
                    except:
                        pass

                    print("\n" + "="*60)
                    if username_filled:
                        print("[OK] 账号密码已自动填充，请手动完成验证码并点击登录")
                    else:
                        print("[Warn] 账号填充失败，请手动输入账号密码并完成验证码")
                    print("="*60 + "\n")

                    # 等待用户滑动验证码
                    await asyncio.sleep(3)

                    # 自动点击登录按钮
                    try:
                        login_btn_selectors = [
                            "button:has-text('登录')",
                            "button[type='submit']",
                            ".login-btn",
                        ]

                        for selector in login_btn_selectors:
                            try:
                                btn = page.locator(selector)
                                if await btn.count() > 0 and await btn.is_visible():
                                    await btn.click()
                                    print("✓ 已自动点击登录按钮")
                                    break
                            except:
                                continue
                    except:
                        pass
            except Exception as e:
                print(f"自动填充流程出错: {e}")

            # 等待跳转到用户中心
            print("[等待] 正在等待进入用户中心...")
            max_wait = 120
            is_logged_in = False
            user_center_url = "https://register.ccopyright.com.cn/account.html?current=soft_register"

            print("[等待] 正在检测登录状态...")
            for i in range(max_wait):
                current_url = page.url
                if "account.html" in current_url or "/index" in current_url:
                    print(f"\n[成功] 检测到已登录！当前页面: {current_url}")
                    is_logged_in = True
                    break

                if i == 15 and "login.html" in current_url:
                    print(f"\n[提示] 尝试直接跳转到用户中心...")
                    await page.goto(user_center_url)
                    await asyncio.sleep(2)
                    continue

                if i % 5 == 0:
                    print(f"       [{i}s] 当前 URL: {current_url} (等待跳转...)")

                await asyncio.sleep(1)

            if not is_logged_in:
                print(f"\n[超时] {max_wait}秒内未检测到成功登录，停止脚本。")
                return

            # 强制跳转到用户中心列表页
            print(f"\n[跳转] 正在前往用户中心列表页: {user_center_url}")
            await page.goto(user_center_url)

            # 等待列表加载
            print("[等待] 正在加载项目列表...")
            try:
                await page.wait_for_selector(".hd-table-body", timeout=10000)
            except:
                pass

            await page.wait_for_load_state('networkidle')
            await asyncio.sleep(5)

            print(f"[状态] 当前页面: {page.url}")
            print("[扫描] 正在扫描页面上的项目...")

            # 策略：找到所有的表格行，提取项目信息和流水号
            # 每一行包含：项目名称、流水号、上传按钮

            # 先获取页面内容，提取所有流水号
            page_content = await page.content()

            # 查找页面上所有的流水号（格式：20xxRxxLxxxxxxx）
            flow_numbers_on_page = re.findall(r'(20\d{2}R\d{2}L\d+)', page_content)
            flow_numbers_on_page = list(set(flow_numbers_on_page))  # 去重

            print(f"[发现] 页面上找到 {len(flow_numbers_on_page)} 个流水号")

            # 匹配本地签章页文件
            upload_tasks = []
            for flow_num in flow_numbers_on_page:
                if flow_num in flow_number_map:
                    upload_tasks.append({
                        'flow_number': flow_num,
                        'file_path': flow_number_map[flow_num]
                    })
                    print(f"      ✓ 匹配: {flow_num}")
                else:
                    print(f"      ✗ 未找到本地文件: {flow_num}")

            if not upload_tasks:
                print("\n[警告] 没有找到任何需要上传的项目")
                return

            print(f"\n{'-'*60}")
            print(f"[准备] 共有 {len(upload_tasks)} 个项目需要上传签章页")
            print(f"{'-'*60}")

            # 执行上传
            success_count = 0

            for index, task in enumerate(upload_tasks):
                flow_number = task['flow_number']
                file_path = task['file_path']

                print(f"\n[{index+1}/{len(upload_tasks)}] 正在处理流水号: {flow_number}")
                print(f"      文件: {file_path.name}")

                try:
                    # 策略：在页面上定位包含该流水号的行，然后找到对应的上传按钮

                    # 方法1: 找到包含流水号文本的元素
                    flow_number_element = page.locator(f"text={flow_number}").first

                    if await flow_number_element.count() == 0:
                        print(f"      [失败] 在页面上未找到流水号 {flow_number}")
                        continue

                    # 找到该流水号所在的行容器（通常是tr或包含table-row的div）
                    # 尝试多种父元素定位方式
                    row_element = None

                    # 尝试1: 查找tr父元素
                    try:
                        tr_row = flow_number_element.locator("xpath=ancestor::tr").first
                        if await tr_row.count() > 0:
                            row_element = tr_row
                            print(f"      定位到表格行 (tr)")
                    except:
                        pass

                    # 尝试2: 如果没有tr，查找包含table-row类的div
                    if not row_element:
                        try:
                            div_row = flow_number_element.locator("xpath=ancestor::div[contains(@class, 'row')]").first
                            if await div_row.count() > 0:
                                row_element = div_row
                                print(f"      定位到行容器 (div.row)")
                        except:
                            pass

                    # 尝试3: 向上查找3层父元素
                    if not row_element:
                        try:
                            parent_row = flow_number_element.locator("xpath=ancestor::*[3]").first
                            if await parent_row.count() > 0:
                                row_element = parent_row
                                print(f"      定位到父容器")
                        except:
                            pass

                    if not row_element:
                        print(f"      [失败] 无法定位到包含流水号的行容器")
                        continue

                    # 在该行内查找"上传签章页"按钮或input
                    # 策略：先找包含"上传签章页"文字的按钮
                    upload_button = row_element.locator("text=上传签章页").first

                    if await upload_button.count() == 0:
                        print(f"      [失败] 在行内未找到'上传签章页'按钮")
                        continue

                    print(f"      找到'上传签章页'按钮")

                    # 在该按钮的父元素或兄弟元素中查找 input[type="file"]
                    # 方法1: 按钮内部的input
                    file_input = upload_button.locator("xpath=.//input[@type='file']").first

                    if await file_input.count() == 0:
                        # 方法2: 按钮的兄弟元素
                        file_input = upload_button.locator("xpath=../input[@type='file']").first

                    if await file_input.count() == 0:
                        # 方法3: 在按钮的父父元素下查找
                        file_input = upload_button.locator("xpath=../..//input[@type='file']").first

                    if await file_input.count() == 0:
                        # 方法4: 在整个row内查找
                        file_input = row_element.locator("input[type='file']").first

                    if await file_input.count() == 0:
                        print(f"      [失败] 在按钮附近未找到文件上传input")
                        continue

                    print(f"      找到文件上传input")

                    # 上传文件
                    print(f"      正在选择文件...")
                    await file_input.set_input_files(str(file_path.absolute()))

                    # 关键：选择文件后，需要等待一下让页面响应
                    await asyncio.sleep(1)

                    # 查找并点击"确定"/"上传"/"提交"按钮
                    print(f"      查找上传确认按钮...")
                    upload_confirm_clicked = False

                    # 在行内或附近查找可能的确认按钮
                    confirm_button_selectors = [
                        # 在row内查找
                        row_element.locator("button:has-text('上传')"),
                        row_element.locator("button:has-text('确定')"),
                        row_element.locator("button:has-text('确认')"),
                        row_element.locator("button:has-text('提交')"),
                        row_element.locator(".upload-btn"),
                        row_element.locator(".confirm-btn"),
                        # 在上传按钮附近查找
                        upload_button.locator("xpath=../button[contains(text(), '上传')]"),
                        upload_button.locator("xpath=../../button[contains(text(), '上传')]"),
                    ]

                    for selector in confirm_button_selectors:
                        try:
                            if await selector.count() > 0:
                                btn = selector.first
                                if await btn.is_visible():
                                    await btn.click()
                                    print(f"      ✓ 已点击确认按钮")
                                    upload_confirm_clicked = True
                                    break
                        except:
                            continue

                    if not upload_confirm_clicked:
                        # 如果没找到确认按钮，可能文件选择后会自动上传
                        # 或者需要在整个页面上查找
                        print(f"      未找到行内确认按钮，尝试在页面上查找...")

                        page_confirm_selectors = [
                            page.locator("button:has-text('上传'):visible"),
                            page.locator("button:has-text('确定'):visible"),
                            page.locator("button:has-text('确认'):visible"),
                        ]

                        for selector in page_confirm_selectors:
                            try:
                                if await selector.count() > 0:
                                    await selector.first.click()
                                    print(f"      ✓ 已点击页面确认按钮")
                                    upload_confirm_clicked = True
                                    break
                            except:
                                continue

                    if not upload_confirm_clicked:
                        print(f"      ⚠ 未找到确认按钮，文件可能需要手动确认上传")

                    # 等待上传真正完成
                    print(f"      正在等待上传完成...")

                    # 策略1: 等待网络活动（上传中）然后等待网络空闲（上传完成）
                    await asyncio.sleep(2)  # 给点时间让上传开始

                    try:
                        await page.wait_for_load_state('networkidle', timeout=30000)
                        print(f"      网络空闲，上传应该已完成")
                    except:
                        print(f"      等待网络空闲超时，可能还在上传...")

                    # 策略2: 额外等待，确保服务器处理完成
                    await asyncio.sleep(3)

                    # 策略3: 检查页面上是否有成功提示
                    try:
                        success_indicators = [
                            page.locator("text=上传成功"),
                            page.locator("text=已上传"),
                            page.locator("text=完成"),
                            page.locator(".success-message"),
                        ]

                        found_success = False
                        for indicator in success_indicators:
                            if await indicator.count() > 0 and await indicator.is_visible():
                                print(f"      ✓✓✓ 检测到上传成功提示！")
                                found_success = True
                                break

                        if not found_success:
                            print(f"      ⚠ 未检测到明确的成功提示，请手动确认")
                    except:
                        pass

                    print(f"      [完成] 文件上传流程执行完毕")
                    success_count += 1

                except Exception as e:
                    print(f"      [失败] 上传出错: {e}")
                    import traceback
                    traceback.print_exc()

                # 稍作休息
                await asyncio.sleep(1)

            print(f"\n{'='*60}")
            print(f"[完成] 全部处理完毕。成功: {success_count}/{len(upload_tasks)}")
            print(f"{'='*60}")

            print("\n" + "="*60)
            print("提示: 请在浏览器中手动检查上传结果")
            print("确认无误后，手动关闭浏览器窗口以结束程序")
            print("="*60 + "\n")

            # 保持浏览器打开，等待用户手动关闭
            print("等待用户手动关闭浏览器...")
            while browser.is_connected():
                await asyncio.sleep(1)

        except Exception as e:
            print(f"\n[错误] 程序运行出错: {e}")
            import traceback
            traceback.print_exc()

            print("\n浏览器将保持打开，请检查错误后手动关闭")
            # 即使出错也保持浏览器打开
            while browser.is_connected():
                await asyncio.sleep(1)
        finally:
            # 只有在浏览器已断开时才尝试关闭
            try:
                if browser.is_connected():
                    await browser.close()
            except:
                pass

if __name__ == "__main__":
    asyncio.run(batch_upload_signatures())
