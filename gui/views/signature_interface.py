"""
签章页管理界面
支持自动下载签章页、自动签名、应用扫描效果
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QFileDialog)
from qfluentwidgets import (ScrollArea, PushButton, FluentIcon,
                            MessageBox, InfoBar, InfoBarPosition, TextEdit,
                            BodyLabel, LineEdit, ComboBox)
import json
from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from ..common.signal_bus import signal_bus
from config import OUTPUT_DIR, BASE_DIR as PROJECT_BASE


class SignatureInterface(ScrollArea):
    """签章页管理界面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.setObjectName("signatureInterface")
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.submit_config_path = PROJECT_BASE / "config" / "submit_config.json"
        self.current_worker = None
        self.is_processing = False

        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        # 步骤1: 下载签章页
        download_group = self.create_download_group()

        # 步骤2: 自动签名
        sign_group = self.create_sign_group()

        # 步骤2.5: 一键签名+扫描（快捷功能）
        one_click_group = self.create_one_click_group()

        # 步骤3: 应用扫描效果
        scan_group = self.create_scan_group()

        # 步骤4: 自动提交签章页
        upload_group = self.create_upload_group()

        # 日志区域
        log_label = BodyLabel("操作日志:", self.view)
        self.log_view = TextEdit(self.view)
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(200)

        # 布局
        self.vBoxLayout.setSpacing(20)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.addWidget(download_group)
        self.vBoxLayout.addWidget(sign_group)
        self.vBoxLayout.addWidget(one_click_group)
        self.vBoxLayout.addWidget(scan_group)
        self.vBoxLayout.addWidget(upload_group)
        self.vBoxLayout.addWidget(log_label)
        self.vBoxLayout.addWidget(self.log_view)
        self.vBoxLayout.addStretch(1)

    def create_download_group(self):
        """创建下载签章页分组"""
        group = QGroupBox("步骤1: 下载签章页", self.view)
        layout = QVBoxLayout(group)

        # 账号选择
        account_layout = QHBoxLayout()
        account_label = BodyLabel("登录账号:", group)
        self.account_combo = ComboBox(group)
        self.account_combo.setFixedWidth(300)
        self.load_accounts()

        account_layout.addWidget(account_label)
        account_layout.addWidget(self.account_combo)
        account_layout.addStretch(1)

        # 说明
        desc_label = BodyLabel(
            "功能说明: 自动登录软著中心账号，下载所有待签章的签章页到 签章页/ 目录",
            group
        )
        desc_label.setWordWrap(True)

        # 下载按钮
        download_btn = PushButton(FluentIcon.DOWNLOAD, "开始下载签章页", group)
        download_btn.clicked.connect(self.on_download_signatures)
        download_btn.setFixedWidth(200)

        layout.addLayout(account_layout)
        layout.addWidget(desc_label)
        layout.addWidget(download_btn)

        return group

    def create_sign_group(self):
        """创建自动签名分组"""
        group = QGroupBox("步骤2: 自动签名", self.view)
        layout = QVBoxLayout(group)

        # 签名文件夹路径
        folder_layout = QHBoxLayout()
        folder_label = BodyLabel("签名文件夹:", group)
        self.sign_folder_edit = LineEdit(group)
        self.sign_folder_edit.setPlaceholderText("选择包含签名图片的文件夹")
        self.sign_folder_edit.setText(str(PROJECT_BASE / "签名"))

        browse_btn = PushButton(FluentIcon.FOLDER, "浏览", group)
        browse_btn.clicked.connect(self.on_browse_sign_folder)
        browse_btn.setFixedWidth(100)

        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.sign_folder_edit)
        folder_layout.addWidget(browse_btn)

        # 说明
        desc_label = BodyLabel(
            "功能说明: 从签名文件夹中随机选择签名图片，插入到签章页的指定位置\n"
            "输入目录: 签章页/ | 输出目录: 已签名/ | 支持格式: PNG, JPG",
            group
        )
        desc_label.setWordWrap(True)

        # 签名按钮
        sign_btn = PushButton(FluentIcon.EDIT, "开始自动签名", group)
        sign_btn.clicked.connect(self.on_auto_sign)
        sign_btn.setFixedWidth(200)

        layout.addLayout(folder_layout)
        layout.addWidget(desc_label)
        layout.addWidget(sign_btn)

        return group

    def create_one_click_group(self):
        """创建一键签名+扫描分组"""
        group = QGroupBox("快捷功能: 一键签名+扫描", self.view)
        layout = QVBoxLayout(group)

        # 说明
        desc_label = BodyLabel(
            "功能说明: 合并步骤2和步骤3，一键完成签名和扫描效果处理\n"
            "流程: 签章页/ → 已签名/ → 最终提交/\n"
            "适用于已经下载好签章页，希望一次性完成所有处理的场景",
            group
        )
        desc_label.setWordWrap(True)

        # 一键按钮
        one_click_btn = PushButton(FluentIcon.PLAY, "一键签名+扫描", group)
        one_click_btn.clicked.connect(self.on_sign_and_scan)
        one_click_btn.setFixedWidth(200)

        layout.addWidget(desc_label)
        layout.addWidget(one_click_btn)

        return group

    def create_scan_group(self):
        """创建扫描效果分组"""
        group = QGroupBox("步骤3: 应用扫描效果", self.view)
        layout = QVBoxLayout(group)

        # 说明
        desc_label = BodyLabel(
            "功能说明: 对已签名的PDF应用真实扫描效果（灰度、倾斜、模糊、纸张褶皱等）\n"
            "输入目录: 已签名/ | 输出目录: 最终提交/ | DPI: 200",
            group
        )
        desc_label.setWordWrap(True)

        # 扫描按钮
        scan_btn = PushButton(FluentIcon.PHOTO, "应用扫描效果", group)
        scan_btn.clicked.connect(self.on_apply_scan_effect)
        scan_btn.setFixedWidth(200)

        layout.addWidget(desc_label)
        layout.addWidget(scan_btn)

        return group

    def create_upload_group(self):
        """创建自动提交分组"""
        group = QGroupBox("步骤4: 自动提交签章页", self.view)
        layout = QVBoxLayout(group)

        # 账号选择
        account_layout = QHBoxLayout()
        account_label = BodyLabel("登录账号:", group)
        self.upload_account_combo = ComboBox(group)
        self.upload_account_combo.setFixedWidth(300)
        self.load_upload_accounts()

        account_layout.addWidget(account_label)
        account_layout.addWidget(self.upload_account_combo)
        account_layout.addStretch(1)

        # 说明
        desc_label = BodyLabel(
            "功能说明: 自动登录软著中心账号，扫描项目列表，根据流水号匹配并上传签章页\n"
            "输入目录: 最终提交/ | 自动匹配项目名称和流水号",
            group
        )
        desc_label.setWordWrap(True)

        # 提交按钮
        upload_btn = PushButton(FluentIcon.SEND, "开始自动提交", group)
        upload_btn.clicked.connect(self.on_upload_signatures)
        upload_btn.setFixedWidth(200)

        layout.addLayout(account_layout)
        layout.addWidget(desc_label)
        layout.addWidget(upload_btn)

        return group

    def load_accounts(self):
        """加载账号配置"""
        if self.submit_config_path.exists():
            try:
                with open(self.submit_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                    if "accounts" in config:
                        accounts = config.get("accounts", [])
                        if accounts:
                            for account in accounts:
                                username = account.get("username", "")
                                desc = account.get("description", "")
                                if username:
                                    display_text = f"{username} ({desc})" if desc else username
                                    self.account_combo.addItem(display_text, userData=account)
                        else:
                            self.account_combo.addItem("未配置账号")
                    elif "username" in config:
                        username = config.get("username", "未配置")
                        self.account_combo.addItem(username, userData=config)
                    else:
                        self.account_combo.addItem("配置格式错误")
            except Exception as e:
                self.account_combo.addItem(f"配置加载失败: {str(e)}")
        else:
            self.account_combo.addItem("未配置账号")

    def load_upload_accounts(self):
        """加载上传账号配置（复用下载账号的加载逻辑）"""
        if self.submit_config_path.exists():
            try:
                with open(self.submit_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                    if "accounts" in config:
                        accounts = config.get("accounts", [])
                        if accounts:
                            for account in accounts:
                                username = account.get("username", "")
                                desc = account.get("description", "")
                                if username:
                                    display_text = f"{username} ({desc})" if desc else username
                                    self.upload_account_combo.addItem(display_text, userData=account)
                        else:
                            self.upload_account_combo.addItem("未配置账号")
                    elif "username" in config:
                        username = config.get("username", "未配置")
                        self.upload_account_combo.addItem(username, userData=config)
                    else:
                        self.upload_account_combo.addItem("配置格式错误")
            except Exception as e:
                self.upload_account_combo.addItem(f"配置加载失败: {str(e)}")
        else:
            self.upload_account_combo.addItem("未配置账号")

    def on_browse_sign_folder(self):
        """浏览签名文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择签名文件夹",
            str(PROJECT_BASE)
        )
        if folder:
            self.sign_folder_edit.setText(folder)

    def on_download_signatures(self):
        """下载签章页"""
        if self.is_processing:
            InfoBar.warning(
                title="任务进行中",
                content="已有任务正在运行，请等待完成",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        current_index = self.account_combo.currentIndex()
        selected_account = self.account_combo.itemData(current_index)

        if not selected_account or not isinstance(selected_account, dict):
            InfoBar.error(
                title="未选择账号",
                content="请先配置并选择登录账号",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        result = MessageBox(
            "确认下载",
            "将自动登录软著中心账号并下载所有签章页\n"
            "下载过程中可能需要手动输入验证码\n\n"
            "确定继续吗？",
            self
        ).exec()

        if not result:
            return

        self.is_processing = True
        self.log_view.append("\n[START] 开始下载签章页...\n")
        self.log_view.append(f"[INFO] 账号: {self.account_combo.currentText()}\n")

        try:
            from ..common.worker import TaskWorker

            self.current_worker = TaskWorker(
                "download_signatures",
                "下载签章页",
                selected_account=selected_account
            )

            self.current_worker.log.connect(self._handle_worker_log)
            self.current_worker.finished.connect(self._on_task_finished)

            self.current_worker.start()

        except Exception as e:
            self.log_view.append(f"[ERROR] 启动任务失败: {str(e)}\n")
            self.is_processing = False

    def on_auto_sign(self):
        """自动签名"""
        if self.is_processing:
            InfoBar.warning(
                title="任务进行中",
                content="已有任务正在运行，请等待完成",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        sign_folder = Path(self.sign_folder_edit.text())
        if not sign_folder.exists():
            InfoBar.error(
                title="文件夹不存在",
                content=f"签名文件夹不存在: {sign_folder}",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        sign_images = list(sign_folder.glob("*.png")) + list(sign_folder.glob("*.jpg"))
        if not sign_images:
            InfoBar.error(
                title="无签名图片",
                content="签名文件夹中未找到PNG或JPG图片",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        result = MessageBox(
            "确认签名",
            f"找到 {len(sign_images)} 个签名图片\n"
            "将对 签章页/ 中的PDF进行自动签名\n\n"
            "确定继续吗？",
            self
        ).exec()

        if not result:
            return

        self.is_processing = True
        self.log_view.append("\n[START] 开始自动签名...\n")
        self.log_view.append(f"[INFO] 签名文件夹: {sign_folder}\n")

        try:
            from ..common.worker import TaskWorker

            self.current_worker = TaskWorker(
                "auto_sign",
                "自动签名",
                sign_folder=str(sign_folder)
            )

            self.current_worker.log.connect(self._handle_worker_log)
            self.current_worker.finished.connect(self._on_task_finished)

            self.current_worker.start()

        except Exception as e:
            self.log_view.append(f"[ERROR] 启动任务失败: {str(e)}\n")
            self.is_processing = False

    def on_apply_scan_effect(self):
        """应用扫描效果"""
        if self.is_processing:
            InfoBar.warning(
                title="任务进行中",
                content="已有任务正在运行，请等待完成",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        result = MessageBox(
            "确认应用效果",
            "将对 output/已签名/ 中的PDF应用扫描效果\n"
            "输出到 output/最终提交/\n\n"
            "确定继续吗？",
            self
        ).exec()

        if not result:
            return

        self.is_processing = True
        self.log_view.append("\n[START] 开始应用扫描效果...\n")

        try:
            from ..common.worker import TaskWorker

            self.current_worker = TaskWorker(
                "apply_scan_effect",
                "应用扫描效果"
            )

            self.current_worker.log.connect(self._handle_worker_log)
            self.current_worker.finished.connect(self._on_task_finished)

            self.current_worker.start()

        except Exception as e:
            self.log_view.append(f"[ERROR] 启动任务失败: {str(e)}\n")
            self.is_processing = False

    def on_sign_and_scan(self):
        """一键签名+扫描"""
        if self.is_processing:
            InfoBar.warning(
                title="任务进行中",
                content="已有任务正在运行，请等待完成",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        # 检查签名文件夹
        sign_folder = Path(self.sign_folder_edit.text())
        if not sign_folder.exists():
            InfoBar.error(
                title="签名文件夹不存在",
                content=f"请先设置有效的签名文件夹: {sign_folder}",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        sign_images = list(sign_folder.glob("*.png")) + list(sign_folder.glob("*.jpg"))
        if not sign_images:
            InfoBar.error(
                title="无签名图片",
                content="签名文件夹中未找到PNG或JPG图片",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        # 检查签章页目录
        pdf_dir = PROJECT_BASE / "签章页"
        if not pdf_dir.exists():
            InfoBar.error(
                title="签章页目录不存在",
                content="请先下载签章页到 签章页/ 目录",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        pdf_files = list(pdf_dir.glob("*.pdf"))
        if not pdf_files:
            InfoBar.error(
                title="无签章页文件",
                content="签章页/ 目录中没有PDF文件",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        result = MessageBox(
            "确认一键处理",
            f"将执行以下流程:\n"
            f"1. 对 {len(pdf_files)} 个签章页进行签名\n"
            f"2. 应用扫描效果\n"
            f"3. 输出到 最终提交/ 目录\n\n"
            f"签名图片数量: {len(sign_images)}\n\n"
            "确定继续吗？",
            self
        ).exec()

        if not result:
            return

        self.is_processing = True
        self.log_view.append("\n[START] 开始一键签名+扫描处理...\n")
        self.log_view.append(f"[INFO] 签章页数量: {len(pdf_files)}\n")
        self.log_view.append(f"[INFO] 签名图片数量: {len(sign_images)}\n")

        try:
            from ..common.worker import TaskWorker

            self.current_worker = TaskWorker(
                "sign_and_scan",
                "一键签名+扫描",
                sign_folder=str(sign_folder)
            )

            self.current_worker.log.connect(self._handle_worker_log)
            self.current_worker.finished.connect(self._on_task_finished)

            self.current_worker.start()

        except Exception as e:
            self.log_view.append(f"[ERROR] 启动任务失败: {str(e)}\n")
            self.is_processing = False

    def _handle_worker_log(self, message: str):
        """处理Worker日志"""
        self.log_view.append(f"{message}\n")

    def on_upload_signatures(self):
        """自动提交签章页"""
        if self.is_processing:
            InfoBar.warning(
                title="任务进行中",
                content="已有任务正在运行，请等待完成",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        current_index = self.upload_account_combo.currentIndex()
        selected_account = self.upload_account_combo.itemData(current_index)

        if not selected_account or not isinstance(selected_account, dict):
            InfoBar.error(
                title="未选择账号",
                content="请先配置并选择登录账号",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        # 检查最终提交目录
        final_dir = PROJECT_BASE / "最终提交"
        if not final_dir.exists() or not list(final_dir.glob("*.pdf")):
            InfoBar.error(
                title="无文件可提交",
                content="最终提交/ 目录中没有PDF文件",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        pdf_count = len(list(final_dir.glob("*.pdf")))

        result = MessageBox(
            "确认提交",
            f"将自动登录软著中心账号并上传签章页\n"
            f"找到 {pdf_count} 个PDF文件待上传\n"
            f"上传过程中可能需要手动输入验证码\n\n"
            "确定继续吗？",
            self
        ).exec()

        if not result:
            return

        self.is_processing = True
        self.log_view.append("\n[START] 开始自动提交签章页...\n")
        self.log_view.append(f"[INFO] 账号: {self.upload_account_combo.currentText()}\n")
        self.log_view.append(f"[INFO] 待上传文件数: {pdf_count}\n")

        try:
            from ..common.worker import TaskWorker

            self.current_worker = TaskWorker(
                "upload_signatures",
                "自动提交签章页",
                selected_account=selected_account
            )

            self.current_worker.log.connect(self._handle_worker_log)
            self.current_worker.finished.connect(self._on_task_finished)

            self.current_worker.start()

        except Exception as e:
            self.log_view.append(f"[ERROR] 启动任务失败: {str(e)}\n")
            self.is_processing = False

    def _on_task_finished(self, success: bool, message: str):
        """任务完成回调"""
        self.is_processing = False

        if success:
            InfoBar.success(
                title="任务完成",
                content=message,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            self.log_view.append(f"\n[SUCCESS] {message}\n")
        else:
            InfoBar.error(
                title="任务失败",
                content=message,
                parent=self,
                position=InfoBarPosition.TOP
            )
            self.log_view.append(f"\n[ERROR] {message}\n")
