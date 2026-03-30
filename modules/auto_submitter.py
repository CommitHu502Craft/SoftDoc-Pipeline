"""
软著自动提交模块
实现版权局官网的完整自动化提交流程
"""
import asyncio
import json
import logging
import random
import time
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout
from modules.artifact_naming import (
    first_existing_artifact_path,
    preferred_artifact_path,
    resolve_project_identity,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("AutoSubmitter")

class CopyrightSubmitter:
    """版权局自动提交器"""
    
    BASE_URL = "https://register.ccopyright.com.cn"
    LOGIN_URL = f"{BASE_URL}/login.html"
    
    # 步骤映射，用于断点恢复
    STEPS = {
        1: '_step_login',
        2: '_step_identity',
        3: '_step_application',
        4: '_step_development',
        5: '_step_features',
        6: '_step_upload', # 注意：features 内部会调用 upload，这个 step 保留用于逻辑兼容
        7: '_step_confirm'
    }
    
    # 固定环境模板 (User Defined) - 按语言分类
    ENV_TEMPLATES = {
        "python": {
            "dev_hardware": "Windows/Linux系统的开发工作站",
            "run_hardware": "服务器配置：4核CPU、8GB内存、50GB存储空间以上；终端设备：PC端和移动设备",
            "dev_os": "Windows 11 / Ubuntu 22.04",
            "dev_tools": "PyCharm，Visual Studio Code",
            "run_platform": "Windows Server 2019及以上，Linux（CentOS 7.6/Ubuntu 20.04）",
            "run_environment": "数据库：MySQL 8.0+；缓存：Redis 6.0+；运行时：Python 3.10+",
            "languages": ["Python", "HTML", "JavaScript", "PL/SQL"],
        },
        "java": {
            "dev_hardware": "Windows/Linux系统的开发工作站",
            "run_hardware": "服务器配置：4核CPU、8GB内存、50GB存储空间以上；终端设备：PC端和移动设备",
            "dev_os": "Windows 11 / Ubuntu 22.04",
            "dev_tools": "IntelliJ IDEA，Maven",
            "run_platform": "Windows Server 2019及以上，Linux（CentOS 7.6/Ubuntu 20.04）",
            "run_environment": "数据库：MySQL 8.0+；缓存：Redis 6.0+；运行时：JDK 17+",
            "languages": ["Java", "HTML", "JavaScript", "PL/SQL"],
        },
        "nodejs": {
            "dev_hardware": "Windows/Linux系统的开发工作站",
            "run_hardware": "服务器配置：4核CPU、8GB内存、50GB存储空间以上；终端设备：PC端和移动设备",
            "dev_os": "Windows 11 / Ubuntu 22.04",
            "dev_tools": "Visual Studio Code，WebStorm",
            "run_platform": "Windows Server 2019及以上，Linux（CentOS 7.6/Ubuntu 20.04）",
            "run_environment": "数据库：MySQL 8.0+ / MongoDB 5.0+；运行时：Node.js 18+",
            "languages": ["JavaScript", "TypeScript", "HTML", "PL/SQL"],
        },
        "default": {
            "dev_hardware": "Windows系统的笔记本电脑",
            "run_hardware": "服务器配置：4核CPU、8GB内存、500GB存储空间以上；终端设备：PC端和移动设备",
            "dev_os": "Windows 11",
            "dev_tools": "Visual Studio Code",
            "run_platform": "Windows Server 2016及以上，Linux各发行版",
            "run_environment": "数据库：MySQL 5.7或以上；编程环境：Java、Python、JavaScript",
            "languages": ["Python", "HTML", "Java", "PL/SQL"],
        }
    }

    def _get_env_template(self) -> dict:
        """根据项目目标语言获取对应的环境模板"""
        genome = self.plan.get("genome", {})
        target_lang = genome.get("target_language", "python").lower()

        # 映射语言名称
        lang_map = {
            "python": "python",
            "java": "java",
            "node.js": "nodejs",
            "nodejs": "nodejs",
            "javascript": "nodejs",
        }

        template_key = lang_map.get(target_lang, "default")
        return self.ENV_TEMPLATES.get(template_key, self.ENV_TEMPLATES["default"])

    def __init__(self, project_name: str, output_dir: Path, config_path: Path, page: Optional[Page] = None, selected_account: dict = None):
        self.project_name = project_name
        self.output_dir = output_dir
        self.project_dir = output_dir / project_name
        self.identity = resolve_project_identity(project_name=project_name, project_dir=self.project_dir)
        self.software_full_name = str(self.identity.get("software_full_name") or project_name).strip() or project_name
        self.page = page  # 允许外部传入 Page 对象
        self.browser = None

        # 加载配置
        logger.info(f"正在加载配置文件: {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        # 处理账号信息：优先使用选中的账号，否则从配置文件读取
        if selected_account:
            # 用户在GUI中选择了特定账号
            self.username = selected_account.get('username', '')
            self.password = selected_account.get('password', '')
            logger.info(f"使用GUI选中的账号: {self.username[:3]}*** ({selected_account.get('description', '')})")
        elif 'accounts' in self.config:
            # 新格式：多账号数组，使用第一个账号
            accounts = self.config.get('accounts', [])
            if accounts:
                first_account = accounts[0]
                self.username = first_account.get('username', '')
                self.password = first_account.get('password', '')
                logger.info(f"使用配置文件中的第一个账号: {self.username[:3]}*** ({first_account.get('description', '')})")
            else:
                raise ValueError("配置文件中 accounts 数组为空")
        elif 'username' in self.config:
            # 兼容旧格式：单账号
            self.username = self.config.get('username', '')
            self.password = self.config.get('password', '')
            logger.info(f"使用旧格式配置的账号: {self.username[:3]}***")
        else:
            raise ValueError("配置文件格式错误：未找到 username 或 accounts 字段")

        # 验证账号信息
        if not self.username or not self.password:
            raise ValueError("账号或密码为空，请检查配置文件")

        # 调试：打印配置信息
        logger.info(f"配置加载成功 - username: {self.username[:3] if self.username else '(空)'}***, password: {'***' if self.password else '(空)'}")
        logger.info(f"完整配置keys: {list(self.config.keys())}")
            
        # 加载项目规划
        plan_path = self.project_dir / "project_plan.json"
        if not plan_path.exists():
            raise FileNotFoundError(f"未找到项目规划文件: {plan_path}")
        with open(plan_path, 'r', encoding='utf-8') as f:
            self.plan = json.load(f)

        logger.info(f"✓ 已加载项目规划: {plan_path}")
        # 验证关键字段
        if 'copyright_fields' in self.plan:
            logger.info(f"  - 技术特点分类: {self.plan['copyright_fields'].get('tech_category', '未设置')}")
            logger.info(f"  - 面向领域: {self.plan['copyright_fields'].get('industry', '未设置')}")
            
        # 检查文件
        # 用户确认说明书也应为PDF格式（导出后），因此检查 .pdf 而不是 .docx
        self.doc_path = (
            first_existing_artifact_path(self.project_dir, project_name=project_name, artifact_key="manual_pdf")
            or preferred_artifact_path(self.project_dir, project_name=project_name, artifact_key="manual_pdf")
        )
        self.pdf_path = (
            first_existing_artifact_path(self.project_dir, project_name=project_name, artifact_key="code_pdf")
            or preferred_artifact_path(self.project_dir, project_name=project_name, artifact_key="code_pdf")
        )

        # 文件存在性检查
        missing = []
        if not self.doc_path.exists():
            missing.append(f"操作说明书PDF ({self.doc_path.name})")
        if not self.pdf_path.exists():
            missing.append(f"源代码PDF ({self.pdf_path.name})")
        
        if missing:
            raise FileNotFoundError(f"缺少必需的PDF文件: {', '.join(missing)}\n请确保已将说明书Word导出为PDF并保存在相同目录下。")
        
        # 源程序量：按业务策略使用随机范围
        self.source_lines = str(random.randint(3000, 5000))

    async def _execute_flow(self, start_step: int):
        """执行提交流程的核心逻辑"""
        try:
            # 状态机循环
            current_step = start_step

            # 特殊处理：如果不是从第一步开始，需要先手动登录或复用 session
            if start_step > 1:
                 logger.warning("从中间步骤恢复可能需要您已手动登录并处于相关页面。")

            if current_step <= 1:
                # 如果是复用Page模式，可能已经登录了
                # 简单检查：如果已经在内部页面，跳过登录
                try:
                    current_url = self.page.url if self.page else ""
                    if current_url and ("/r11.html" in current_url or "index" in current_url):
                        logger.info("检测到已在系统内部，跳过登录步骤")
                    else:
                        await self._step_login()
                except Exception as e:
                    logger.warning(f"获取页面URL失败: {e}，执行登录")
                    await self._step_login()
                current_step = 2

            if current_step <= 2:
                await self._step_identity()
                current_step = 3

            if current_step <= 3:
                await self._step_application()
                current_step = 4

            if current_step <= 4:
                await self._step_development()
                current_step = 5

            if current_step <= 5:
                await self._step_features()
                current_step = 6

            # 步骤 6 上传已内嵌在 features 中
            if current_step <= 6:
                await self._step_upload()
                current_step = 7

            if current_step <= 7:
                await self._step_confirm()

            logger.info(f"🎉 项目 {self.project_name} 流程执行完毕！")

        except Exception as e:
            logger.error(f"自动化流程出错: {e}")
            await self._capture_error("流程异常")
            raise

    async def run(self, start_step: int = 1, keep_open: bool = False):
        """执行完整的提交流程
        :param start_step: 起始步骤
        :param keep_open: 完成后是否保持浏览器打开（仅在独立运行时有效）
        """
        logger.info(f"启动自动化提交任务: {self.project_name}, 从步骤 {start_step} 开始...")

        if self.page:
            # 复用现有 Page 模式
            await self._execute_flow(start_step)
        else:
            # 独立运行模式
            async with async_playwright() as p:
                # 启动浏览器 - 使用自适应窗口
                self.browser = await p.chromium.launch(
                    headless=False,
                    args=['--start-maximized']
                )
                context = await self.browser.new_context(no_viewport=True)
                self.page = await context.new_page()

                try:
                    await self._execute_flow(start_step)

                    logger.info("🎉 恭喜！全流程执行完毕。")

                    if keep_open:
                        # 保持浏览器打开，直到用户决定关闭
                        logger.info("按 Enter 键关闭浏览器...")
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, input)

                finally:
                    await self.browser.close()

    async def _step_login(self):
        """步骤 1: 登录"""
        logger.info(">>> 开始步骤 1: 登录")
        await self.page.goto(self.LOGIN_URL)
        
        # 等待页面完全加载（10秒）
        logger.info("等待登录页面完全加载（10秒）...")
        await asyncio.sleep(10)
        
        # 尝试自动填充账号密码
        try:
            # 使用实例属性中的账号密码（已在 __init__ 中处理好）
            username = self.username
            password = self.password

            logger.info(f"开始自动填充 - 账号: {username[:3] if username else '(空)'}***, 密码: {'***' if password else '(空)'}")

            if username and password:
                # 简化策略：直接查找所有可能的输入框并填充
                logger.info("正在查找账号输入框...")
                
                # 查找账号输入框（多种策略）
                username_filled = False
                
                # 策略1: 通过 placeholder 定位
                try:
                    logger.info("策略1: 通过 placeholder 定位账号框...")
                    username_locators = [
                        self.page.locator("input[placeholder*='手机']"),
                        self.page.locator("input[placeholder*='用户']"),
                        self.page.locator("input[placeholder*='账号']"),
                        self.page.locator("input[placeholder*='登录']"),
                    ]
                    
                    for loc in username_locators:
                        if await loc.count() > 0:
                            await loc.first.fill(username)
                            logger.info(f"✓ 已填充账号 (placeholder): {username[:3]}***")
                            username_filled = True
                            break
                except Exception as e:
                    logger.warning(f"策略1失败: {e}")
                
                # 策略2: 查找所有可见的 text/tel 类型输入框
                if not username_filled:
                    try:
                        logger.info("策略2: 查找所有可见文本输入框...")
                        all_inputs = await self.page.locator("input").all()
                        logger.info(f"找到 {len(all_inputs)} 个 input 元素")
                        
                        for idx, inp in enumerate(all_inputs):
                            try:
                                input_type = await inp.get_attribute("type")
                                is_visible = await inp.is_visible()
                                logger.info(f"  Input {idx}: type={input_type}, visible={is_visible}")
                                
                                if input_type in ["text", "tel", None] and is_visible:
                                    await inp.fill(username)
                                    logger.info(f"✓ 已填充账号 (第{idx}个input): {username[:3]}***")
                                    username_filled = True
                                    break
                            except Exception as e:
                                logger.debug(f"  Input {idx} 检查失败: {e}")
                                continue
                    except Exception as e:
                        logger.warning(f"策略2失败: {e}")
                
                if not username_filled:
                    logger.error("❌ 所有策略都无法填充账号！")
                
                # 填充密码
                await asyncio.sleep(0.5)
                logger.info("正在查找密码输入框...")
                
                try:
                    pwd_input = self.page.locator("input[type='password']")
                    pwd_count = await pwd_input.count()
                    logger.info(f"找到 {pwd_count} 个密码输入框")
                    
                    if pwd_count > 0:
                        await pwd_input.first.fill(password)
                        logger.info("✓ 已填充密码: ******")
                    else:
                        logger.error("❌ 未找到密码输入框！")
                except Exception as e:
                    logger.error(f"❌ 密码填充失败: {e}")
                
                print("\n" + "="*60)
                if username_filled:
                    print("[OK] 账号密码已自动填充，请手动完成验证码并点击登录")
                else:
                    print("[Warn] 账号填充失败，请手动输入账号密码并完成验证码")
                print("="*60 + "\n")
                
                # 等待用户滑动验证码（给点时间）
                logger.info("等待用户完成验证码（3秒）...")
                await asyncio.sleep(3)
                
                # 自动点击登录按钮
                try:
                    login_btn_selectors = [
                        "button:has-text('登录')",
                        "button[type='submit']",
                        ".login-btn",
                        "button.btn-primary"
                    ]
                    
                    clicked = False
                    for selector in login_btn_selectors:
                        try:
                            btn = self.page.locator(selector)
                            if await btn.count() > 0 and await btn.is_visible():
                                await btn.click()
                                logger.info("✓ 已自动点击登录按钮")
                                clicked = True
                                break
                        except:
                            continue
                    
                    if not clicked:
                        logger.info("未找到登录按钮，请手动点击")
                except Exception as e:
                    logger.warning(f"自动点击登录按钮失败: {e}")
            else:
                logger.warning("配置文件中账号或密码为空，跳过自动填充")
                        
        except Exception as e:
            logger.error(f"自动填充流程出错: {e}")
            import traceback
            traceback.print_exc()

        # 等待登录成功跳转
        # 等待登录成功跳转
        print("\nWaiting for login... (请手动登录)\n")
        # 使用配置的超时时间
        timeout = self.config.get("wait_captcha_seconds", 60)
        # 增加一点 buffer，因为配置的是等待验证码的时间，这里是总登录等待
        max_retries = timeout * 2 
        
        for i in range(max_retries):
            if "/r11.html" in self.page.url or "index" in self.page.url:
                logger.info("✅ 登录成功检测通过！")
                await asyncio.sleep(2) # 等待页面稳定
                return
            if i % 5 == 0:
                # 每5秒打印一次
                pass
            await asyncio.sleep(1)
        raise TimeoutError(f"登录超时 ({timeout}秒)")

    async def _step_identity(self):
        """步骤 2: 身份选择 /identity"""
        logger.info(">>> 开始步骤 2: 身份选择")
        # 确保在正确的 URL
        target_url = "https://register.ccopyright.com.cn/r11.html#/identity"
        if self.page.url != target_url:
            await self.page.goto(target_url)
        
        # 点击 "我是申请人"
        # 尝试通过文本定位
        try:
            await self.page.wait_for_selector("text=我是申请人", timeout=10000)
            await self.page.click("text=我是申请人")
            logger.info("已点击 '我是申请人'")
        except:
            logger.warning("未找到 '我是申请人' 按钮，尝试直接寻找下一步或检查是否已跳过")
        
        await asyncio.sleep(2)

    async def _step_application(self):
        """步骤 3: 填写基本信息 /application"""
        logger.info(">>> 开始步骤 3: 软件基本信息")
        # 使用轮询代替阻塞等待
        await self._wait_for_url_contains("/application", timeout=30)
        await asyncio.sleep(2) # 等待 Vue 渲染
        
        # 1. 软件全称
        # 寻找 placeholder="请输入软件全称"
        await self._fill_by_placeholder("请输入软件全称", self.software_full_name)
        
        # 2. 软件简称 - 留空
        # 寻找 placeholder="请输入软件简称..." 并确保为空
        # await self._fill_by_placeholder("请输入软件简称", "") 
        
        # 3. 版本号
        await self._fill_by_placeholder("请输入版本号", "V1.0")
        
        logger.info("基本信息填写完毕")
        await self._click_next_step()

    async def _step_development(self):
        """步骤 4: 开发信息 /development"""
        logger.info(">>> 开始步骤 4: 开发信息")
        await self._wait_for_url_contains("/development", timeout=30)
        await asyncio.sleep(2)
        
        # 1. 软件分类 - 选择 "应用软件"
        # 关键：需要先点击下拉框触发器，选项才会可见
        try:
            # 策略1: 查找包含 "请选择" 的下拉框触发器
            logger.info("正在定位软件分类下拉框...")
            
            # 尝试多种可能的触发器选择器
            trigger_selectors = [
                ".hd-select",  # 常见的下拉框类名
                "div.el-select",  # Element UI 下拉框
                "div[class*='select']",  # 包含 select 的 div
                "input[placeholder*='请选择']",  # placeholder 包含请选择的输入框
            ]
            
            clicked_trigger = False
            for selector in trigger_selectors:
                try:
                    trigger = self.page.locator(selector).first
                    if await trigger.count() > 0 and await trigger.is_visible():
                        await trigger.click()
                        logger.info(f"✓ 已点击下拉框触发器: {selector}")
                        clicked_trigger = True
                        await asyncio.sleep(1)  # 等待下拉选项展开
                        break
                except:
                    continue
            
            if not clicked_trigger:
                # 备用：尝试点击包含 "软件分类" 文字附近的元素
                logger.info("尝试通过文本定位下拉框...")
                classification_label = self.page.locator("text=软件分类")
                if await classification_label.count() > 0:
                    # 点击 label 的父元素或兄弟元素
                    parent = classification_label.locator("..").first
                    # 在父元素内查找可点击的 div 或 input
                    clickable = parent.locator("div.hd-select, input, div[class*='select']").first
                    if await clickable.count() > 0:
                        await clickable.click()
                        logger.info("✓ 已通过文本定位点击下拉框")
                        await asyncio.sleep(1)
            
            # 现在点击 "应用软件" 选项（此时应该可见了）
            app_software = self.page.get_by_text("应用软件", exact=True)
            if await app_software.count() > 0:
                await app_software.click()
                logger.info("✓ 已选择 '应用软件'")
            else:
                logger.warning("未找到 '应用软件' 选项")
                
        except Exception as e:
            logger.error(f"选择软件分类失败: {e}")
            logger.warning("请手动选择 '应用软件'")

        # 2. 开发完成日期 - 默认今天
        # 日期控件通常很难自动交互，如果默认就是今天则无需操作
        # 如果需要填写，尝试直接 fill 格式化日期
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            # 尝试找日期输入框
            date_input = self.page.locator(".datePicker input")
            if await date_input.count() > 0:
                 # 有些日期控件禁止直接输入，必须点选。
                 # 如果是readonly，通常点击后会弹出当前日期的日历，直接回车或点击“确定”/“今天”
                 await date_input.first.click()
                 await asyncio.sleep(0.5)
                 # 尝试点击“今天”或“确定”
                 today_btn = self.page.get_by_text("今天")
                 if await today_btn.is_visible():
                     await today_btn.click()
                 else:
                     # 尝试直接按回车
                     await self.page.keyboard.press("Enter")
                 logger.info(f"设定日期: {today}")
        except Exception as e:
            logger.warning(f"设置日期失败: {e}")
            
        await self._click_next_step()

    async def _step_features(self):
        """步骤 5: 特征信息 /features (核心表单)"""
        logger.info(">>> 开始步骤 5: 特征信息")
        await self._wait_for_url_contains("/features", timeout=30)
        await asyncio.sleep(2)
        
        # 从项目规划中获取动态字段
        fields = self.plan.get('copyright_fields', {})
        tech_cat = fields.get('tech_category', '其他')
        tech_detail = fields.get('tech_detail', '无')

        # 处理 industry 字段：如果是数组，转换为逗号分隔的字符串
        industry_raw = fields.get('industry', '未填写')
        if isinstance(industry_raw, list):
            industry_str = '、'.join(industry_raw)  # 使用顿号分隔
        else:
            industry_str = industry_raw

        # 打印关键字段用于验证
        logger.info(f"📋 项目动态字段:")
        logger.info(f"  - 开发目的: {fields.get('development_purpose', '未填写')[:30]}...")
        logger.info(f"  - 面向领域（原始）: {industry_raw}")
        logger.info(f"  - 面向领域（填写）: {industry_str}")
        logger.info(f"  - 主要功能: {fields.get('main_functions', '未填写')[:50]}...")
        logger.info(f"  - 技术特点分类: {tech_cat}")
        logger.info(f"  - 技术特点详情: {tech_detail[:30]}...")

        # 获取动态环境模板（根据项目目标语言）
        env_template = self._get_env_template()
        logger.info(f"  - 使用环境模板: {self.plan.get('genome', {}).get('target_language', 'default')}")

        # 映射填充任务
        # 格式：(Label关键词 或 Placeholder关键词, 值)
        fill_tasks = [
            ("开发的硬件环境", env_template['dev_hardware']),
            ("运行的硬件环境", env_template['run_hardware']),
            ("开发该软件的操作系统", env_template['dev_os']),
            ("软件开发环境", env_template['dev_tools']),
            ("该软件的运行平台", env_template['run_platform']),
            ("软件运行支撑环境", env_template['run_environment']),
            ("开发目的", fields.get('development_purpose', '未填写')),
            ("面向领域", industry_str),
            ("软件的主要功能", fields.get('main_functions', '未填写')),
            ("源程序量", self.source_lines)
        ]

        # 1. 执行文本框填充 - 增加超时控制
        logger.info("开始填充环境信息和功能描述...")
        for key, value in fill_tasks:
            # 尝试通过 placeholder 模糊匹配，带超时
            try:
                await asyncio.wait_for(
                    self._fill_fuzzy(key, value),
                    timeout=3.0  # 每个字段最多3秒
                )
            except asyncio.TimeoutError:
                logger.warning(f"填充 [{key}] 超时，跳过")
            except Exception as e:
                logger.debug(f"填充 [{key}] 失败: {e}")
        
        logger.info("环境信息填充完成")
            
        # 2. 编程语言 (多选)
        # 假设是 Checkbox 组
        logger.info("选择编程语言...")
        for lang in env_template['languages']:
            try:
                # 查找包含该语言文本的 checkbox 或 span
                # 这种通常是 click 操作
                await self.page.get_by_text(lang, exact=True).click()
            except:
                pass
                
        # 3. 技术特点 (选择 + 填写)
        # 先选择分类
        logger.info(f"选择技术特点分类: {tech_cat}")
        try:
            # 策略：找"软件的技术特点"的h3标题，然后在同级div内操作
            h3_tech = self.page.locator("h3:has-text('软件的技术特点')").first

            if await h3_tech.count() > 0:
                # 获取h3的父元素（.fillin_item）
                parent = h3_tech.locator("..")

                # 在父元素内找到下拉框（如果有）并选择分类
                # 通常技术特点是复选框，直接点击对应的文字即可
                try:
                    tech_option = parent.get_by_text(tech_cat, exact=True)
                    option_count = await tech_option.count()
                    logger.info(f"找到技术特点选项 '{tech_cat}' 的数量: {option_count}")

                    if option_count > 0:
                        await tech_option.click()
                        logger.info(f"✓ 已选择技术特点分类: {tech_cat}")
                    else:
                        logger.error(f"❌ 未找到技术特点选项: {tech_cat}")
                        # 列出所有可用选项
                        all_options = await parent.locator("label, span").all_inner_texts()
                        logger.info(f"可用的技术特点选项: {all_options}")
                except Exception as e:
                    logger.error(f"❌ 选择技术特点分类失败: {e}")
                    import traceback
                    traceback.print_exc()

                # 填写具体技术特点描述
                await asyncio.sleep(0.5)
                tech_textarea = parent.locator("textarea").first

                if await tech_textarea.count() > 0:
                    await tech_textarea.fill(tech_detail)
                    logger.info(f"✓ 已填写技术特点详情: {tech_detail[:30]}...")
                else:
                    logger.warning("未找到技术特点文本框")
            else:
                logger.error("❌ 未找到'软件的技术特点'标题")

        except Exception as e:
            logger.error(f"❌ 技术特点填写遇到困难: {e}")
            import traceback
            traceback.print_exc()

        # 4. 上传文件 (在 Features 页面底部或 Next 之前)
        # 此时页面还没跳走
        already_navigated = await self._step_upload_logic()

        # 点击下一步（如果上传等待中还没跳转的话）
        if not already_navigated:
            await self._click_next_step()

    async def _step_upload_logic(self):
        """处理文件上传逻辑 (嵌入在 Features 流程中)

        Returns:
            bool: True 如果已经跳转到下一页，False 如果还在当前页
        """
        logger.info(">>> 开始上传材料")
        
        try:
            # 程序鉴别材料 (源代码)
            # 寻找 input type=file. 通常页面上有两个上传点。
            # 很难区分哪个是哪个，通常按顺序：1. 文档 2. 源码，或者反过来。
            # 根据用户描述： "提交程序鉴别材料 以及 文档鉴别材料"
            # 我们可以尝试通过附近的文本来判断
            
            # 方案：遍历所有 file input
            file_inputs = await self.page.locator("input[type='file']").all()
            
            # 使用更智能的定位策略：文本定位
            logger.info(f"找到 {len(file_inputs)} 个上传入口，尝试智能匹配...")
            
            uploaded_pdf = False
            uploaded_doc = False
            
            # 策略：通过定位包含关键字的父元素来找 input
            # 1. 源代码 -> "程序" 或 "Source"
            try:
                # 寻找包含 "程序" 字样的文字，且后面跟着 input type=file
                # XPath: 包含 '程序' 的元素，其后代或兄弟有 input
                # 简化：只通过顺序判断，如果常规检测失败，再尝试智能定位
                if len(file_inputs) >= 2:
                     # 默认顺序：通常网页排版上，先是文档，后是代码？或者反之
                     # 依据用户经验，没有合作协议，所以可能是：
                     # 1. 程序鉴别材料
                     # 2. 文档鉴别材料
                     
                     logger.info("检测到2个上传点，执行默认顺序上传...")
                     # 假设第1个是程序(PDF)，第2个是文档(PDF)
                     
                     # 这里为了稳健，打印提示并等待2秒
                     # 可以在上传后通过文件名验证
                     
                     await file_inputs[0].set_input_files(str(self.pdf_path.absolute()))
                     logger.info(f"已向第1个入口上传源代码: {self.pdf_path.name}")
                     uploaded_pdf = True
                     
                     await asyncio.sleep(1)
                     
                     await file_inputs[1].set_input_files(str(self.doc_path.absolute()))
                     logger.info(f"已向第2个入口上传说明书: {self.doc_path.name}")
                     uploaded_doc = True
            
            except Exception as e:
                logger.warning(f"默认顺序上传失败: {e}")
            
            # 如果默认上传未完全成功，尝试备用逻辑（智能定位）
            if not (uploaded_pdf and uploaded_doc):
                 logger.info("尝试备用智能定位策略...")
                 # ... (此处省略复杂定位，保持简单以免出错)
                 logger.warning("自动上传未完全成功，请手动检查并上传！")

            # 等待上传完成（带重试机制），返回是否已跳转
            return await self._wait_for_upload_completion()

        except Exception as e:
            logger.error(f"上传过程出错: {e}")
            return False

    async def _wait_for_upload_completion(self):
        """
        等待上传完成并尝试点击下一步
        策略：30秒后尝试点击，失败则15秒后重试，最多重试2次
        总时间点：30秒、45秒、60秒各尝试一次

        Returns:
            bool: True 如果已成功跳转到下一页，False 如果未跳转
        """
        wait_times = [30, 15, 15]  # 累计: 30秒, 45秒, 60秒

        for i, wait_time in enumerate(wait_times):
            logger.info(f"等待上传处理 ({wait_time}秒)..." + (f" (第{i}次重试)" if i > 0 else ""))
            await asyncio.sleep(wait_time)

            # 尝试点击下一步按钮
            try:
                next_btn = self.page.locator("button:has-text('下一步')").first
                if await next_btn.count() > 0 and await next_btn.is_visible():
                    is_disabled = await next_btn.get_attribute("disabled")
                    if not is_disabled:
                        logger.info("尝试点击下一步...")
                        await next_btn.click()
                        await asyncio.sleep(2)

                        # 检查是否成功跳转
                        current_url = self.page.url
                        if "/confirm" in current_url:
                            logger.info("上传处理完成，已跳转到确认页")
                            return True
                        elif "/features" not in current_url:
                            logger.info("上传处理完成，页面已跳转")
                            return True
                        else:
                            logger.info("点击后未跳转，继续等待重试...")
                    else:
                        logger.info("下一步按钮仍被禁用，继续等待...")
            except Exception as e:
                logger.debug(f"尝试点击下一步出错: {e}")

        logger.info("上传等待结束，继续下一步")
        return False

    async def _step_upload(self):
        """步骤 6: 独立的上传步骤 (如果存在)"""
        # 根据用户反馈，上传在 Features 页面，所以此步骤可能为空
        # 或者仅仅是确认
        await asyncio.sleep(1)

    async def _step_confirm(self):
        """步骤 7: 确认提交 /confirm"""
        logger.info(">>> 开始步骤 7: 确认提交")
        await self._wait_for_url_contains("/confirm", timeout=30)
        await asyncio.sleep(2)

        # 滚动到底部
        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)

        # 自动点击提交按钮
        try:
            submit_selectors = [
                "button:has-text('提交')",
                "button:has-text('确认提交')",
                ".submit-btn",
                "button[type='submit']"
            ]

            submitted = False
            for selector in submit_selectors:
                try:
                    btn = self.page.locator(selector)
                    if await btn.count() > 0 and await btn.is_visible():
                        logger.info("找到提交按钮，准备自动提交...")
                        await asyncio.sleep(1)  # 稍等1秒确保页面稳定
                        await btn.first.click()
                        logger.info("✅ 已自动点击提交按钮！")
                        submitted = True
                        break
                except:
                    continue

            if not submitted:
                logger.warning("未找到提交按钮，请手动点击提交")
        except Exception as e:
            logger.warning(f"自动提交失败: {e}，请手动点击提交")

        # Bug3修复：改进提交完成判断，处理网站卡顿
        # 等待提交完成的确认
        await self._wait_for_submit_completion()

    async def _wait_for_submit_completion(self, timeout: int = 60):
        """等待提交完成的确认信号
        Bug3修复：改进判断逻辑，处理网站卡顿情况
        """
        logger.info("等待提交完成确认...")
        start_time = asyncio.get_event_loop().time()

        while True:
            try:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    logger.warning(f"⚠ 提交确认超时 ({timeout}秒)，但可能已成功提交")
                    logger.info("💡 提示：请手动检查提交状态，如成功可继续")
                    return True

                # 策略1: 检查URL是否跳转到成功页面或账户页面
                current_url = self.page.url
                if "account.html" in current_url or "success" in current_url.lower():
                    logger.info("✅ 检测到跳转至账户页面，提交成功！")
                    return True

                # 策略2: 检查页面是否出现成功提示
                success_indicators = [
                    "提交成功",
                    "已提交",
                    "申请成功",
                    "受理成功"
                ]

                for indicator in success_indicators:
                    try:
                        element = self.page.locator(f"text={indicator}")
                        if await element.count() > 0:
                            logger.info(f"✅ 检测到成功提示: {indicator}")
                            await asyncio.sleep(2)  # 等待2秒确保提交完成
                            return True
                    except:
                        continue

                # 策略3: 检查是否还在confirm页面（可能卡住了）
                if "/confirm" in current_url:
                    # 检查提交按钮是否消失（说明正在处理）
                    submit_btn = self.page.locator("button:has-text('提交')")
                    btn_count = await submit_btn.count()

                    if btn_count == 0:
                        logger.info("🔄 提交按钮已消失，正在处理中...")
                    elif elapsed > 30:
                        # 超过30秒还在confirm页面且按钮还在，可能需要手动处理
                        logger.warning("⚠ 提交可能需要手动确认，请检查页面")

                await asyncio.sleep(2)  # 每2秒检查一次

            except Exception as e:
                logger.debug(f"提交确认检测异常: {e}")
                await asyncio.sleep(2)

    # --- 辅助方法 ---

    async def _fill_fuzzy(self, keyword: str, value: str):
        """模糊查找输入框并填充 -通过label文字定位"""
        if not value:
            return
        
        try:
            # 策略：在features.html中，每个字段的结构是：
            # <h3><span>字段名</span></h3>
            # <div class="fillin_info">
            #   <textarea placeholder="请输入..." ...></textarea>
            # </div>
            
            # 方法：找到包含keyword的h3，然后在其父元素内找textarea
            
            # 查找包含keyword的h3标签
            h3_loc = self.page.locator(f"h3:has-text('{keyword}')")
            h3_count = await h3_loc.count()
            
            if h3_count == 0:
                # 未找到对应标题
                return
            
            # 获取h3的父元素（通常是 .fillin_item）
            parent = h3_loc.first.locator("..")
            
            # 在父元素内查找textarea或input
            textarea = parent.locator("textarea").first
            if await textarea.count() > 0:
                await textarea.fill(value)
                logger.debug(f"✓ 已填充 [{keyword}]")
                return
            
            # 如果没有textarea，尝试input
            input_field = parent.locator("input[type='text']").first
            if await input_field.count() > 0:
                await input_field.fill(value)
                logger.debug(f"✓ 已填充 [{keyword}]")
                return
                
        except Exception as e:
            logger.debug(f"填充 [{keyword}] 失败: {e}")

    async def _fill_by_placeholder(self, placeholder: str, value: str):
        """通过 placeholder 包含匹配填充"""
        try:
            # get_by_placeholder 默认是 exact=False (部分匹配吗? 不，是 exact=False 且不区分大小写? 文档说默认 strict)
            # 使用 CSS 选择器模糊匹配 placeholder
            selector = f"input[placeholder*='{placeholder}'], textarea[placeholder*='{placeholder}']"
            await self.page.locator(selector).first.fill(value)
            logger.info(f"已填充: {placeholder} -> {value[:10]}...")
        except Exception as e:
            logger.warning(f"无法填充字段 [{placeholder}]: {e}")

    async def _click_next_step(self):
        """点击下一步"""
        try:
            await asyncio.sleep(1)
            # 常见的“下一步”按钮文案
            await self.page.get_by_text("下一步", exact=True).click()
            logger.info("点击了 '下一步'")
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"点击下一步失败 (可能是页面未完成或需要手动操作): {e}")

    async def _wait_for_url_contains(self, url_fragment: str, timeout: int = 30):
        """轮询等待URL包含指定片段，避免阻塞"""
        start_time = asyncio.get_event_loop().time()
        while True:
            try:
                current_url = self.page.url
                if url_fragment in current_url:
                    logger.info(f"✓ URL匹配成功: {current_url}")
                    return True
                
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    logger.warning(f"⚠ URL等待超时 ({timeout}秒)，当前URL: {current_url}")
                    # 不抛异常，继续执行
                    return False
                    
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"URL检测异常: {e}")
                return False
    
    async def _capture_error(self, reason: str):
        path = Path("logs/error.png")
        path.parent.mkdir(exist_ok=True)
        try:
            if self.page and not self.page.is_closed():
                await self.page.screenshot(path=path)
                logger.error(f"已保存错误截图: {path}")
        except:
            pass

    async def _locate_signature_print_button(self):
        """
        在签章列表页定位当前项目对应的“打印签章页”按钮。
        先按软件全称/项目名做行内匹配，失败则回退首个可见按钮。
        """
        if not self.page:
            return None

        print_buttons = self.page.get_by_text("打印签章页")
        total = await print_buttons.count()
        if total <= 0:
            return None

        lookup_tokens = []
        if self.software_full_name:
            lookup_tokens.append(self.software_full_name)
        if self.project_name and self.project_name not in lookup_tokens:
            lookup_tokens.append(self.project_name)

        for token in lookup_tokens:
            try:
                token_matches = self.page.get_by_text(token)
                match_count = await token_matches.count()
            except Exception:
                match_count = 0
            for idx in range(min(match_count, 3)):
                try:
                    item = token_matches.nth(idx)
                    row = item.locator("xpath=ancestor::tr[1]").first
                    if await row.count() > 0:
                        row_btn = row.get_by_text("打印签章页").first
                        if await row_btn.count() > 0 and await row_btn.is_visible():
                            logger.info(f"已按项目标识定位到签章按钮: {token}")
                            return row_btn
                except Exception:
                    continue

        for idx in range(total):
            try:
                btn = print_buttons.nth(idx)
                if await btn.is_visible():
                    logger.warning("未精确命中项目行，回退首个可见签章按钮")
                    return btn
            except Exception:
                continue
        return print_buttons.first

    async def download_sign_pdf(self):
        """下载签章页PDF"""
        logger.info(">>> 开始下载签章页 PDF")
        try:
            # 1. 跳转到用户中心
            user_center_url = "https://register.ccopyright.com.cn/account.html?current=soft_register"
            if "account.html" not in self.page.url:
                logger.info("跳转到用户中心...")
                await self.page.goto(user_center_url)
                await self.page.wait_for_load_state('networkidle')

            # 2. 查找当前项目的记录
            # 假设列表按时间排序，最新的在最上面。或者我们可以搜索项目名称。
            # 为了准确，我们尝试搜索项目名称
            # 这里的选择器需要根据实际页面结构调整，根据您提供的html，似乎是一个表格或列表

            # 简单策略：查找包含项目名称的行，然后找该行内的 "打印签章页" 按钮
            # 注意：项目名称可能被截断，或者显示不全。
            # 更稳妥的策略：如果是刚提交的，通常是列表的第一项。

            logger.info(f"查找项目 [{self.software_full_name}] 的签章页按钮...")

            # 等待列表加载
            await asyncio.sleep(2)

            print_btn = await self._locate_signature_print_button()
            if not print_btn or await print_btn.count() == 0:
                logger.error("未找到 '打印签章页' 按钮")
                return

            # 3. 点击打印签章页
            logger.info("点击 '打印签章页'...")
            # 可能会打开新标签页，需要处理
            async with self.page.context.expect_page() as new_page_info:
                await print_btn.click()

            print_page = await new_page_info.value
            await print_page.wait_for_load_state('networkidle')
            logger.info(f"已打开打印页: {print_page.url}")

            # 4. 在打印页点击 "打印" 按钮，进入最终的打印预览页 (点击打印后.html)
            # 根据您的描述：打印页点击”打印“之后跳转到点击打印后

            # 查找页面上的 "打印" 按钮
            # 这里的 selector 需要根据 打印页.html 确定
            # 假设是一个由文字 "打印" 组成的按钮
            final_print_btn = print_page.get_by_text("打印", exact=True)
            if await final_print_btn.count() > 0:
                logger.info("点击页面上的 '打印' 按钮...")
                await final_print_btn.click()
                # 这里可能会跳转，或者是一个弹窗？
                # 根据描述：跳转到点击打印后
                await asyncio.sleep(2) # 等待跳转或渲染
            else:
                logger.warning("未找到 '打印' 按钮，假设当前即为可打印页面")

            # 5. 获取流水号并保存 PDF
            # 尝试从 URL 获取流水号: ...?flowNumber=2026R11L0125852...
            flow_number = "unknown"
            try:
                from urllib.parse import urlparse, parse_qs
                parsed_url = urlparse(print_page.url)
                params = parse_qs(parsed_url.query)
                if 'flowNumber' in params:
                    flow_number = params['flowNumber'][0]
                    logger.info(f"获取到流水号: {flow_number}")
                else:
                    # 尝试从页面内容获取
                    # 假设页面上有显示流水号的地方
                    content = await print_page.content()
                    import re
                    match = re.search(r"20\d{2}R\d{2}L\d+", content)
                    if match:
                        flow_number = match.group(0)
                        logger.info(f"从页面内容提取流水号: {flow_number}")
            except Exception as e:
                logger.warning(f"获取流水号失败: {e}")
                # 使用时间戳作为备选
                import time
                flow_number = f"sign_page_{int(time.time())}"

            # 6. 保存 PDF
            pdf_filename = f"{flow_number}.pdf"
            save_path = self.project_dir / pdf_filename

            logger.info(f"正在保存 PDF 到: {save_path}")

            # 使用 page.pdf() 生成 PDF
            # 注意：需要模拟 print 媒体类型以获得最佳效果
            await print_page.emulate_media(media="print")
            await print_page.pdf(path=save_path, format="A4", print_background=True)

            logger.info(f"✅ 签章页 PDF 下载成功！")

            # 关闭打印页
            await print_page.close()

        except Exception as e:
            logger.error(f"下载签章页 PDF 失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

async def auto_submit(project_name: str, output_dir: Path, config_path: Path, start_step: int = 1):
    submitter = CopyrightSubmitter(project_name, output_dir, config_path)
    await submitter.run(start_step=start_step, keep_open=True)

async def auto_submit_batch(project_names: list, output_dir: Path, config_path: Path, selected_account: dict = None):
    """
    批量提交项目，复用浏览器会话
    :param project_names: 项目名称列表
    :param output_dir: 输出目录
    :param config_path: 配置文件路径
    :param selected_account: 用户选中的账号信息（包含username和password）
    """
    logger.info(f"启动批量提交任务，共 {len(project_names)} 个项目")

    # 如果传入了选中的账号，记录日志
    if selected_account:
        logger.info(f"使用指定账号: {selected_account.get('username', '未知')} ({selected_account.get('description', '')})")

    async with async_playwright() as p:
        # 1. 启动浏览器 (只启动一次)
        browser = await p.chromium.launch(
            headless=False,
            args=['--start-maximized']
        )
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()

        try:
            # 2. 依次处理每个项目
            for i, project_name in enumerate(project_names, 1):
                logger.info(f"===== 开始处理第 {i}/{len(project_names)} 个项目: {project_name} =====")
                try:
                    # 创建提交器，传入共享的 page 和选中的账号
                    submitter = CopyrightSubmitter(project_name, output_dir, config_path, page=page, selected_account=selected_account)

                    # 如果不是第一个项目，需要重置页面到初始状态
                    if i > 1:
                        logger.info("重置页面状态...")
                        # 直接跳转到身份选择页面，开始新的提交流程
                        await page.goto("https://register.ccopyright.com.cn/r11.html#/identity")
                        await asyncio.sleep(2)
                        # 后续项目跳过登录步骤（已经登录）
                        await submitter.run(start_step=2)
                    else:
                        # 第一个项目需要登录
                        await submitter.run(start_step=1)

                    logger.info(f"===== 项目 {project_name} 处理完成 =====")

                    # 提交完成后，移动项目到"已提交"文件夹
                    try:
                        move_to_submitted(project_name, output_dir)
                    except Exception as e:
                        logger.error(f"移动项目到已提交文件夹失败: {e}")

                    # 提交完成后，通常停留在 confirm 页面或列表页。
                    # 给一点缓冲时间
                    await asyncio.sleep(3)

                    # Bug2修复：不再自动下载签章页，用户可以使用批量下载功能
                    # 下载签章页
                    # try:
                    #     await submitter.download_sign_pdf()
                    # except Exception as e:
                    #     logger.error(f"下载签章页失败: {e}")

                except Exception as e:
                    logger.error(f"项目 {project_name} 处理失败: {e}")
                    # 即使失败，也尝试继续下一个？
                    # 通常如果 session 还在，可以继续。
                    await asyncio.sleep(5)

            logger.info("🎉 所有批量任务执行完毕！")

            # Bug1修复：保持浏览器打开，直到用户手动关闭窗口
            # 使用更健壮的连接检测，避免状态不一致
            logger.info("浏览器保持开启中。请在检查完毕后手动关闭浏览器窗口以结束任务...")
            try:
                while browser.is_connected():
                    await asyncio.sleep(1)
            except Exception as e:
                logger.info(f"浏览器连接已断开: {e}")

        except Exception as outer_e:
            logger.error(f"批量任务异常: {outer_e}")

        finally:
            # Bug1修复：确保无论如何都清理资源和重置状态
            # 只有当浏览器断开连接（用户关闭）或者发生异常时才会执行到这里
            # 如果 browser.is_connected() 为 False，close() 是安全的（幂等或抛错被忽略）
            try:
                if browser and browser.is_connected():
                    await browser.close()
            except:
                pass

            logger.info("任务完全结束，资源已清理")


def move_to_submitted(project_name: str, output_dir: Path) -> bool:
    """
    将已提交的项目移动到"已提交"文件夹

    :param project_name: 项目名称
    :param output_dir: 输出目录
    :return: 是否移动成功
    """
    try:
        # 源项目目录
        source_dir = output_dir / project_name

        # 目标"已提交"目录
        submitted_dir = output_dir / "已提交"
        submitted_dir.mkdir(exist_ok=True)

        # 目标项目目录
        target_dir = submitted_dir / project_name

        # 检查源目录是否存在
        if not source_dir.exists():
            logger.warning(f"项目目录不存在: {source_dir}")
            return False

        # 如果目标已存在，先删除或重命名
        if target_dir.exists():
            # 备份旧的已提交项目（加上时间戳）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = submitted_dir / f"{project_name}_备份_{timestamp}"
            logger.info(f"目标目录已存在，备份为: {backup_dir.name}")
            shutil.move(str(target_dir), str(backup_dir))

        # 移动项目目录
        logger.info(f"移动项目: {source_dir} → {target_dir}")
        shutil.move(str(source_dir), str(target_dir))

        logger.info(f"✓ 项目 {project_name} 已移动到已提交文件夹")
        return True

    except Exception as e:
        logger.error(f"移动项目失败: {e}")
        import traceback
        traceback.print_exc()
        return False
