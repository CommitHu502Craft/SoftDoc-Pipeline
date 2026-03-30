"""
项目基因图谱随机引擎
使用项目名称MD5作为种子，确保同一项目名每次生成结果一致，不同项目名差异最大化
"""
import json
import random
import hashlib
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime
from core.logger import create_logger


class RandomEngine:
    """
    单例模式的随机决策引擎
    为每个项目生成一致的"基因图谱"，包含所有随机化配置
    """

    _instance: Optional['RandomEngine'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if RandomEngine._initialized:
            return

        self._project_name: Optional[str] = None
        self._seed: Optional[int] = None
        self._rng: Optional[random.Random] = None
        self._genome: Optional[Dict[str, Any]] = None
        self._logger = create_logger("RandomEngine")

        # 确保日志目录存在
        self._log_file = Path(__file__).parent.parent / "logs" / "genome_decisions.log"
        self._log_file.parent.mkdir(parents=True, exist_ok=True)

        # 加载配置文件
        self._config = self._load_config()

        RandomEngine._initialized = True

    def _load_config(self) -> Dict[str, Any]:
        """
        加载基因图谱配置文件

        Returns:
            dict: 配置数据
        """
        config_path = Path(__file__).parent.parent / "config" / "genome_config.json"

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self._logger.info(f"已加载基因图谱配置: {config_path}")
            return config
        except FileNotFoundError:
            self._logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
            return self._get_default_config()
        except json.JSONDecodeError as e:
            self._logger.error(f"配置文件JSON解析失败: {e}，使用默认配置")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """
        获取默认配置（当配置文件不存在或损坏时使用）

        Returns:
            dict: 默认配置
        """
        return {
            "languages": {
                "Java": {"framework": "Spring Boot", "file_ext": ".java"},
                "Python": {"framework": "FastAPI", "file_ext": ".py"}
            },
            "ui_frameworks": {
                "Tailwind": {"cdn_url": "https://cdn.tailwindcss.com"},
                "Bootstrap": {"cdn_url": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"}
            },
            "layout_modes": {
                "sidebar-left": {"description": "左侧边栏导航"},
                "topbar": {"description": "顶部水平导航"}
            },
            "color_palettes": [
                {
                    "name": "ocean",
                    "primary": "hsl(210, 79%, 46%)",
                    "secondary": "hsl(199, 89%, 48%)",
                    "accent": "hsl(187, 100%, 42%)",
                    "background": "hsl(210, 17%, 98%)"
                }
            ],
            "narrative_styles": {
                "technical": {"description": "技术导向风格"},
                "business": {"description": "商业导向风格"}
            }
        }

    def set_project_seed(self, project_name: str):
        """
        设置项目种子

        Args:
            project_name: 项目名称，用于生成MD5种子
        """
        self._project_name = project_name

        # 使用项目名的MD5前8位作为种子
        md5_hash = hashlib.md5(project_name.encode('utf-8')).hexdigest()
        self._seed = int(md5_hash[:8], 16)

        # 创建独立的随机数生成器
        self._rng = random.Random(self._seed)

        # 重置基因图谱
        self._genome = None

        # 记录种子设置
        self._log_decision(f"项目: {project_name}, 种子: {self._seed}")
        self._logger.info(f"已设置项目种子 - 项目: {project_name}, 种子: {self._seed}")

    def apply_overrides(self, overrides: Dict[str, str]):
        """应用用户指定的覆盖配置"""
        self._ensure_initialized()

        # 确保基因图谱已生成
        if self._genome is None:
            self.get_genome()

        if not overrides:
            return

        # 应用覆盖
        for key, value in overrides.items():
            if value and value != "Random":
                self._genome[key] = value
                self._log_decision(f"应用用户覆盖: {key} -> {value}")
                self._logger.info(f"应用用户覆盖: {key}={value}")

    def get_target_language(self) -> str:
        """
        获取目标编程语言

        Returns:
            str: 随机选择的编程语言
        """
        self._ensure_initialized()
        languages = list(self._config.get("languages", {}).keys())
        if not languages:
            languages = ["Python"]

        language = self._rng.choice(languages)
        lang_config = self._config["languages"].get(language, {})

        self._log_decision(
            f"目标语言: {language}, "
            f"框架: {lang_config.get('framework', 'N/A')}, "
            f"扩展名: {lang_config.get('file_ext', 'N/A')}"
        )
        return language

    def get_language_config(self, language: str = None) -> Dict[str, Any]:
        """
        获取指定语言的完整配置

        Args:
            language: 语言名称，如果为None则获取当前选择的语言

        Returns:
            dict: 语言配置详情
        """
        self._ensure_initialized()
        if language is None:
            language = self.get_target_language()

        return self._config.get("languages", {}).get(language, {})

    def get_ui_framework(self) -> str:
        """
        获取UI框架

        Returns:
            str: 随机选择的UI框架
        """
        self._ensure_initialized()
        frameworks = list(self._config.get("ui_frameworks", {}).keys())
        if not frameworks:
            frameworks = ["Bootstrap"]

        framework = self._rng.choice(frameworks)
        fw_config = self._config["ui_frameworks"].get(framework, {})

        self._log_decision(
            f"UI框架: {framework}, "
            f"版本: {fw_config.get('version', 'N/A')}"
        )
        return framework

    def get_ui_framework_config(self, framework: str = None) -> Dict[str, Any]:
        """
        获取指定UI框架的完整配置

        Args:
            framework: 框架名称，如果为None则获取当前选择的框架

        Returns:
            dict: 框架配置详情
        """
        self._ensure_initialized()
        if framework is None:
            framework = self.get_ui_framework()

        return self._config.get("ui_frameworks", {}).get(framework, {})

    def get_visual_style(self) -> str:
        """
        获取视觉风格 (Design System)
        基于项目名称哈希锁定

        Returns:
            str: 风格名称 (Enterprise/SaaS/Data)
        """
        self._ensure_initialized()
        styles = list(self._config.get("design_systems", {}).keys())
        if not styles:
            styles = ["Enterprise"]

        # 使用随机数生成器选择，保证确定性
        style = self._rng.choice(styles)

        style_config = self._config["design_systems"].get(style, {})
        self._log_decision(
            f"视觉风格: {style}, "
            f"描述: {style_config.get('description', 'N/A')}"
        )
        return style

    def get_design_system_config(self, style: str = None) -> Dict[str, Any]:
        """
        获取指定视觉风格的详细配置

        Args:
            style: 风格名称

        Returns:
            dict: 配置详情
        """
        self._ensure_initialized()
        if style is None:
            style = self.get_visual_style()

        return self._config.get("design_systems", {}).get(style, {})

    def get_business_context(self) -> List[str]:
        """
        生成业务上下文关键词
        根据项目名称关键词匹配行业，生成20个专有名词

        Returns:
            List[str]: 20个业务名词
        """
        self._ensure_initialized()
        name = self._project_name or ""

        # 简单的关键词映射库
        # 实际应用中可以移至配置文件
        industry_terms = {
            "医疗": ["门诊号", "医保结算", "处方流转", "电子病历", "检验报告", "住院床位", "医嘱管理", "分诊排队", "药品库存", "手术排期", "生命体征", "影像归档", "远程会诊", "公共卫生", "疫苗接种", "慢病管理", "转诊记录", "血库管理", "院感监控", "医疗废物"],
            "教育": ["学籍档案", "课程表", "教案管理", "在线考试", "成绩分析", "家校互通", "图书借阅", "宿舍管理", "奖学金", "选课系统", "师资考评", "科研项目", "实验室预约", "学分统计", "迎新报到", "毕业设计", "校园一卡通", "心理健康", "社团活动", "勤工助学"],
            "金融": ["账户流水", "信贷审批", "风险评估", "理财产品", "跨境支付", "征信报告", "反洗钱", "资产清算", "外汇交易", "保险理赔", "股票行情", "基金定投", "大额存单", "信用卡", "区块链记账", "智能合约", "客户画像", "营销活动", "合规审计", "资金存管"],
            "电商": ["SKU管理", "订单履约", "物流追踪", "售后退款", "优惠券", "秒杀活动", "直播带货", "会员积分", "供应链", "库存预警", "竞品分析", "流量转化", "客单价", "购物车", "评价管理", "分销佣金", "店铺装修", "广告投放", "数据大屏", "支付网关"],
            "林业": ["林权证", "采伐限额", "森林防火", "病虫害防治", "野生动物", "古树名木", "碳汇交易", "巡护记录", "无人机监测", "卫星遥感", "土壤墒情", "气象数据", "苗木培育", "木材运输", "执法台账", "生态补偿", "护林员", "瞭望塔", "红外相机", "生物多样性"]
        }

        # 匹配行业
        selected_industry = "通用"
        terms = []

        for key, val in industry_terms.items():
            if key in name:
                selected_industry = key
                terms = val
                break

        # 如果没有匹配到，使用通用企业术语
        if not terms:
            selected_industry = "通用企业"
            terms = ["审批流程", "组织架构", "考勤打卡", "薪资核算", "报销单", "合同管理", "客户关系", "项目进度", "会议纪要", "固定资产", "采购订单", "库存盘点", "销售报表", "预算控制", "绩效考核", "招聘计划", "培训记录", "企业文化", "公文流转", "系统日志"]

        self._log_decision(f"业务上下文: 行业=[{selected_industry}], 关键词数={len(terms)}")
        return terms

    def get_layout_mode(self) -> str:
        """
        获取布局模式

        Returns:
            str: 随机选择的布局模式
        """
        self._ensure_initialized()
        layouts = list(self._config.get("layout_modes", {}).keys())
        if not layouts:
            layouts = ["sidebar-left"]

        layout = self._rng.choice(layouts)
        layout_config = self._config["layout_modes"].get(layout, {})

        self._log_decision(
            f"布局模式: {layout}, "
            f"描述: {layout_config.get('description', 'N/A')}"
        )
        return layout

    def get_layout_config(self, layout: str = None) -> Dict[str, Any]:
        """
        获取指定布局模式的完整配置

        Args:
            layout: 布局模式名称，如果为None则获取当前选择的布局

        Returns:
            dict: 布局配置详情
        """
        self._ensure_initialized()
        if layout is None:
            layout = self.get_layout_mode()

        return self._config.get("layout_modes", {}).get(layout, {})

    def get_color_scheme(self) -> Dict[str, str]:
        """
        获取配色方案

        Returns:
            dict: 包含主色调、强调色、背景色等的字典（HSL格式）
        """
        self._ensure_initialized()
        palettes = self._config.get("color_palettes", [])
        if not palettes:
            palettes = [{
                "name": "default",
                "primary": "hsl(210, 79%, 46%)",
                "background": "hsl(210, 17%, 98%)"
            }]

        color_scheme = self._rng.choice(palettes)

        self._log_decision(
            f"配色方案: {color_scheme.get('name', 'N/A')} - "
            f"{color_scheme.get('description', '')}, "
            f"主色: {color_scheme.get('primary', 'N/A')}"
        )
        return color_scheme.copy()

    def get_narrative_style(self) -> str:
        """
        获取叙述风格（用于文档生成）

        Returns:
            str: 随机选择的叙述风格
        """
        self._ensure_initialized()
        styles = list(self._config.get("narrative_styles", {}).keys())
        if not styles:
            styles = ["business"]

        style = self._rng.choice(styles)
        style_config = self._config["narrative_styles"].get(style, {})

        self._log_decision(
            f"叙述风格: {style}, "
            f"描述: {style_config.get('description', 'N/A')}"
        )
        return style

    def get_narrative_style_config(self, style: str = None) -> Dict[str, Any]:
        """
        获取指定叙述风格的完整配置

        Args:
            style: 风格名称，如果为None则获取当前选择的风格

        Returns:
            dict: 风格配置详情
        """
        self._ensure_initialized()
        if style is None:
            style = self.get_narrative_style()

        return self._config.get("narrative_styles", {}).get(style, {})

    def get_database_type(self) -> str:
        """
        获取数据库类型（额外功能）

        Returns:
            str: 随机选择的数据库类型
        """
        self._ensure_initialized()
        databases = list(self._config.get("database_types", {}).keys())
        if not databases:
            return "MySQL"

        database = self._rng.choice(databases)
        db_config = self._config["database_types"].get(database, {})

        self._log_decision(
            f"数据库类型: {database}, "
            f"版本: {db_config.get('version', 'N/A')}"
        )
        return database

    def get_architecture_pattern(self) -> str:
        """
        获取架构模式（额外功能）

        Returns:
            str: 随机选择的架构模式
        """
        self._ensure_initialized()
        patterns = list(self._config.get("architecture_patterns", {}).keys())
        if not patterns:
            return "mvc"

        pattern = self._rng.choice(patterns)
        pattern_config = self._config["architecture_patterns"].get(pattern, {})

        self._log_decision(
            f"架构模式: {pattern_config.get('name', pattern)}, "
            f"复杂度: {pattern_config.get('complexity', 'N/A')}"
        )
        return pattern

    def get_genome(self) -> Dict[str, Any]:
        """
        获取完整的项目基因图谱

        Returns:
            dict: 包含所有随机决策的字典
        """
        self._ensure_initialized()

        # 如果已经生成过，直接返回缓存
        if self._genome is not None:
            return self._genome.copy()

        # 生成完整基因图谱
        self._genome = {
            "project_name": self._project_name,
            "seed": self._seed,
            "target_language": self.get_target_language(),
            "ui_framework": self.get_ui_framework(),
            "layout_mode": self.get_layout_mode(),
            "visual_style": self.get_visual_style(),  # V2.1 新增
            "business_context": self.get_business_context(),  # V2.1 新增
            "color_scheme": self.get_color_scheme(),
            "narrative_style": self.get_narrative_style(),
            "database_type": self.get_database_type(),
            "architecture_pattern": self.get_architecture_pattern(),
            "generated_at": datetime.now().isoformat()
        }

        self._logger.info(f"已生成完整基因图谱: {self._project_name}")
        self._log_decision(f"完整基因图谱: {self._genome}")

        return self._genome.copy()

    def _ensure_initialized(self):
        """确保已设置项目种子"""
        if self._rng is None:
            raise RuntimeError(
                "随机引擎未初始化！请先调用 set_project_seed(project_name) 设置项目种子。"
            )

    def _log_decision(self, message: str):
        """
        记录决策到日志文件

        Args:
            message: 日志消息
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"

        try:
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            self._logger.warning(f"无法写入基因图谱日志: {e}")

    def reset(self):
        """重置随机引擎（用于测试）"""
        self._project_name = None
        self._seed = None
        self._rng = None
        self._genome = None
        self._logger.info("随机引擎已重置")


# 全局单例获取函数
_random_engine: Optional[RandomEngine] = None


def get_random_engine() -> RandomEngine:
    """
    获取随机引擎单例

    Returns:
        RandomEngine: 随机引擎实例
    """
    global _random_engine
    if _random_engine is None:
        _random_engine = RandomEngine()
    return _random_engine


# 便捷函数
def set_project_seed(project_name: str):
    """设置项目种子"""
    get_random_engine().set_project_seed(project_name)


def get_project_genome() -> Dict[str, Any]:
    """获取项目基因图谱"""
    return get_random_engine().get_genome()
