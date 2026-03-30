"""
浏览器会话管理模块
支持保存和加载登录状态，避免重复登录
"""
import asyncio
import json
from pathlib import Path
from typing import Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# 会话状态保存路径
SESSION_DIR = Path(__file__).parent.parent / "config"
SESSION_FILE = SESSION_DIR / "browser_session.json"

# 登录页面URL特征
LOGIN_URL_PATTERNS = [
    "/login",
    "login.html",
]

# 用户中心URL（登录成功后的页面）
USER_CENTER_URL = "https://register.ccopyright.com.cn/r11.html"


async def save_session(context: BrowserContext):
    """保存当前会话状态（cookie + localStorage）"""
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(SESSION_FILE))
        print(f"[会话] ✓ 登录状态已保存到 {SESSION_FILE.name}")
        return True
    except Exception as e:
        print(f"[会话] ✗ 保存登录状态失败: {e}")
        return False


async def load_session_if_exists() -> Optional[str]:
    """检查是否有保存的会话状态"""
    if SESSION_FILE.exists():
        # 检查文件是否有效（不为空）
        try:
            with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get('cookies') or data.get('origins'):
                    print(f"[会话] 发现已保存的登录状态")
                    return str(SESSION_FILE)
        except:
            pass
    return None


def is_login_page(url: str) -> bool:
    """判断当前URL是否是登录页面"""
    url_lower = url.lower()
    for pattern in LOGIN_URL_PATTERNS:
        if pattern in url_lower:
            return True
    return False


async def ensure_logged_in(
    page: Page,
    context: BrowserContext,
    config: dict,
    target_url: str = USER_CENTER_URL
) -> bool:
    """
    确保已登录状态

    流程：
    1. 导航到目标页面
    2. 检测是否被重定向到登录页
    3. 如果是登录页，执行登录流程
    4. 登录成功后保存状态

    Args:
        page: Playwright页面对象
        context: 浏览器上下文
        config: 包含 username 和 password 的配置
        target_url: 目标页面URL

    Returns:
        bool: 是否成功进入目标页面（已登录状态）
    """
    print(f"[登录] 正在导航到目标页面...")
    await page.goto(target_url)
    await asyncio.sleep(3)

    current_url = page.url
    print(f"[登录] 当前URL: {current_url}")

    # 检测是否在登录页
    if is_login_page(current_url):
        print("[登录] 检测到登录页面，需要重新登录...")
        success = await do_login(page, config)
        if success:
            # 登录成功，保存状态
            await save_session(context)
            return True
        else:
            print("[登录] ✗ 登录失败")
            return False
    else:
        print("[登录] ✓ 已处于登录状态，无需重新登录")
        return True


async def do_login(page: Page, config: dict) -> bool:
    """
    执行登录流程

    Args:
        page: Playwright页面对象
        config: 包含 username 和 password 的配置

    Returns:
        bool: 登录是否成功
    """
    username = config.get('username', '')
    password = config.get('password', '')
    wait_captcha_seconds = config.get('wait_captcha_seconds', 60)

    if not username or not password:
        print("[登录] ✗ 账号或密码未配置")
        return False

    print(f"[登录] 账号: {username[:3]}***")

    # 等待页面加载
    await asyncio.sleep(3)

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
                print(f"[登录] ✓ 已填充账号")
                username_filled = True
                break
    except:
        pass

    if not username_filled:
        # 备用：查找所有文本输入框
        try:
            all_inputs = await page.locator("input").all()
            for inp in all_inputs:
                try:
                    input_type = await inp.get_attribute("type")
                    is_visible = await inp.is_visible()
                    if input_type in ["text", "tel", None] and is_visible:
                        await inp.fill(username)
                        print(f"[登录] ✓ 已填充账号")
                        username_filled = True
                        break
                except:
                    continue
        except:
            pass

    if not username_filled:
        print("[登录] ✗ 无法填充账号")
        return False

    # 填充密码
    await asyncio.sleep(0.5)
    try:
        pwd_input = page.locator("input[type='password']")
        if await pwd_input.count() > 0:
            await pwd_input.first.fill(password)
            print(f"[登录] ✓ 已填充密码")
        else:
            print("[登录] ✗ 未找到密码输入框")
            return False
    except Exception as e:
        print(f"[登录] ✗ 填充密码失败: {e}")
        return False

    # 尝试自动点击登录按钮
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
                    print("[登录] ✓ 已自动点击登录按钮")
                    break
            except:
                continue
    except:
        pass

    # 等待用户完成验证码
    print(f"\n{'='*50}")
    print(f"请在 {wait_captcha_seconds} 秒内完成验证码并点击登录...")
    print(f"{'='*50}\n")

    # 等待登录成功（检测URL变化）
    for i in range(wait_captcha_seconds):
        await asyncio.sleep(1)
        current_url = page.url

        if not is_login_page(current_url):
            print(f"\n[登录] ✓ 登录成功！")
            await asyncio.sleep(2)  # 等待页面稳定
            return True

        # 每10秒提示一次
        remaining = wait_captcha_seconds - i - 1
        if remaining > 0 and remaining % 10 == 0:
            print(f"[登录] 等待中... 剩余 {remaining} 秒")

    print(f"\n[登录] ✗ 登录超时")
    return False


async def create_browser_context(playwright, headless: bool = False) -> Tuple[Browser, BrowserContext]:
    """
    创建浏览器上下文，自动加载已保存的会话状态

    Returns:
        Tuple: (browser, context)
    """
    print("[浏览器] 正在启动...")
    browser = await playwright.chromium.launch(
        headless=headless,
        args=['--start-maximized']
    )

    # 尝试加载已保存的会话
    session_path = await load_session_if_exists()

    if session_path:
        try:
            context = await browser.new_context(
                no_viewport=True,
                storage_state=session_path
            )
            print("[浏览器] ✓ 已加载保存的登录状态")
        except Exception as e:
            print(f"[浏览器] 加载会话失败，使用新会话: {e}")
            context = await browser.new_context(no_viewport=True)
    else:
        context = await browser.new_context(no_viewport=True)
        print("[浏览器] 使用新会话")

    return browser, context
