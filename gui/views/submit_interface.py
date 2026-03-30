"""
自动提交界面
管理软著材料自动提交任务
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QHeaderView)
from qfluentwidgets import (ScrollArea, PushButton, FluentIcon, ComboBox,
                            MessageBox, InfoBar, InfoBarPosition, TextEdit, BodyLabel)
import json
import re
import shutil
from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from ..common.signal_bus import signal_bus
from config import OUTPUT_DIR, BASE_DIR as PROJECT_BASE

# 已提交文件夹路径
SUBMITTED_DIR = OUTPUT_DIR / "已提交"


class SubmitInterface(ScrollArea):
    """自动提交界面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.setObjectName("submitInterface")
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.submit_config_path = PROJECT_BASE / "config" / "submit_config.json"
        self.submit_queue = []  # 提交队列
        self.current_worker = None
        self.is_submitting = False

        self.init_ui()
        self.connect_signals()

    def init_ui(self):
        """初始化UI"""
        # 工具栏 - 第一行：账号选择
        toolbar_row1 = QHBoxLayout()

        # 账号选择
        account_label = BodyLabel("提交账号:", self.view)
        self.account_combo = ComboBox(self.view)
        self.account_combo.setFixedWidth(200)
        self.load_accounts()

        toolbar_row1.addWidget(account_label)
        toolbar_row1.addWidget(self.account_combo)
        toolbar_row1.addStretch(1)

        # 工具栏 - 第二行：操作按钮
        toolbar_row2 = QHBoxLayout()

        # 操作按钮
        move_to_submitted_btn = PushButton(FluentIcon.FOLDER_ADD, "移动到已提交", self.view)
        move_to_submitted_btn.clicked.connect(self.on_move_to_submitted)

        clear_queue_btn = PushButton(FluentIcon.DELETE, "清空队列", self.view)
        clear_queue_btn.clicked.connect(self.on_clear_queue)

        remove_selected_btn = PushButton(FluentIcon.REMOVE, "移除选中", self.view)
        remove_selected_btn.clicked.connect(self.on_remove_selected)

        start_submit_btn = PushButton(FluentIcon.SEND, "开始批量提交", self.view)
        start_submit_btn.clicked.connect(self.on_start_batch_submit)

        toolbar_row2.addWidget(move_to_submitted_btn)
        toolbar_row2.addWidget(clear_queue_btn)
        toolbar_row2.addWidget(remove_selected_btn)
        toolbar_row2.addStretch(1)
        toolbar_row2.addWidget(start_submit_btn)

        # 提交队列表格
        self.queue_table = QTableWidget(self.view)
        self.queue_table.setColumnCount(4)
        self.queue_table.setHorizontalHeaderLabels([
            "项目名称", "状态", "添加时间", "备注"
        ])

        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 4):
            self.queue_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        # 启用多选
        self.queue_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)

        # 日志区域
        log_label = BodyLabel("提交日志:", self.view)
        self.log_view = TextEdit(self.view)
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(150)

        # 布局
        self.vBoxLayout.setSpacing(15)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.addLayout(toolbar_row1)
        self.vBoxLayout.addLayout(toolbar_row2)
        self.vBoxLayout.addWidget(self.queue_table)
        self.vBoxLayout.addWidget(log_label)
        self.vBoxLayout.addWidget(self.log_view)

    def connect_signals(self):
        """连接信号"""
        signal_bus.submit_started.connect(self.on_project_added_to_queue)

    def load_accounts(self):
        """加载账号配置"""
        if self.submit_config_path.exists():
            try:
                with open(self.submit_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                    # 兼容旧格式（单账号）
                    if "username" in config:
                        username = config.get("username", "未配置")
                        self.account_combo.addItem(username)
                    # 新格式（多账号数组）
                    elif "accounts" in config:
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
                    else:
                        self.account_combo.addItem("配置格式错误")
            except Exception as e:
                self.account_combo.addItem(f"配置加载失败: {str(e)}")
        else:
            self.account_combo.addItem("未配置账号")

    def on_project_added_to_queue(self, project_name: str):
        """项目添加到队列"""
        if project_name in self.submit_queue:
            self.log_view.append(f"[INFO] {project_name} 已在队列中\n")
            return

        self.submit_queue.append(project_name)
        self.refresh_queue_table()
        self.log_view.append(f"[INFO] 已添加: {project_name}\n")

    def refresh_queue_table(self):
        """刷新队列表格"""
        self.queue_table.setRowCount(len(self.submit_queue))

        from datetime import datetime
        for row, project_name in enumerate(self.submit_queue):
            # 项目名称
            name_item = QTableWidgetItem(project_name)
            self.queue_table.setItem(row, 0, name_item)

            # 状态
            status_item = QTableWidgetItem("待提交")
            self.queue_table.setItem(row, 1, status_item)

            # 添加时间
            time_item = QTableWidgetItem(datetime.now().strftime('%H:%M:%S'))
            self.queue_table.setItem(row, 2, time_item)

            # 备注
            remark_item = QTableWidgetItem("-")
            self.queue_table.setItem(row, 3, remark_item)

    def on_clear_queue(self):
        """清空队列"""
        if not self.submit_queue:
            return

        result = MessageBox(
            "确认清空",
            f"确定清空 {len(self.submit_queue)} 个待提交项目吗？",
            self
        ).exec()

        if result:
            self.submit_queue.clear()
            self.refresh_queue_table()
            self.log_view.append("[INFO] 队列已清空\n")

    def on_remove_selected(self):
        """移除选中项"""
        selected_rows = set(item.row() for item in self.queue_table.selectedItems())

        if not selected_rows:
            InfoBar.warning(
                title="未选择项目",
                content="请先选择要移除的项目",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        # 从后向前删除，避免索引混乱
        for row in sorted(selected_rows, reverse=True):
            if row < len(self.submit_queue):
                removed = self.submit_queue.pop(row)
                self.log_view.append(f"[INFO] 已移除: {removed}\n")

        self.refresh_queue_table()

    def on_start_batch_submit(self):
        """启动批量提交（复用浏览器会话）"""
        if not self.submit_queue:
            InfoBar.warning(
                title="队列为空",
                content="请先添加项目到提交队列",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        if self.is_submitting:
            InfoBar.warning(
                title="任务进行中",
                content="已有提交任务正在运行，请等待完成",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        result = MessageBox(
            "批量提交确认",
            f"确定开始批量提交 {len(self.submit_queue)} 个项目吗？\n\n"
            "说明：\n"
            "1. 将启动浏览器并自动填写\n"
            "2. 多个项目将复用同一浏览器窗口，无需重复登录\n"
            "3. 遇到验证码时请手动配合\n"
            "4. 任务完成后浏览器将保持开启，请手动关闭以结束",
            self
        ).exec()

        if not result:
            return

        # 更新状态
        self.is_submitting = True
        self.log_view.append(f"\n[START] 开始批量提交，共 {len(self.submit_queue)} 个项目\n")
        self.log_view.append(f"[INFO] 账号: {self.account_combo.currentText()}\n")

        # 启动Worker执行批量任务
        try:
            from ..common.worker import TaskWorker

            # 将整个队列复制一份传给worker
            project_list = list(self.submit_queue)

            # 获取当前选中的账号信息
            current_index = self.account_combo.currentIndex()
            selected_account = self.account_combo.itemData(current_index)

            # 使用 'submit_batch' 任务类型，传递账号信息
            self.current_worker = TaskWorker(
                "submit_batch",
                "批量任务",
                project_list=project_list,
                selected_account=selected_account
            )

            # 连接信号
            self.current_worker.log.connect(self._handle_worker_log)
            self.current_worker.finished.connect(self._on_batch_finished)

            # 启动任务
            self.current_worker.start()

        except Exception as e:
            self.log_view.append(f"[ERROR] 启动任务失败: {str(e)}\n")
            self.is_submitting = False

    def _handle_worker_log(self, message: str):
        """处理Worker日志，解析进度并更新表格"""
        self.log_view.append(f"[LOG] {message}\n")

        # 解析日志来更新表格状态
        # 匹配开始： "===== 开始处理第 i/n 个项目: {project_name} ====="
        start_match = re.search(r"===== 开始处理第 \d+/\d+ 个项目: (.+?) =====", message)
        if start_match:
            project_name = start_match.group(1)
            self._update_row_status(project_name, "提交中...")
            return

        # 匹配成功： "===== 项目 {project_name} 处理完成 ====="
        success_match = re.search(r"===== 项目 (.+?) 处理完成 =====", message)
        if success_match:
            project_name = success_match.group(1)
            self._update_row_status(project_name, "成功")
            return

        # 匹配失败： "项目 {project_name} 处理失败: {e}"
        fail_match = re.search(r"项目 (.+?) 处理失败:", message)
        if fail_match:
            project_name = fail_match.group(1)
            self._update_row_status(project_name, "失败")
            # 也可以提取错误信息更新到备注，这里简化处理
            return

    def _update_row_status(self, project_name: str, status: str):
        """更新指定项目的状态列"""
        try:
            # 找到项目所在的行
            for row in range(self.queue_table.rowCount()):
                item = self.queue_table.item(row, 0)
                if item and item.text() == project_name:
                    self.queue_table.setItem(row, 1, QTableWidgetItem(status))
                    break
        except:
            pass

    def _on_batch_finished(self, success: bool, message: str):
        """批量任务完成回调"""
        # Bug1修复：无论成功失败，都要重置状态，避免卡住
        self.is_submitting = False

        if success:
            InfoBar.success(
                title="批量任务结束",
                content="所有项目的提交流程已执行完毕，请检查浏览器窗口",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000
            )
        else:
            InfoBar.error(
                title="任务异常中止",
                content=f"错误信息: {message}",
                parent=self,
                position=InfoBarPosition.TOP
            )

        # Bug1修复：清理worker引用，允许二次提交
        if self.current_worker:
            try:
                self.current_worker.quit()
                self.current_worker.wait()
            except:
                pass
            self.current_worker = None

        self.log_view.append("[INFO] 状态已重置，可以进行新的提交任务\n")

    def on_move_to_submitted(self):
        """将选中的项目移动到已提交文件夹"""
        # 获取选中的行
        selected_rows = set(item.row() for item in self.queue_table.selectedItems())

        if not selected_rows:
            InfoBar.warning(
                title="未选择项目",
                content="请先在队列中选择要移动的项目",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        # 获取选中的项目名称
        selected_projects = []
        for row in selected_rows:
            if row < len(self.submit_queue):
                selected_projects.append(self.submit_queue[row])

        if not selected_projects:
            return

        # 确认对话框
        result = MessageBox(
            "移动到已提交",
            f"确定将以下 {len(selected_projects)} 个项目移动到\"已提交\"文件夹吗？\n\n"
            f"项目列表:\n" + "\n".join(f"  • {p}" for p in selected_projects[:5]) +
            (f"\n  ... 等共 {len(selected_projects)} 个项目" if len(selected_projects) > 5 else "") +
            f"\n\n移动后项目将从 output/ 移动到 output/已提交/",
            self
        ).exec()

        if not result:
            return

        # 确保目标文件夹存在
        SUBMITTED_DIR.mkdir(parents=True, exist_ok=True)

        # 执行移动
        success_count = 0
        fail_count = 0
        moved_projects = []

        for project_name in selected_projects:
            try:
                source_path = OUTPUT_DIR / project_name
                target_path = SUBMITTED_DIR / project_name

                if not source_path.exists():
                    self.log_view.append(f"[WARN] 项目文件夹不存在: {project_name}\n")
                    fail_count += 1
                    continue

                if target_path.exists():
                    # 目标已存在，询问是否覆盖
                    self.log_view.append(f"[WARN] 目标已存在，将覆盖: {project_name}\n")
                    shutil.rmtree(target_path)

                # 移动文件夹
                shutil.move(str(source_path), str(target_path))
                self.log_view.append(f"[OK] 已移动: {project_name}\n")
                success_count += 1
                moved_projects.append(project_name)

            except Exception as e:
                self.log_view.append(f"[ERROR] 移动失败 {project_name}: {str(e)}\n")
                fail_count += 1

        # 从队列中移除已移动的项目
        for project_name in moved_projects:
            if project_name in self.submit_queue:
                self.submit_queue.remove(project_name)

        # 刷新表格
        self.refresh_queue_table()

        # 显示结果
        if success_count > 0:
            InfoBar.success(
                title="移动完成",
                content=f"成功移动 {success_count} 个项目到\"已提交\"文件夹" +
                        (f"，{fail_count} 个失败" if fail_count > 0 else ""),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )

            # 通知项目列表刷新
            signal_bus.projects_refresh.emit()
        else:
            InfoBar.error(
                title="移动失败",
                content=f"所有项目移动失败，请检查日志",
                parent=self,
                position=InfoBarPosition.TOP
            )
