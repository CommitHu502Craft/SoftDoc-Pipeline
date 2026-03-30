"""
项目管理界面
核心功能：项目列表、批量操作、状态监控
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QHeaderView, QMenu, QInputDialog)
from PyQt6.QtGui import QAction
from qfluentwidgets import (ScrollArea, PushButton, FluentIcon, LineEdit,
                            ComboBox, MessageBox, InfoBar, InfoBarPosition,
                            ProgressBar, isDarkTheme)
from pathlib import Path
import sys
import json

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from ..common.project_scanner import ProjectScanner
from ..common.worker import TaskWorker
from ..common.signal_bus import signal_bus
from ..common.config_manager import config_manager
from ..components.flow_layout import FlowLayout
from config import OUTPUT_DIR
from modules.project_charter import (
    draft_project_charter_with_ai,
    load_project_charter,
    normalize_project_charter,
    save_project_charter,
    validate_project_charter,
)
from modules.spec_review import (
    approve_spec_review,
    get_spec_review_status,
    save_spec_review_artifacts,
)


class ProjectInterface(ScrollArea):
    """项目管理界面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.setObjectName("project界面")
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.scanner = ProjectScanner(OUTPUT_DIR)
        self.current_worker = None
        self.running_workers = {}  # project_name -> TaskWorker
        self.worker_progress = {}   # project_name -> progress(0-100)

        # 待处理项目列表（尚未在磁盘上创建的项目）
        self.pending_projects = []
        # 批量任务队列
        self.batch_queue = []
        self.batch_task_type = None
        self.batch_total = 0
        self.batch_completed = 0
        self.batch_failed = 0
        self.batch_running_projects = set()
        self.batch_max_parallel = int(config_manager.get("batch_max_parallel", 2) or 2)

        self.init_ui()
        self.connect_signals()
        self.refresh_projects()

    @staticmethod
    def _auto_confirm_spec_enabled() -> bool:
        """
        默认开启自动规格确认，避免 full_pipeline 在 spec 后人工阻断。
        可通过 gui_config.json 的 auto_confirm_spec_review 关闭。
        """
        return bool(config_manager.get("auto_confirm_spec_review", True))
    
    def init_ui(self):
        """初始化UI"""
        # 第一行：搜索和筛选
        search_layout = QHBoxLayout()
        search_layout.setSpacing(10)

        # 搜索框
        self.search_box = LineEdit(self.view)
        self.search_box.setPlaceholderText("搜索项目...")
        self.search_box.setFixedWidth(250)
        self.search_box.textChanged.connect(self.on_search)

        # 状态筛选
        self.status_filter = ComboBox(self.view)
        self.status_filter.addItems(["全部", "已完成", "进行中", "未开始"])
        self.status_filter.setFixedWidth(120)
        self.status_filter.currentTextChanged.connect(self.refresh_projects)

        search_layout.addWidget(self.search_box)
        search_layout.addWidget(self.status_filter)
        search_layout.addStretch(1)

        # 第二行：操作按钮 - 使用FlowLayout自动换行
        button_container = QWidget(self.view)
        toolbar = FlowLayout(button_container, margin=0, spacing=8)

        # 操作按钮
        new_btn = PushButton(FluentIcon.ADD, "新建项目", button_container)
        new_btn.clicked.connect(self.on_new_project)

        select_all_btn = PushButton(FluentIcon.CHECKBOX, "全选", button_container)
        select_all_btn.clicked.connect(self.on_select_all)

        refresh_btn = PushButton(FluentIcon.SYNC, "刷新", button_container)
        refresh_btn.clicked.connect(self.refresh_projects)

        batch_plan_btn = PushButton(FluentIcon.DOCUMENT, "批量规划", button_container)
        batch_plan_btn.clicked.connect(lambda: self.on_batch_task("plan"))

        batch_html_btn = PushButton(FluentIcon.CODE, "批量HTML", button_container)
        batch_html_btn.clicked.connect(lambda: self.on_batch_task("html"))

        batch_code_btn = PushButton(FluentIcon.DEVELOPER_TOOLS, "批量代码", button_container)
        batch_code_btn.clicked.connect(lambda: self.on_batch_task("code"))

        batch_full_btn = PushButton(FluentIcon.PLAY, "批量完整流程", button_container)
        batch_full_btn.clicked.connect(lambda: self.on_batch_task("full_pipeline"))

        add_to_queue_btn = PushButton(FluentIcon.SEND, "添加到提交队列", button_container)
        add_to_queue_btn.clicked.connect(self.on_add_to_submit_queue)

        # 批量并行度
        self.parallel_combo = ComboBox(button_container)
        self.parallel_combo.addItems(["1", "2", "3", "4"])
        self.parallel_combo.setFixedWidth(90)
        self.parallel_combo.setToolTip("批量任务并行度")
        if str(self.batch_max_parallel) in ["1", "2", "3", "4"]:
            self.parallel_combo.setCurrentText(str(self.batch_max_parallel))
        else:
            self.parallel_combo.setCurrentText("2")
            self.batch_max_parallel = 2
        self.parallel_combo.currentTextChanged.connect(self.on_parallel_changed)

        toolbar.addWidget(new_btn)
        toolbar.addWidget(select_all_btn)
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(batch_plan_btn)
        toolbar.addWidget(batch_html_btn)
        toolbar.addWidget(batch_code_btn)
        toolbar.addWidget(batch_full_btn)
        toolbar.addWidget(self.parallel_combo)
        toolbar.addWidget(add_to_queue_btn)
        
        # 进度条
        self.progress_bar = ProgressBar(self.view)
        self.progress_bar.setVisible(False)
        
        # 表格 - 增加进度列
        self.table = QTableWidget(self.view)
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "项目名称", "创建时间", "规划", "HTML", "截图", "代码", "文档", "PDF", "进度", "操作"
        ])


        # 设置表格样式
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 10):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        
        # 启用多选
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)  # 允许多选
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        # 布局
        self.vBoxLayout.setSpacing(15)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.addLayout(search_layout)
        self.vBoxLayout.addWidget(button_container)
        self.vBoxLayout.addWidget(self.progress_bar)
        self.vBoxLayout.addWidget(self.table)
    
    def connect_signals(self):
        """连接信号"""
        signal_bus.projects_refresh.connect(self.refresh_projects)
        signal_bus.project_created.connect(lambda: self.refresh_projects())
        signal_bus.project_updated.connect(lambda: self.refresh_projects())
        signal_bus.task_completed.connect(self.on_task_completed)
    
    def refresh_projects(self):
        """刷新项目列表"""
        # 扫描磁盘上的项目
        disk_projects = self.scanner.scan_all_projects()

        # 创建pending项目的虚拟数据
        from datetime import datetime
        pending_data = []
        for name in self.pending_projects:
            # 检查是否已经在磁盘上(已处理过)
            if any(p['name'] == name for p in disk_projects):
                continue

            # 创建虚拟项目数据
            pending_data.append({
                'name': name,
                'created_time_str': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'status': {
                    'plan': False,
                    'html': False,
                    'screenshot': False,
                    'code': False,
                    'document': False,
                    'pdf': False
                }
            })

        # 合并: pending项目在前
        projects = pending_data + disk_projects

        # 应用筛选
        filter_text = self.status_filter.currentText()
        if filter_text == "已完成":
            projects = [p for p in projects if all(p['status'].values())]
        elif filter_text == "进行中":
            projects = [p for p in projects if any(p['status'].values()) and not all(p['status'].values())]
        elif filter_text == "未开始":
            projects = [p for p in projects if not any(p['status'].values())]
        
        # 填充表格
        self.table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            # 项目名称
            name_item = QTableWidgetItem(project['name'])
            self.table.setItem(row, 0, name_item)
            
            # 创建时间
            time_item = QTableWidgetItem(project['created_time_str'])
            self.table.setItem(row, 1, time_item)
            
            # 状态列（使用✅/❌）- 增加代码列
            statuses = project['status']
            for col, key in enumerate(['plan', 'html', 'screenshot', 'code', 'document', 'pdf'], start=2):
                status_text = "✅" if statuses.get(key, False) else "❌"
                status_item = QTableWidgetItem(status_text)
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, status_item)

            # 进度列 - 显示进度条或状态文本
            progress_widget = self._create_progress_widget(project['name'])
            self.table.setCellWidget(row, 8, progress_widget)

            # 操作按钮（创建按钮组件）
            actions_widget = self._create_action_buttons(row, project['name'])
            self.table.setCellWidget(row, 9, actions_widget)

    def _create_progress_widget(self, project_name: str):
        """创建进度显示组件"""
        from qfluentwidgets import BodyLabel

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # 检查是否有正在运行或排队中的任务
        if project_name in self.running_workers:
            progress_val = self.worker_progress.get(project_name, 0)
            status_label = BodyLabel(f"处理中 {progress_val}%", widget)
            layout.addWidget(status_label)
        elif self.batch_task_type and project_name in self.batch_queue:
            status_label = BodyLabel("排队中", widget)
            layout.addWidget(status_label)
        else:
            # 显示空闲状态
            status_label = BodyLabel("就绪", widget)
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(status_label)

        layout.addStretch(1)
        return widget

    def _create_action_buttons(self, row: int, project_name: str):
        """创建操作按钮组件"""
        from qfluentwidgets import TransparentToolButton

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 打开目录按钮
        open_btn = TransparentToolButton(FluentIcon.FOLDER, widget)
        open_btn.setToolTip("打开项目目录")
        open_btn.clicked.connect(lambda: self.open_project_dir(project_name))

        # 删除按钮
        delete_btn = TransparentToolButton(FluentIcon.DELETE, widget)
        delete_btn.setToolTip("删除项目")
        delete_btn.clicked.connect(lambda: self.delete_project(project_name))

        layout.addWidget(open_btn)
        layout.addWidget(delete_btn)
        layout.addStretch(1)

        return widget

    def on_search(self, text: str):
        """搜索过滤"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                match = text.lower()in item.text().lower()
                self.table.setRowHidden(row, not match)
    
    def on_new_project(self):
        """新建项目（支持批量）"""
        text, ok = QInputDialog.getMultiLineText(
            self,
            "新建项目",
            "请输入项目名称（每行一个）："
        )

        if ok and text:
            # 按行分割并去除空白
            projects = [line.strip() for line in text.split('\n') if line.strip()]
            if not projects:
                return

            charter = self._prompt_project_charter(projects[0])
            if not charter:
                InfoBar.warning(
                    title="章程未完成",
                    content="项目章程是必填项，已取消本次创建。",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                return

            count = 0
            for project_name in projects:
                # 检查是否已存在（简单检查表格中是否已有）
                # 实际上 add_pending_project 只是UI添加，真正的创建是在生成规划时
                # 但为了用户体验，我们添加到列表顶部
                project_dir = OUTPUT_DIR / project_name
                project_charter = dict(charter)
                project_charter["project_name"] = project_name
                save_project_charter(project_dir, project_charter)
                self.add_pending_project(project_name)
                count += 1

            if count > 0:
                InfoBar.success(
                    title="已添加项目",
                    content=f"成功添加 {count} 个待处理项目",
                    parent=self,
                    position=InfoBarPosition.TOP
                )

    def _prompt_project_charter(self, sample_project_name: str):
        """
        AI 自动草拟章程 + 人工确认（可快速编辑 JSON）。
        """
        InfoBar.info(
            title="章程草拟中",
            content=f"正在使用 AI 为“{sample_project_name}”生成章程草案...",
            parent=self,
            position=InfoBarPosition.TOP
        )

        try:
            draft = draft_project_charter_with_ai(sample_project_name)
        except Exception as e:
            InfoBar.warning(
                title="AI草拟失败",
                content=f"将使用模板草案继续确认：{e}",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return None

        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        while True:
            edited_text, ok = QInputDialog.getMultiLineText(
                self,
                "确认项目章程（可直接修改 JSON）",
                "请快速检查并确认章程，点击确定后将保存：",
                text=draft_text,
            )
            if not ok:
                return None

            try:
                edited_raw = json.loads(edited_text)
            except Exception as e:
                InfoBar.error(
                    title="章程格式错误",
                    content=f"JSON 解析失败：{e}",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                draft_text = edited_text
                continue

            charter = normalize_project_charter(edited_raw, project_name=sample_project_name)
            errors = validate_project_charter(charter)
            if errors:
                InfoBar.error(
                    title="章程校验失败",
                    content="；".join(errors),
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                draft_text = json.dumps(charter, ensure_ascii=False, indent=2)
                continue
            return charter

    def _ensure_project_charter_ready(self, project_name: str, interactive: bool = True):
        """
        确保项目章程存在且有效。可选地进行 AI 草拟并人工确认。
        """
        project_dir = OUTPUT_DIR / project_name
        current = normalize_project_charter(load_project_charter(project_dir) or {}, project_name=project_name)
        errors = validate_project_charter(current)
        if not errors:
            save_project_charter(project_dir, current)
            return current

        if not interactive:
            return None

        charter = self._prompt_project_charter(project_name)
        if not charter:
            return None
        save_project_charter(project_dir, charter)
        return charter

    def _ensure_spec_review_ready(self, project_name: str, interactive: bool = True) -> bool:
        """
        确保可执行规格已确认。
        """
        project_dir = OUTPUT_DIR / project_name
        spec_path = project_dir / "project_executable_spec.json"
        if not spec_path.exists():
            return True

        # 刷新评审产物；当规格发生变化时自动回到 pending
        save_spec_review_artifacts(project_dir, project_name)
        status = get_spec_review_status(project_dir, spec_path)
        if status.get("approved"):
            return True

        if self._auto_confirm_spec_enabled():
            result = approve_spec_review(project_dir, reviewer="qt-auto")
            if result.get("ok"):
                return True

        if not interactive:
            return False

        guide_path = Path(status.get("guide_path") or (project_dir / "spec_review_guide.md"))
        preview = ""
        if guide_path.exists():
            try:
                with open(guide_path, "r", encoding="utf-8") as f:
                    preview = "\n".join(f.read().splitlines()[:14])
            except Exception:
                preview = ""

        message = (
            "检测到未确认规格。\n"
            f"规格哈希: {status.get('spec_digest', '')[:12]}...\n"
            f"评审清单: {guide_path}\n\n"
            "是否确认该规格并继续？"
        )
        if preview:
            message += "\n\n--- 评审摘要预览 ---\n" + preview

        box = MessageBox("确认可执行规格", message, self)
        try:
            box.yesButton.setText("确认并继续")
            box.cancelButton.setText("稍后")
        except Exception:
            pass
        if not box.exec():
            return False

        result = approve_spec_review(project_dir, reviewer="qt-user")
        if not result.get("ok"):
            InfoBar.error(
                title="规格确认失败",
                content=str(result.get("message") or "未知错误"),
                parent=self,
                position=InfoBarPosition.TOP
            )
            return False
        return True

    def add_pending_project(self, project_name: str):
        """添加待处理项目到列表"""
        # 检查是否重复
        if project_name in self.pending_projects:
            return

        # 保存到pending列表
        self.pending_projects.append(project_name)

        # 在表格顶部插入新行
        self.table.insertRow(0)

        # 项目名称
        name_item = QTableWidgetItem(project_name)
        self.table.setItem(0, 0, name_item)

        # 创建时间
        from datetime import datetime
        time_item = QTableWidgetItem(datetime.now().strftime('%Y-%m-%d %H:%M'))
        self.table.setItem(0, 1, time_item)

        # 状态列（全部设为❌）
        for col in range(2, 8):
            status_item = QTableWidgetItem("❌")
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(0, col, status_item)

        # 进度列
        progress_widget = self._create_progress_widget(project_name)
        self.table.setCellWidget(0, 8, progress_widget)

        # 操作按钮
        actions_widget = self._create_action_buttons(0, project_name)
        self.table.setCellWidget(0, 9, actions_widget)
    
    
    def on_select_all(self):
        """全选/取消全选"""
        if self.table.selectedItems():
            self.table.clearSelection()
        else:
            self.table.selectAll()

    def on_parallel_changed(self, text: str):
        """更新批量并行度配置"""
        try:
            value = max(1, min(4, int(text)))
        except Exception:
            value = 2
        self.batch_max_parallel = value
        config_manager.set("batch_max_parallel", value)
    
    def get_selected_projects(self):
        """获取选中的项目列表"""
        selected_rows = set(item.row() for item in self.table.selectedItems())
        projects = []
        for row in selected_rows:
            name_item = self.table.item(row, 0)
            if name_item:
                projects.append(name_item.text())
        return projects
    
    def on_batch_task(self, task_type: str):
        """批量任务"""
        selected = self.get_selected_projects()

        if not selected:
            InfoBar.warning(
                title="未选择项目",
                content="请先选择要操作的项目（可按Ctrl/Shift多选）",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        if self.running_workers:
            InfoBar.warning(
                title="任务运行中",
                content="当前有任务正在执行，请稍后再启动新的批量任务",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        charter_required_tasks = {"plan", "spec", "code", "verify", "document", "pdf", "freeze", "full_pipeline", "resume_pipeline"}
        spec_required_tasks = {"code", "verify", "document", "pdf", "freeze", "resume_pipeline"}
        valid_selected = list(selected)
        skipped_charter = []
        skipped_spec = []

        if task_type in charter_required_tasks:
            keep = []
            for project_name in valid_selected:
                if self._ensure_project_charter_ready(project_name, interactive=False):
                    keep.append(project_name)
                else:
                    skipped_charter.append(project_name)
            valid_selected = keep

        if task_type in spec_required_tasks:
            keep = []
            for project_name in valid_selected:
                if self._ensure_spec_review_ready(project_name, interactive=False):
                    keep.append(project_name)
                else:
                    skipped_spec.append(project_name)
            valid_selected = keep

        if not valid_selected:
            reason = []
            if skipped_charter:
                reason.append(f"章程不合格 {len(skipped_charter)}")
            if skipped_spec:
                reason.append(f"规格未确认 {len(skipped_spec)}")
            InfoBar.warning(
                title="批量任务未启动",
                content="；".join(reason) if reason else "无可执行项目",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        result = MessageBox(
            "批量操作确认",
            f"确定对 {len(valid_selected)} 个项目执行 {task_type} 操作吗？\n\n项目：{', '.join(valid_selected[:3])}{'...' if len(valid_selected) > 3 else ''}",
            self
        ).exec()

        if not result:
            return

        # 初始化批量队列
        self.batch_queue = list(valid_selected)
        self.batch_task_type = task_type
        self.batch_total = len(valid_selected)
        self.batch_completed = 0
        self.batch_failed = 0
        self.batch_running_projects = set()

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # 并行启动首批任务
        self._process_next_batch_task()

        InfoBar.success(
            title="批量任务已启动",
            content=f"共 {len(valid_selected)} 个项目，并行度: {self.batch_max_parallel}",
            parent=self,
            position=InfoBarPosition.TOP
        )
        if skipped_charter or skipped_spec:
            msg_parts = []
            if skipped_charter:
                msg_parts.append(f"跳过章程不合格 {len(skipped_charter)} 个")
            if skipped_spec:
                msg_parts.append(f"跳过规格未确认 {len(skipped_spec)} 个")
            InfoBar.warning(
                title="部分项目已跳过",
                content="；".join(msg_parts),
                parent=self,
                position=InfoBarPosition.TOP
            )
    
    def on_add_to_submit_queue(self):
        """添加到提交队列"""
        selected = self.get_selected_projects()

        if not selected:
            InfoBar.warning(
                title="未选择项目",
                content="请先选择要提交的项目",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return

        # 发送信号到提交界面
        for project_name in selected:
            signal_bus.submit_started.emit(project_name)

        InfoBar.success(
            title="已添加到提交队列",
            content=f"{len(selected)} 个项目已添加，请前往'自动提交'页面查看",
            parent=self,
            position=InfoBarPosition.TOP
        )

    def _process_next_batch_task(self):
        """按并行度持续调度批量任务"""
        if not self.batch_task_type:
            return

        # 启动新任务直到达到并行上限
        while self.batch_queue and len(self.batch_running_projects) < self.batch_max_parallel:
            project_name = self.batch_queue.pop(0)
            self.run_task(self.batch_task_type, project_name, is_batch=True)

        # 所有任务完成
        if not self.batch_queue and not self.batch_running_projects:
            finished = self.batch_completed + self.batch_failed
            self.batch_task_type = None
            self.batch_queue = []
            self.batch_running_projects = set()
            self.progress_bar.setVisible(False)
            self.refresh_projects()

            if self.batch_failed == 0:
                InfoBar.success(
                    title="批量任务完成",
                    content=f"成功 {finished}/{self.batch_total}",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
            else:
                InfoBar.warning(
                    title="批量任务结束",
                    content=f"成功 {self.batch_completed}/{self.batch_total}，失败 {self.batch_failed}",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
            self.batch_total = 0
            self.batch_completed = 0
            self.batch_failed = 0

    def show_context_menu(self, pos):
        """显示右键菜单"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        project_name = self.table.item(row, 0).text()

        menu = QMenu(self)

        # 基础操作
        open_action = QAction(FluentIcon.FOLDER.icon(), "打开目录", self)
        open_action.triggered.connect(lambda: self.open_project_dir(project_name))

        # 单步执行菜单
        step_menu = menu.addMenu("单步执行")

        plan_action = QAction(FluentIcon.DOCUMENT.icon(), "生成规划", self)
        plan_action.triggered.connect(lambda: self.run_task("plan", project_name))

        spec_action = QAction(FluentIcon.DOCUMENT.icon(), "生成规格", self)
        spec_action.triggered.connect(lambda: self.run_task("spec", project_name))

        html_action = QAction(FluentIcon.CODE.icon(), "生成HTML", self)
        html_action.triggered.connect(lambda: self.run_task("html", project_name))

        screenshot_action = QAction(FluentIcon.CAMERA.icon(), "生成截图", self)
        screenshot_action.triggered.connect(lambda: self.run_task("screenshot", project_name))

        code_action = QAction(FluentIcon.DEVELOPER_TOOLS.icon(), "生成代码", self)
        code_action.triggered.connect(lambda: self.run_task("code", project_name))

        verify_action = QAction(FluentIcon.CHECKBOX.icon(), "运行验证", self)
        verify_action.triggered.connect(lambda: self.run_task("verify", project_name))

        doc_action = QAction(FluentIcon.BOOK_SHELF.icon(), "生成文档", self)
        doc_action.triggered.connect(lambda: self.run_task("document", project_name))

        pdf_action = QAction(FluentIcon.DOCUMENT.icon(), "生成源码PDF", self)
        pdf_action.triggered.connect(lambda: self.run_task("pdf", project_name))

        freeze_action = QAction(FluentIcon.FOLDER.icon(), "生成冻结包", self)
        freeze_action.triggered.connect(lambda: self.run_task("freeze", project_name))

        step_menu.addAction(plan_action)
        step_menu.addAction(spec_action)
        step_menu.addAction(html_action)
        step_menu.addAction(screenshot_action)
        step_menu.addAction(code_action)
        step_menu.addAction(verify_action)
        step_menu.addAction(doc_action)
        step_menu.addAction(pdf_action)
        step_menu.addAction(freeze_action)

        # 完整流程
        rerun_action = QAction(FluentIcon.SYNC.icon(), "完整重跑", self)
        rerun_action.triggered.connect(lambda: self.run_task("full_pipeline", project_name))

        # 从断点继续
        resume_action = QAction(FluentIcon.PLAY.icon(), "从当前状态继续", self)
        resume_action.triggered.connect(lambda: self.run_task("resume_pipeline", project_name))

        approve_spec_action = QAction(FluentIcon.CHECKBOX.icon(), "确认规格", self)
        approve_spec_action.triggered.connect(lambda: self._confirm_spec(project_name))

        # 删除
        delete_action = QAction(FluentIcon.DELETE.icon(), "删除项目", self)
        delete_action.triggered.connect(lambda: self.delete_project(project_name))

        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(rerun_action)
        menu.addAction(resume_action)
        menu.addAction(approve_spec_action)
        menu.addSeparator()
        menu.addAction(delete_action)

        menu.exec(self.table.viewport().mapToGlobal(pos))
    
    def open_project_dir(self, project_name: str):
        """打开项目目录"""
        import os
        project_path = OUTPUT_DIR / project_name
        if project_path.exists():
            os.startfile(str(project_path))
    
    def delete_project(self, project_name: str):
        """删除项目"""
        result = MessageBox (
            "确认删除",
            f"确定要删除项目 '{project_name}' 吗？\n此操作不可撤销！",
            self
        ).exec()
        
        if result:
            import shutil
            project_path = OUTPUT_DIR / project_name
            try:
                shutil.rmtree(project_path)
                InfoBar.success(
                    title="删除成功",
                    content=f"项目 '{project_name}' 已删除",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                self.refresh_projects()
            except Exception as e:
                InfoBar.error(
                    title="删除失败",
                    content=str(e),
                    parent=self,
                    position=InfoBarPosition.TOP
                )
    
    def _confirm_spec(self, project_name: str):
        """手动确认项目规格"""
        if self._ensure_spec_review_ready(project_name, interactive=True):
            InfoBar.success(
                title="规格已确认",
                content=f"{project_name} 的规格已确认，可继续执行后续阶段",
                parent=self,
                position=InfoBarPosition.TOP
            )

    def run_task(self, task_type: str, project_name: str, is_batch: bool = False):
        """运行任务"""
        if not is_batch and self.running_workers:
            InfoBar.warning(
                title="任务运行中",
                content="请等待当前任务完成",
                parent=self,
                position=InfoBarPosition.TOP
            )
            return False

        if project_name in self.running_workers:
            return False

        charter_required_tasks = {"plan", "spec", "code", "verify", "document", "pdf", "freeze", "full_pipeline", "resume_pipeline"}
        project_charter = None
        if not is_batch and task_type in charter_required_tasks:
            project_charter = self._ensure_project_charter_ready(project_name, interactive=True)
            if not project_charter:
                InfoBar.warning(
                    title="章程未确认",
                    content="已取消任务启动。请确认章程后重试。",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                return False

        spec_required_tasks = {"code", "verify", "document", "pdf", "freeze", "resume_pipeline"}
        if not is_batch and task_type in spec_required_tasks:
            if not self._ensure_spec_review_ready(project_name, interactive=True):
                InfoBar.warning(
                    title="规格未确认",
                    content="已取消任务启动。请确认规格后重试。",
                    parent=self,
                    position=InfoBarPosition.TOP
                )
                return False

        worker_kwargs = {}
        if project_charter:
            worker_kwargs["project_charter"] = project_charter
        if not is_batch and task_type == "full_pipeline":
            worker_kwargs["require_spec_confirmation"] = True
            worker_kwargs["auto_approve_spec"] = self._auto_confirm_spec_enabled()
        if not is_batch and task_type in {"resume_pipeline", "code", "verify", "document", "pdf", "freeze"}:
            worker_kwargs["auto_approve_spec"] = self._auto_confirm_spec_enabled()
        worker = TaskWorker(task_type, project_name, **worker_kwargs)
        self.running_workers[project_name] = worker
        self.worker_progress[project_name] = 0

        if is_batch:
            self.batch_running_projects.add(project_name)
        else:
            self.current_worker = worker
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)

        # 连接信号
        worker.progress.connect(lambda v, pn=project_name: self.on_task_progress(v, pn))
        worker.log.connect(lambda msg, pn=project_name: self.on_task_log(msg, pn))
        worker.finished.connect(
            lambda success, message, pn=project_name, batch=is_batch:
            self.on_task_finished(success, message, pn, batch)
        )

        worker.start()

        if not is_batch:
            InfoBar.info(
                title="任务已启动",
                content=f"正在执行 {task_type} for {project_name}",
                parent=self,
                position=InfoBarPosition.TOP
            )
        return True

    def on_task_progress(self, value: int, project_name: str = ""):
        """任务进度更新"""
        if project_name:
            self.worker_progress[project_name] = value

        # 单任务进度
        if self.current_worker and project_name == self.current_worker.project_name and not self.batch_task_type:
            self.progress_bar.setValue(value)

        # 批量聚合进度
        if self.batch_task_type and self.batch_total > 0:
            running_progress = sum(self.worker_progress.get(p, 0) for p in self.batch_running_projects)
            progress_units = self.batch_completed + self.batch_failed + (running_progress / 100.0)
            percent = int(min(100, max(0, (progress_units / self.batch_total) * 100)))
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(percent)

    def on_task_log(self, message: str, project_name: str = ""):
        """任务日志"""
        prefix = f"[{project_name}] " if project_name else ""
        print(f"[TASK LOG] {prefix}{message}")

    def on_task_finished(self, success: bool, message: str, project_name: str = "", is_batch: bool = False):
        """任务完成"""
        self.running_workers.pop(project_name, None)
        self.worker_progress.pop(project_name, None)
        self.batch_running_projects.discard(project_name)

        if success:
            if is_batch:
                self.batch_completed += 1
            else:
                self.progress_bar.setVisible(False)
                InfoBar.success(
                    title="任务完成",
                    content=message,
                    parent=self,
                    position=InfoBarPosition.TOP
                )
        else:
            if is_batch:
                self.batch_failed += 1
            else:
                self.progress_bar.setVisible(False)
                InfoBar.error(
                    title="任务失败",
                    content=message,
                    parent=self,
                    position=InfoBarPosition.TOP
                )

        # 刷新列表
        QTimer.singleShot(300, self.refresh_projects)

        # 批量模式：继续调度
        if is_batch and self.batch_task_type:
            self.on_task_progress(0)  # 刷新聚合进度
            QTimer.singleShot(200, self._process_next_batch_task)
        elif not self.running_workers:
            self.current_worker = None
    
    def on_task_completed(self, task_id: str, success: bool, message: str):
        """处理全局任务完成信号"""
        self.refresh_projects()
