"""
设置界面
API配置、主题切换、账号管理
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QLabel, QFormLayout)
from qfluentwidgets import (ScrollArea, SettingCardGroup, SwitchSettingCard,
                            PushSettingCard, LineEdit, ComboBox,
                            PrimaryPushButton, FluentIcon, InfoBar,
                            InfoBarPosition)
import json
from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from ..common.signal_bus import signal_bus
from ..common.config_manager import config_manager
from config import (load_api_config, update_provider_config,
                    set_current_provider, get_provider_config)


class SettingInterface(ScrollArea):
    """设置界面"""

    QUALITY_PROFILE_PRESETS = {
        "economy": {
            "novelty_threshold": 0.35,
            "file_novelty_budget": 0.35,
            "project_novelty_threshold": 0.32,
            "rewrite_candidates": 1,
            "max_rewrite_rounds": 1,
            "heavy_search_ratio": 0.20,
            "enable_project_novelty_gate": False,
            "enforce_file_gate": False,
            "enforce_file_gate_on_obfuscation": False,
            "max_risky_files": 8,
            "max_syntax_fail_files": 4,
            "min_ai_line_ratio": 0.10,
            "max_failed_files": 8,
            "max_llm_attempts_per_file": 2,
            "llm_text_retries": 1,
            "max_total_llm_calls": 12,
            "max_total_llm_failures": 4,
            "disable_llm_on_budget_exhausted": True,
            "disable_llm_on_failures": True,
            "enable_embedding_similarity": False,
            "embedding_similarity_weight": 0.15,
            "embedding_max_chars": 2400,
            "llm_provider_override": "",
            "llm_model_override": "",
        },
        "high_constraint": {
            "novelty_threshold": 0.46,
            "file_novelty_budget": 0.46,
            "project_novelty_threshold": 0.42,
            "rewrite_candidates": 2,
            "max_rewrite_rounds": 2,
            "heavy_search_ratio": 0.30,
            "enable_project_novelty_gate": True,
            "enforce_file_gate": True,
            "enforce_file_gate_on_obfuscation": False,
            "max_risky_files": 2,
            "max_syntax_fail_files": 0,
            "min_ai_line_ratio": 0.20,
            "max_failed_files": 0,
            "max_llm_attempts_per_file": 4,
            "llm_text_retries": 2,
            "max_total_llm_calls": 32,
            "max_total_llm_failures": 10,
            "disable_llm_on_budget_exhausted": True,
            "disable_llm_on_failures": True,
            "enable_embedding_similarity": False,
            "embedding_similarity_weight": 0.15,
            "embedding_max_chars": 2400,
            "llm_provider_override": "",
            "llm_model_override": "",
        },
    }
    QUALITY_PROFILE_LABEL_TO_KEY = {
        "低消耗(默认)": "economy",
        "高约束": "high_constraint",
    }
    QUALITY_PROFILE_KEY_TO_LABEL = {
        "economy": "低消耗(默认)",
        "high_constraint": "高约束",
    }
    
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)
        
        self.setObjectName("settingInterface")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        # API设置组
        self.api_group = SettingCardGroup("API 配置", self.view)

        runtime_api_config = load_api_config()
        self.current_provider = runtime_api_config.get("current_provider", "deepseek")
        provider_names = list(runtime_api_config.get("providers", {}).keys())
        if not provider_names:
            provider_names = ["deepseek"]
        self.available_providers = provider_names

        # API Provider 选择卡片
        self.api_provider_card = PushSettingCard(
            "配置",
            FluentIcon.CLOUD,
            "API提供商",
            f"当前: {self.current_provider}",
            self.api_group
        )
        
        # API Provider下拉框
        provider_widget = QWidget()
        provider_layout = QVBoxLayout(provider_widget)
        provider_label = QLabel("选择API提供商:")
        self.provider_combo = ComboBox()
        self.provider_combo.addItems(provider_names)
        if self.current_provider in provider_names:
            self.provider_combo.setCurrentText(self.current_provider)
        else:
            self.current_provider = provider_names[0]
            self.provider_combo.setCurrentText(self.current_provider)
        self.provider_combo.currentTextChanged.connect(self.on_api_provider_changed)
        provider_layout.addWidget(provider_label)
        provider_layout.addWidget(self.provider_combo)
        
        # API详细配置
        self.api_config_widget = QWidget()
        self.api_config_layout = QFormLayout(self.api_config_widget)
        
        self.api_key_edit = LineEdit()
        self.api_key_edit.setPlaceholderText("API Key")
        
        self.base_url_edit = LineEdit()
        self.base_url_edit.setPlaceholderText("Base URL")
        
        self.model_edit = LineEdit()
        self.model_edit.setPlaceholderText("模型名称")

        self.max_tokens_edit = LineEdit()
        self.max_tokens_edit.setPlaceholderText("max_tokens，例如 8192")

        self.temperature_edit = LineEdit()
        self.temperature_edit.setPlaceholderText("temperature，例如 0.7")

        self.transport_combo = ComboBox()
        self.transport_combo.addItems(["auto", "http", "sdk"])

        self.api_style_combo = ComboBox()
        self.api_style_combo.addItems(["chat", "responses", "auto"])

        self.http_retries_edit = LineEdit()
        self.http_retries_edit.setPlaceholderText("HTTP重试次数，例如 4")

        self.retry_cap_edit = LineEdit()
        self.retry_cap_edit.setPlaceholderText("重试降载 max_tokens 上限，例如 4096")

        self.max_inflight_edit = LineEdit()
        self.max_inflight_edit.setPlaceholderText("最大并发请求数，0=自动（推荐）")

        self.min_interval_edit = LineEdit()
        self.min_interval_edit.setPlaceholderText("请求最小间隔秒数，0=自动（推荐）")

        self.use_env_proxy_combo = ComboBox()
        self.use_env_proxy_combo.addItems(["True", "False"])

        self.auto_bypass_proxy_combo = ComboBox()
        self.auto_bypass_proxy_combo.addItems(["False", "True"])

        self.api_config_layout.addRow("API Key:", self.api_key_edit)
        self.api_config_layout.addRow("Base URL:", self.base_url_edit)
        self.api_config_layout.addRow("Model:", self.model_edit)
        self.api_config_layout.addRow("Max Tokens:", self.max_tokens_edit)
        self.api_config_layout.addRow("Temperature:", self.temperature_edit)
        self.api_config_layout.addRow("Transport:", self.transport_combo)
        self.api_config_layout.addRow("API Style:", self.api_style_combo)
        self.api_config_layout.addRow("HTTP Retries:", self.http_retries_edit)
        self.api_config_layout.addRow("Retry Token Cap:", self.retry_cap_edit)
        self.api_config_layout.addRow("Max Inflight:", self.max_inflight_edit)
        self.api_config_layout.addRow("Min Req Interval(s):", self.min_interval_edit)
        self.api_config_layout.addRow("Use Env Proxy:", self.use_env_proxy_combo)
        self.api_config_layout.addRow("Auto Bypass Proxy:", self.auto_bypass_proxy_combo)
        
        # 保存按钮
        save_api_btn = PrimaryPushButton("保存API配置", self.view)
        save_api_btn.clicked.connect(self.save_api_config)
        
        self.api_group.addSettingCard(self.api_provider_card)
        
        # 加载当前API配置
        self.load_api_config(self.current_provider)
        
        # 外观设置组
        self.appearance_group = SettingCardGroup("外观设置", self.view)
        
        current_theme = config_manager.get('theme', 'dark')
        self.theme_card = PushSettingCard(
            "切换",
            FluentIcon.BRUSH,
            "主题",
            f"当前: {'深色' if current_theme == 'dark' else '浅色'}",
            self.appearance_group
        )
        self.theme_card.clicked.connect(self.on_theme_toggle)
        
        self.appearance_group.addSettingCard(self.theme_card)

        # 生成偏好设置组
        self.generation_group = SettingCardGroup("生成偏好", self.view)

        # 目标语言选择
        lang_widget = QWidget()
        lang_layout = QVBoxLayout(lang_widget)
        lang_label = QLabel("目标编程语言:")
        self.lang_combo = ComboBox()
        self.lang_combo.addItems(["Random", "Java", "Python", "Go", "Node.js", "PHP"])
        self.lang_combo.setCurrentText(config_manager.get("target_language", "Random"))
        self.lang_combo.currentTextChanged.connect(lambda t: self.save_preference("target_language", t))
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.lang_combo)

        self.lang_card = PushSettingCard(
            "设置",
            FluentIcon.CODE,
            "编程语言",
            "选择生成的后端代码语言",
            self.generation_group
        )
        # 将自定义 widget 放入卡片下方 (FluentWidgets 的 PushSettingCard 不直接支持 custom widget，
        # 这里的做法是直接把 combo 放在 card group 里，或者仿照 API Provider 的写法)
        # 仿照 API Provider 写法：

        # UI 框架选择
        ui_widget = QWidget()
        ui_layout = QVBoxLayout(ui_widget)
        ui_label = QLabel("前端 UI 框架:")
        self.ui_combo = ComboBox()
        self.ui_combo.addItems(["Random", "Vue", "React", "Angular", "HTML+Bootstrap", "Layui"])
        self.ui_combo.setCurrentText(config_manager.get("ui_framework", "Random"))
        self.ui_combo.currentTextChanged.connect(lambda t: self.save_preference("ui_framework", t))
        ui_layout.addWidget(ui_label)
        ui_layout.addWidget(self.ui_combo)

        # 添加到 Group
        self.generation_group.addSettingCard(self.lang_card)

        # SettingCardGroup in PyQt-Fluent-Widgets usually takes cards.
        # Looking at line 43: self.api_group = SettingCardGroup...
        # Line 55: provider_widget ...
        # Line 122: self.vBoxLayout.addWidget(self.api_group)
        # Line 124: self.vBoxLayout.addWidget(provider_widget)
        # So we should add the widgets to the main layout, not the group object itself if it doesn't support generic widgets inside.

        self.ui_card = PushSettingCard(
            "设置",
            FluentIcon.web_asset if hasattr(FluentIcon, 'web_asset') else FluentIcon.GLOBE, # Fallback
            "UI 框架",
            "选择生成的界面框架风格",
            self.generation_group
        )
        self.generation_group.addSettingCard(self.ui_card)

        # 代码质量闸门设置
        self.code_quality_card = PushSettingCard(
            "设置",
            FluentIcon.DEVELOPER_TOOLS if hasattr(FluentIcon, "DEVELOPER_TOOLS") else FluentIcon.CODE,
            "代码质量闸门",
            "配置新颖度、语法与AI改写占比阈值",
            self.generation_group
        )
        self.generation_group.addSettingCard(self.code_quality_card)

        quality_widget = QWidget()
        quality_layout = QFormLayout(quality_widget)

        self.code_novelty_edit = LineEdit()
        self.code_novelty_edit.setPlaceholderText("novelty_threshold，例如 0.46")
        self.code_file_budget_edit = LineEdit()
        self.code_file_budget_edit.setPlaceholderText("file_novelty_budget，例如 0.46")
        self.code_project_threshold_edit = LineEdit()
        self.code_project_threshold_edit.setPlaceholderText("project_novelty_threshold，例如 0.42")

        self.code_rewrite_candidates_edit = LineEdit()
        self.code_rewrite_candidates_edit.setPlaceholderText("rewrite_candidates，例如 2")
        self.code_max_rounds_edit = LineEdit()
        self.code_max_rounds_edit.setPlaceholderText("max_rewrite_rounds，例如 2")
        self.code_heavy_ratio_edit = LineEdit()
        self.code_heavy_ratio_edit.setPlaceholderText("heavy_search_ratio，例如 0.30")
        self.code_profile_combo = ComboBox()
        self.code_profile_combo.addItems(["低消耗(默认)", "高约束"])
        self.code_profile_combo.currentTextChanged.connect(self.on_quality_profile_changed)
        self.code_llm_provider_combo = ComboBox()
        self.code_llm_provider_combo.addItems(["(跟随全局)"] + self.available_providers)
        self.code_llm_model_override_edit = LineEdit()
        self.code_llm_model_override_edit.setPlaceholderText("代码阶段模型覆盖（留空=跟随所选提供商默认）")

        self.code_gate_combo = ComboBox()
        self.code_gate_combo.addItems(["True", "False"])
        self.code_file_gate_combo = ComboBox()
        self.code_file_gate_combo.addItems(["True", "False"])
        self.code_file_gate_obf_combo = ComboBox()
        self.code_file_gate_obf_combo.addItems(["False", "True"])

        self.code_max_risky_edit = LineEdit()
        self.code_max_risky_edit.setPlaceholderText("max_risky_files，例如 2")
        self.code_max_syntax_fail_edit = LineEdit()
        self.code_max_syntax_fail_edit.setPlaceholderText("max_syntax_fail_files，例如 0")
        self.code_min_ai_ratio_edit = LineEdit()
        self.code_min_ai_ratio_edit.setPlaceholderText("min_ai_line_ratio，例如 0.20")
        self.code_max_failed_edit = LineEdit()
        self.code_max_failed_edit.setPlaceholderText("max_failed_files，例如 0")
        self.code_max_llm_attempts_edit = LineEdit()
        self.code_max_llm_attempts_edit.setPlaceholderText("max_llm_attempts_per_file，例如 4")
        self.code_llm_text_retries_edit = LineEdit()
        self.code_llm_text_retries_edit.setPlaceholderText("llm_text_retries，例如 2")
        self.code_embedding_combo = ComboBox()
        self.code_embedding_combo.addItems(["False", "True"])
        self.code_embedding_weight_edit = LineEdit()
        self.code_embedding_weight_edit.setPlaceholderText("embedding_similarity_weight，例如 0.15")
        self.code_embedding_chars_edit = LineEdit()
        self.code_embedding_chars_edit.setPlaceholderText("embedding_max_chars，例如 2400")

        quality_layout.addRow("Novelty Threshold:", self.code_novelty_edit)
        quality_layout.addRow("File Novelty Budget:", self.code_file_budget_edit)
        quality_layout.addRow("Project Novelty Threshold:", self.code_project_threshold_edit)
        quality_layout.addRow("Rewrite Candidates:", self.code_rewrite_candidates_edit)
        quality_layout.addRow("Max Rewrite Rounds:", self.code_max_rounds_edit)
        quality_layout.addRow("Heavy Search Ratio:", self.code_heavy_ratio_edit)
        quality_layout.addRow("Quality Profile:", self.code_profile_combo)
        quality_layout.addRow("Code LLM Provider:", self.code_llm_provider_combo)
        quality_layout.addRow("Code LLM Model Override:", self.code_llm_model_override_edit)
        quality_layout.addRow("Enable Project Gate:", self.code_gate_combo)
        quality_layout.addRow("Enable File Gate:", self.code_file_gate_combo)
        quality_layout.addRow("File Gate On Obfuscation:", self.code_file_gate_obf_combo)
        quality_layout.addRow("Max Risky Files:", self.code_max_risky_edit)
        quality_layout.addRow("Max Syntax Fail Files:", self.code_max_syntax_fail_edit)
        quality_layout.addRow("Min AI Line Ratio:", self.code_min_ai_ratio_edit)
        quality_layout.addRow("Max Failed Files:", self.code_max_failed_edit)
        quality_layout.addRow("Max LLM Attempts/File:", self.code_max_llm_attempts_edit)
        quality_layout.addRow("LLM Text Retries:", self.code_llm_text_retries_edit)
        quality_layout.addRow("Enable Embedding Similarity:", self.code_embedding_combo)
        quality_layout.addRow("Embedding Similarity Weight:", self.code_embedding_weight_edit)
        quality_layout.addRow("Embedding Max Chars:", self.code_embedding_chars_edit)

        save_quality_btn = PrimaryPushButton("保存代码质量配置", self.view)
        save_quality_btn.clicked.connect(self.save_code_quality_config)

        # 关于
        self.about_group = SettingCardGroup("关于", self.view)
        
        self.about_card = PushSettingCard(
            "查看",
            FluentIcon.INFO,
            "软著AI自动化系统",
            "版本 1.0.0 - PyQt-Fluent-Widgets",
            self.about_group
        )
        
        self.about_group.addSettingCard(self.about_card)
        
        # 布局
        self.vBoxLayout.setSpacing(20)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.addWidget(self.api_group)
        self.vBoxLayout.addWidget(self.api_provider_card)
        self.vBoxLayout.addWidget(provider_widget)
        self.vBoxLayout.addWidget(self.api_config_widget)
        self.vBoxLayout.addWidget(save_api_btn)
        self.vBoxLayout.addSpacing(10)
        self.vBoxLayout.addWidget(self.appearance_group)
        self.vBoxLayout.addWidget(self.theme_card)

        self.vBoxLayout.addSpacing(10)
        self.vBoxLayout.addWidget(self.generation_group)
        self.vBoxLayout.addWidget(lang_widget)
        self.vBoxLayout.addWidget(ui_widget)
        self.vBoxLayout.addWidget(quality_widget)
        self.vBoxLayout.addWidget(save_quality_btn)

        self.vBoxLayout.addWidget(self.about_group)
        self.vBoxLayout.addStretch(1)

        self.load_code_quality_config()

    def save_preference(self, key: str, value: str):
        """保存偏好设置"""
        config_manager.set(key, value)
        # Update card content
        if key == "target_language":
             self.lang_card.setContent(f"当前: {value}")
        elif key == "ui_framework":
             self.ui_card.setContent(f"当前: {value}")

    def load_code_quality_config(self):
        """加载代码质量闸门配置"""
        profile_key = str(config_manager.get("code_quality_profile", "economy")).strip().lower()
        if profile_key not in self.QUALITY_PROFILE_PRESETS:
            profile_key = "economy"
        self.code_profile_combo.blockSignals(True)
        self.code_profile_combo.setCurrentText(self.QUALITY_PROFILE_KEY_TO_LABEL[profile_key])
        self.code_profile_combo.blockSignals(False)

        self.code_novelty_edit.setText(str(config_manager.get("code_novelty_threshold", 0.35)))
        self.code_file_budget_edit.setText(str(config_manager.get("code_file_novelty_budget", 0.35)))
        self.code_project_threshold_edit.setText(str(config_manager.get("code_project_novelty_threshold", 0.32)))
        self.code_rewrite_candidates_edit.setText(str(config_manager.get("code_rewrite_candidates", 1)))
        self.code_max_rounds_edit.setText(str(config_manager.get("code_max_rewrite_rounds", 1)))
        self.code_heavy_ratio_edit.setText(str(config_manager.get("code_heavy_search_ratio", 0.20)))
        provider_override = str(config_manager.get("code_llm_provider_override", "") or "").strip()
        if provider_override and provider_override not in self.available_providers:
            self.code_llm_provider_combo.addItem(provider_override)
        self.code_llm_provider_combo.setCurrentText(provider_override if provider_override else "(跟随全局)")
        self.code_llm_model_override_edit.setText(str(config_manager.get("code_llm_model_override", "") or ""))
        self.code_gate_combo.setCurrentText(
            "True" if bool(config_manager.get("code_enable_project_novelty_gate", False)) else "False"
        )
        self.code_file_gate_combo.setCurrentText(
            "True" if bool(config_manager.get("code_enforce_file_gate", False)) else "False"
        )
        self.code_file_gate_obf_combo.setCurrentText(
            "True" if bool(config_manager.get("code_enforce_file_gate_on_obfuscation", False)) else "False"
        )
        self.code_max_risky_edit.setText(str(config_manager.get("code_max_risky_files", 8)))
        self.code_max_syntax_fail_edit.setText(str(config_manager.get("code_max_syntax_fail_files", 4)))
        self.code_min_ai_ratio_edit.setText(str(config_manager.get("code_min_ai_line_ratio", 0.10)))
        self.code_max_failed_edit.setText(str(config_manager.get("code_max_failed_files", 8)))
        self.code_max_llm_attempts_edit.setText(str(config_manager.get("code_max_llm_attempts_per_file", 2)))
        self.code_llm_text_retries_edit.setText(str(config_manager.get("code_llm_text_retries", 1)))
        self.code_embedding_combo.setCurrentText(
            "True" if bool(config_manager.get("code_enable_embedding_similarity", False)) else "False"
        )
        self.code_embedding_weight_edit.setText(str(config_manager.get("code_embedding_similarity_weight", 0.15)))
        self.code_embedding_chars_edit.setText(str(config_manager.get("code_embedding_max_chars", 2400)))

    def _apply_quality_profile_preset(self, profile_key: str):
        preset = self.QUALITY_PROFILE_PRESETS.get(profile_key, self.QUALITY_PROFILE_PRESETS["economy"])
        self.code_novelty_edit.setText(str(preset["novelty_threshold"]))
        self.code_file_budget_edit.setText(str(preset["file_novelty_budget"]))
        self.code_project_threshold_edit.setText(str(preset["project_novelty_threshold"]))
        self.code_rewrite_candidates_edit.setText(str(preset["rewrite_candidates"]))
        self.code_max_rounds_edit.setText(str(preset["max_rewrite_rounds"]))
        self.code_heavy_ratio_edit.setText(str(preset["heavy_search_ratio"]))
        self.code_gate_combo.setCurrentText("True" if bool(preset["enable_project_novelty_gate"]) else "False")
        self.code_file_gate_combo.setCurrentText("True" if bool(preset["enforce_file_gate"]) else "False")
        self.code_file_gate_obf_combo.setCurrentText("True" if bool(preset["enforce_file_gate_on_obfuscation"]) else "False")
        self.code_max_risky_edit.setText(str(preset["max_risky_files"]))
        self.code_max_syntax_fail_edit.setText(str(preset["max_syntax_fail_files"]))
        self.code_min_ai_ratio_edit.setText(str(preset["min_ai_line_ratio"]))
        self.code_max_failed_edit.setText(str(preset["max_failed_files"]))
        self.code_max_llm_attempts_edit.setText(str(preset["max_llm_attempts_per_file"]))
        self.code_llm_text_retries_edit.setText(str(preset["llm_text_retries"]))
        self.code_embedding_combo.setCurrentText("True" if bool(preset["enable_embedding_similarity"]) else "False")
        self.code_embedding_weight_edit.setText(str(preset["embedding_similarity_weight"]))
        self.code_embedding_chars_edit.setText(str(preset["embedding_max_chars"]))

    def on_quality_profile_changed(self, profile_label: str):
        profile_key = self.QUALITY_PROFILE_LABEL_TO_KEY.get(profile_label, "economy")
        self._apply_quality_profile_preset(profile_key)

    def save_code_quality_config(self):
        """保存代码质量闸门配置"""
        try:
            profile_key = self.QUALITY_PROFILE_LABEL_TO_KEY.get(
                self.code_profile_combo.currentText().strip(),
                "economy",
            )
            novelty = float(self.code_novelty_edit.text().strip() or 0.35)
            file_budget = float(self.code_file_budget_edit.text().strip() or 0.35)
            project_threshold = float(self.code_project_threshold_edit.text().strip() or 0.32)
            rewrite_candidates = int(self.code_rewrite_candidates_edit.text().strip() or 1)
            max_rounds = int(self.code_max_rounds_edit.text().strip() or 1)
            heavy_ratio = float(self.code_heavy_ratio_edit.text().strip() or 0.20)
            provider_override_raw = self.code_llm_provider_combo.currentText().strip()
            provider_override = "" if provider_override_raw in {"", "(跟随全局)"} else provider_override_raw
            model_override = self.code_llm_model_override_edit.text().strip()
            gate_enabled = self.code_gate_combo.currentText().strip().lower() == "true"
            file_gate_enabled = self.code_file_gate_combo.currentText().strip().lower() == "true"
            file_gate_obf_enabled = self.code_file_gate_obf_combo.currentText().strip().lower() == "true"
            max_risky = int(self.code_max_risky_edit.text().strip() or 8)
            max_syntax_fail = int(self.code_max_syntax_fail_edit.text().strip() or 4)
            min_ai_ratio = float(self.code_min_ai_ratio_edit.text().strip() or 0.10)
            max_failed = int(self.code_max_failed_edit.text().strip() or 8)
            max_llm_attempts = int(self.code_max_llm_attempts_edit.text().strip() or 2)
            llm_text_retries = int(self.code_llm_text_retries_edit.text().strip() or 1)
            enable_embedding = self.code_embedding_combo.currentText().strip().lower() == "true"
            embedding_weight = float(self.code_embedding_weight_edit.text().strip() or 0.15)
            embedding_chars = int(self.code_embedding_chars_edit.text().strip() or 2400)
        except ValueError:
            InfoBar.warning(
                title="保存失败",
                content="代码质量配置格式错误，请检查数值输入",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return

        # 与后端同口径的边界收敛
        novelty = max(0.0, min(novelty, 1.0))
        file_budget = max(0.0, min(file_budget, 1.0))
        project_threshold = max(0.0, min(project_threshold, 1.0))
        rewrite_candidates = max(1, min(rewrite_candidates, 3))
        max_rounds = max(1, min(max_rounds, 4))
        heavy_ratio = max(0.15, min(heavy_ratio, 0.5))
        max_risky = max(0, max_risky)
        max_syntax_fail = max(0, max_syntax_fail)
        min_ai_ratio = max(0.0, min(min_ai_ratio, 1.0))
        max_failed = max(0, max_failed)
        max_llm_attempts = max(1, min(max_llm_attempts, 8))
        llm_text_retries = max(1, min(llm_text_retries, 3))
        embedding_weight = max(0.0, min(embedding_weight, 0.4))
        embedding_chars = max(400, min(embedding_chars, 8000))

        config_manager.set("code_novelty_threshold", novelty)
        config_manager.set("code_file_novelty_budget", file_budget)
        config_manager.set("code_project_novelty_threshold", project_threshold)
        config_manager.set("code_quality_profile", profile_key)
        config_manager.set("code_rewrite_candidates", rewrite_candidates)
        config_manager.set("code_max_rewrite_rounds", max_rounds)
        config_manager.set("code_heavy_search_ratio", heavy_ratio)
        config_manager.set("code_llm_provider_override", provider_override)
        config_manager.set("code_llm_model_override", model_override)
        config_manager.set("code_enable_project_novelty_gate", gate_enabled)
        config_manager.set("code_enforce_file_gate", file_gate_enabled)
        config_manager.set("code_enforce_file_gate_on_obfuscation", file_gate_obf_enabled)
        config_manager.set("code_max_risky_files", max_risky)
        config_manager.set("code_max_syntax_fail_files", max_syntax_fail)
        config_manager.set("code_min_ai_line_ratio", min_ai_ratio)
        config_manager.set("code_max_failed_files", max_failed)
        config_manager.set("code_max_llm_attempts_per_file", max_llm_attempts)
        config_manager.set("code_llm_text_retries", llm_text_retries)
        # 隐式预算参数：不暴露复杂输入，用档位自动设定，控制 token 与时长波动。
        budget_preset = self.QUALITY_PROFILE_PRESETS.get(profile_key, self.QUALITY_PROFILE_PRESETS["economy"])
        config_manager.set("code_max_total_llm_calls", int(budget_preset.get("max_total_llm_calls", 12)))
        config_manager.set("code_max_total_llm_failures", int(budget_preset.get("max_total_llm_failures", 4)))
        config_manager.set(
            "code_disable_llm_on_budget_exhausted",
            bool(budget_preset.get("disable_llm_on_budget_exhausted", True)),
        )
        config_manager.set(
            "code_disable_llm_on_failures",
            bool(budget_preset.get("disable_llm_on_failures", True)),
        )
        config_manager.set("code_enable_embedding_similarity", enable_embedding)
        config_manager.set("code_embedding_similarity_weight", embedding_weight)
        config_manager.set("code_embedding_max_chars", embedding_chars)

        # 回填收敛后的值，避免界面展示与真实配置不一致
        self.load_code_quality_config()

        InfoBar.success(
            title="保存成功",
            content="代码质量配置已保存，新任务会使用最新参数",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000
        )

    def load_api_config(self, provider: str):
        """加载API配置"""
        # 从文件重新加载以获取最新配置
        config = get_provider_config(provider)
        if config:
            self.api_key_edit.setText(config.get("api_key", ""))
            self.base_url_edit.setText(config.get("base_url", ""))
            self.model_edit.setText(config.get("model", ""))
            self.max_tokens_edit.setText(str(config.get("max_tokens", 8192)))
            self.temperature_edit.setText(str(config.get("temperature", 0.7)))
            self.transport_combo.setCurrentText(str(config.get("transport", "auto")))
            self.api_style_combo.setCurrentText(str(config.get("api_style", "chat")))
            self.http_retries_edit.setText(str(config.get("http_retries", 4)))
            self.retry_cap_edit.setText(str(config.get("retry_max_tokens_cap", 4096)))
            self.max_inflight_edit.setText(str(config.get("max_inflight_requests", 0)))
            self.min_interval_edit.setText(str(config.get("min_request_interval_seconds", 0)))
            self.use_env_proxy_combo.setCurrentText("True" if bool(config.get("use_env_proxy", True)) else "False")
            self.auto_bypass_proxy_combo.setCurrentText("True" if bool(config.get("auto_bypass_proxy_on_error", False)) else "False")
    
    def on_api_provider_changed(self, provider: str):
        """API提供商切换"""
        self.load_api_config(provider)
        self.api_provider_card.setContent(f"当前: {provider}")
        signal_bus.api_provider_changed.emit(provider)
    
    def on_theme_toggle(self):
        """主题切换按钮"""
        current = config_manager.get("theme", "dark")
        new_theme = "light" if current == "dark" else "dark"
        config_manager.set("theme", new_theme)
        signal_bus.theme_changed.emit(new_theme)
        self.theme_card.setContent(f"当前: {'浅色' if new_theme == 'light' else '深色'}")
    
    def save_api_config(self):
        """保存API配置到JSON文件"""
        provider = self.provider_combo.currentText()
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        model = self.model_edit.text().strip()
        max_tokens_text = self.max_tokens_edit.text().strip()
        temperature_text = self.temperature_edit.text().strip()
        transport = self.transport_combo.currentText().strip().lower() or "auto"
        api_style = self.api_style_combo.currentText().strip().lower() or "chat"
        http_retries_text = self.http_retries_edit.text().strip()
        retry_cap_text = self.retry_cap_edit.text().strip()
        max_inflight_text = self.max_inflight_edit.text().strip()
        min_interval_text = self.min_interval_edit.text().strip()
        use_env_proxy = self.use_env_proxy_combo.currentText().strip().lower() == "true"
        auto_bypass_proxy = self.auto_bypass_proxy_combo.currentText().strip().lower() == "true"

        # 验证输入
        if not api_key:
            InfoBar.warning(
                title="保存失败",
                content="API Key 不能为空",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return

        if not base_url:
            InfoBar.warning(
                title="保存失败",
                content="Base URL 不能为空",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return

        try:
            max_tokens = int(max_tokens_text) if max_tokens_text else 8192
            temperature = float(temperature_text) if temperature_text else 0.7
            http_retries = int(http_retries_text) if http_retries_text else 4
            retry_cap = int(retry_cap_text) if retry_cap_text else 4096
            max_inflight = int(max_inflight_text) if max_inflight_text else 0
            min_interval = float(min_interval_text) if min_interval_text else 0.0
        except ValueError:
            InfoBar.warning(
                title="保存失败",
                content="数值字段格式错误，请检查 max_tokens/temperature/retries/limit",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return

        max_inflight = max(0, min(max_inflight, 16))
        min_interval = max(0.0, min(min_interval, 10.0))

        # 保存配置到JSON文件
        try:
            success = update_provider_config(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                transport=transport,
                api_style=api_style,
                http_retries=http_retries,
                retry_max_tokens_cap=retry_cap,
                use_env_proxy=use_env_proxy,
                auto_bypass_proxy_on_error=auto_bypass_proxy,
                max_inflight_requests=max_inflight,
                min_request_interval_seconds=min_interval,
            )

            # 设置当前提供商
            set_current_provider(provider)

            if success:
                InfoBar.success(
                    title="保存成功",
                    content=f"API配置已保存到 config/api_config.json\n新任务将立即使用最新配置",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
                # 通知其他组件配置已更改
                signal_bus.api_provider_changed.emit(provider)
            else:
                InfoBar.error(
                    title="保存失败",
                    content="写入配置文件时发生错误",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
        except Exception as e:
            InfoBar.error(
                title="保存失败",
                content=f"保存配置时发生错误: {str(e)}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
