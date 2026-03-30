"""
LLM 监控界面
展示调用次数、Tokens 消耗、Provider 维度与最近运行记录。
"""
from datetime import datetime
from pathlib import Path
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from qfluentwidgets import (
    ScrollArea,
    BodyLabel,
    CaptionLabel,
    PushButton,
    CardWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
)

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.llm_budget import llm_budget


class MetricCard(CardWidget):
    """轻量指标卡片"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(100)
        self.setMinimumWidth(160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        self.title_label = CaptionLabel(title, self)
        self.value_label = BodyLabel("0", self)
        value_font = self.value_label.font()
        value_font.setPointSize(16)
        value_font.setBold(True)
        self.value_label.setFont(value_font)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addStretch(1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(str(value))


class LlmMonitorInterface(ScrollArea):
    """LLM 监控页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.setObjectName("llmMonitorInterface")
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.max_runs = 30
        self._last_error_message = ""

        self._init_ui()
        self._init_timer()
        self.refresh_snapshot()

    def _init_ui(self):
        title_label = BodyLabel("LLM 监控", self.view)
        title_font = title_label.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_label.setFont(title_font)

        subtitle_label = CaptionLabel("调用次数、输入/输出 Tokens、Provider/阶段消耗、最近运行记录", self.view)

        toolbar = QHBoxLayout()
        self.updated_at_label = CaptionLabel("更新时间: --", self.view)
        refresh_btn = PushButton(FluentIcon.SYNC, "刷新", self.view)
        refresh_btn.clicked.connect(self.refresh_snapshot)
        toolbar.addWidget(self.updated_at_label)
        toolbar.addStretch(1)
        toolbar.addWidget(refresh_btn)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        self.calls_card = MetricCard("总调用", self.view)
        self.failures_card = MetricCard("总失败", self.view)
        self.input_tokens_card = MetricCard("输入 Tokens", self.view)
        self.output_tokens_card = MetricCard("输出 Tokens", self.view)
        self.total_tokens_card = MetricCard("总 Tokens", self.view)
        self.active_runs_card = MetricCard("活跃 Run", self.view)
        for card in [
            self.calls_card,
            self.failures_card,
            self.input_tokens_card,
            self.output_tokens_card,
            self.total_tokens_card,
            self.active_runs_card,
        ]:
            summary_row.addWidget(card)
        summary_row.addStretch(1)

        provider_title = BodyLabel("按 Provider 消耗", self.view)
        provider_font = provider_title.font()
        provider_font.setPointSize(14)
        provider_font.setBold(True)
        provider_title.setFont(provider_font)

        self.provider_table = QTableWidget(self.view)
        self.provider_table.setColumnCount(8)
        self.provider_table.setHorizontalHeaderLabels(
            ["Provider", "调用", "失败", "输入Tokens", "输出Tokens", "总Tokens", "模型分布", "协议分布"]
        )
        self._setup_table(self.provider_table, stretch_col=6)
        self.provider_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)

        stage_title = BodyLabel("按阶段消耗", self.view)
        stage_font = stage_title.font()
        stage_font.setPointSize(14)
        stage_font.setBold(True)
        stage_title.setFont(stage_font)

        self.stage_table = QTableWidget(self.view)
        self.stage_table.setColumnCount(6)
        self.stage_table.setHorizontalHeaderLabels(
            ["阶段", "调用", "失败", "输入Tokens", "输出Tokens", "总Tokens"]
        )
        self._setup_table(self.stage_table, stretch_col=0)

        runs_title = BodyLabel("最近运行", self.view)
        runs_font = runs_title.font()
        runs_font.setPointSize(14)
        runs_font.setBold(True)
        runs_title.setFont(runs_font)

        self.runs_table = QTableWidget(self.view)
        self.runs_table.setColumnCount(8)
        self.runs_table.setHorizontalHeaderLabels(
            ["Run ID", "开始时间", "调用", "失败", "输入Tokens", "输出Tokens", "总Tokens", "Top Provider"]
        )
        self._setup_table(self.runs_table, stretch_col=0)
        self.runs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.vBoxLayout.setSpacing(14)
        self.vBoxLayout.setContentsMargins(30, 24, 30, 24)
        self.vBoxLayout.addWidget(title_label)
        self.vBoxLayout.addWidget(subtitle_label)
        self.vBoxLayout.addLayout(toolbar)
        self.vBoxLayout.addLayout(summary_row)
        self.vBoxLayout.addSpacing(6)
        self.vBoxLayout.addWidget(provider_title)
        self.vBoxLayout.addWidget(self.provider_table)
        self.vBoxLayout.addWidget(stage_title)
        self.vBoxLayout.addWidget(self.stage_table)
        self.vBoxLayout.addWidget(runs_title)
        self.vBoxLayout.addWidget(self.runs_table)

    @staticmethod
    def _setup_table(table: QTableWidget, stretch_col: int = 0):
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
        for i in range(table.columnCount()):
            if i == stretch_col:
                continue
            table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

    def _init_timer(self):
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(3000)
        self._refresh_timer.timeout.connect(lambda: self.refresh_snapshot(silent=True))
        self._refresh_timer.start()

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def _format_models(data: dict) -> str:
        if not isinstance(data, dict) or not data:
            return "-"
        rows = sorted(data.items(), key=lambda x: int(x[1]), reverse=True)
        return ", ".join([f"{k}:{v}" for k, v in rows[:4]])

    @staticmethod
    def _format_time(ts) -> str:
        try:
            return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "--"

    @staticmethod
    def _top_provider(run: dict) -> str:
        provider_tokens = run.get("provider_total_tokens") or {}
        if not isinstance(provider_tokens, dict) or not provider_tokens:
            return "-"
        provider, value = max(provider_tokens.items(), key=lambda x: int(x[1]))
        return f"{provider}({value})"

    def refresh_snapshot(self, silent: bool = False):
        try:
            snapshot = llm_budget.get_runtime_snapshot(max_runs=self.max_runs)
        except Exception as e:
            message = f"LLM统计读取失败: {e}"
            if (not silent) and message != self._last_error_message:
                InfoBar.error(
                    title="刷新失败",
                    content=message,
                    parent=self,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=3000,
                )
            self._last_error_message = message
            return

        self._last_error_message = ""
        summary = snapshot.get("summary") or {}
        self.calls_card.set_value(
            f"{self._to_int(summary.get('total_calls'))} / {self._to_int((snapshot.get('config') or {}).get('total_calls'))}"
        )
        self.failures_card.set_value(str(self._to_int(summary.get("total_failures"))))
        self.input_tokens_card.set_value(str(self._to_int(summary.get("input_tokens"))))
        self.output_tokens_card.set_value(str(self._to_int(summary.get("output_tokens"))))
        self.total_tokens_card.set_value(str(self._to_int(summary.get("total_tokens"))))
        self.active_runs_card.set_value(str(self._to_int(summary.get("active_runs"))))

        self._fill_provider_table(snapshot.get("provider_summary") or {})
        self._fill_stage_table(summary)
        self._fill_runs_table(snapshot.get("runs") or [])

        self.updated_at_label.setText(
            f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _fill_provider_table(self, provider_summary: dict):
        rows = []
        for provider, value in provider_summary.items():
            value = value or {}
            rows.append(
                (
                    str(provider),
                    self._to_int(value.get("calls")),
                    self._to_int(value.get("failures")),
                    self._to_int(value.get("input_tokens")),
                    self._to_int(value.get("output_tokens")),
                    self._to_int(value.get("total_tokens")),
                    self._format_models(value.get("models") or {}),
                    self._format_models(value.get("api_styles") or {}),
                )
            )
        rows.sort(key=lambda x: (x[5], x[1]), reverse=True)

        self.provider_table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, cell in enumerate(row_data):
                item = QTableWidgetItem(str(cell))
                if col_idx in (1, 2, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.provider_table.setItem(row_idx, col_idx, item)

    def _fill_stage_table(self, summary: dict):
        stage_calls = summary.get("stage_calls") or {}
        stage_failures = summary.get("stage_failures") or {}
        stage_input = summary.get("stage_input_tokens") or {}
        stage_output = summary.get("stage_output_tokens") or {}
        stage_total = summary.get("stage_total_tokens") or {}

        stage_names = set(stage_calls.keys()) | set(stage_failures.keys()) | set(stage_input.keys()) | set(stage_output.keys()) | set(stage_total.keys())
        rows = []
        for stage in stage_names:
            rows.append(
                (
                    str(stage),
                    self._to_int(stage_calls.get(stage)),
                    self._to_int(stage_failures.get(stage)),
                    self._to_int(stage_input.get(stage)),
                    self._to_int(stage_output.get(stage)),
                    self._to_int(stage_total.get(stage)),
                )
            )
        rows.sort(key=lambda x: (x[5], x[1]), reverse=True)

        self.stage_table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, cell in enumerate(row_data):
                item = QTableWidgetItem(str(cell))
                if col_idx > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.stage_table.setItem(row_idx, col_idx, item)

    def _fill_runs_table(self, runs: list):
        rows = []
        for run in runs:
            run = run or {}
            rows.append(
                (
                    str(run.get("run_id") or ""),
                    self._format_time(run.get("started_at")),
                    self._to_int(run.get("total_calls")),
                    self._to_int(run.get("total_failures")),
                    self._to_int(run.get("input_tokens")),
                    self._to_int(run.get("output_tokens")),
                    self._to_int(run.get("total_tokens")),
                    self._top_provider(run),
                )
            )

        self.runs_table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, cell in enumerate(row_data):
                item = QTableWidgetItem(str(cell))
                if col_idx in (2, 3, 4, 5, 6):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.runs_table.setItem(row_idx, col_idx, item)
