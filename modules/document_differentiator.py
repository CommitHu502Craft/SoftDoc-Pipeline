"""
说明书差异化增强器
通过多样化的文本表达、段落结构、术语选择等方式让每个项目的说明书具有独特性
"""
import random
import hashlib
from typing import Dict, List, Any, Optional


class DocumentDifferentiator:
    """说明书差异化增强器"""

    # 系统介绍的多种表达方式
    INTRO_TEMPLATES = [
        "{project_name}是一款面向{industry}领域的专业化管理平台，通过先进的信息技术手段，实现业务流程的数字化转型。",
        "本系统（{project_name}）致力于为{industry}行业提供全方位的信息化解决方案，助力企业提升管理效能。",
        "{project_name}作为{industry}领域的创新型应用系统，采用现代化架构设计，为用户提供高效便捷的业务处理能力。",
        "基于{industry}行业的实际需求，{project_name}系统整合了多项核心功能，构建了一体化的管理平台。",
        "{project_name}平台是专门针对{industry}领域开发的智能化管理系统，具有操作简便、功能完善的特点。"
    ]

    # 功能描述的多种表达方式
    FEATURE_VERBS = {
        "查询": ["查看", "检索", "浏览", "获取", "查找"],
        "添加": ["新增", "创建", "录入", "登记", "增加"],
        "修改": ["编辑", "更新", "变更", "调整", "修订"],
        "删除": ["移除", "清除", "剔除", "去除", "删掉"],
        "导出": ["输出", "下载", "提取", "导出", "生成"],
        "统计": ["汇总", "分析", "统计", "计算", "聚合"],
        "管理": ["维护", "管控", "处理", "操作", "治理"]
    }

    # 操作步骤的多种引导词
    STEP_PREFIXES = [
        ["第一步", "第二步", "第三步", "第四步", "第五步"],
        ["步骤1", "步骤2", "步骤3", "步骤4", "步骤5"],
        ["首先", "其次", "然后", "接着", "最后"],
        ["1.", "2.", "3.", "4.", "5."],
        ["一、", "二、", "三、", "四、", "五、"]
    ]

    # 功能说明的连接词
    CONNECTORS = {
        "功能": ["该功能", "此功能", "本功能", "该模块", "此模块"],
        "用户可以": ["用户能够", "用户可", "使用者可以", "操作者能够", "用户可通过此功能"],
        "点击": ["单击", "点选", "点击", "选择", "点按"],
        "输入": ["填写", "录入", "输入", "键入", "填入"],
        "选择": ["挑选", "选取", "选定", "指定", "勾选"]
    }

    # 系统特点的多种描述
    FEATURE_DESCRIPTIONS = [
        "界面简洁直观，操作流程清晰明了",
        "采用响应式设计，支持多终端访问",
        "功能模块化设计，便于扩展维护",
        "具备完善的权限控制机制",
        "提供丰富的数据可视化展示",
        "支持批量操作，提升工作效率",
        "内置智能检索功能，快速定位信息",
        "实时数据同步，确保信息准确性"
    ]

    # 技术架构的多种表述
    TECH_DESCRIPTIONS = {
        "前端": ["前端界面", "用户界面", "客户端", "展示层", "前台系统"],
        "后端": ["后端服务", "服务端", "业务逻辑层", "后台系统", "服务层"],
        "数据库": ["数据存储", "持久化层", "数据管理", "存储系统", "数据层"],
        "架构": ["系统架构", "技术架构", "整体架构", "框架设计", "体系结构"]
    }

    # 章节标题变体库 (Phase 2)
    CHAPTER_TITLES = {
        "intro": ["系统概述", "产品简介", "平台概况", "总体说明", "引言"],
        "install": ["安装部署", "环境配置", "系统部署", "安装指南", "实施说明"],
        "manual": ["操作指南", "使用说明", "用户手册", "功能操作", "业务指南"],
        "faq": ["常见问题", "疑难解答", "故障排除", "Q&A", "运维支持"],
        "design": ["系统设计", "详细设计", "技术架构", "设计说明", "架构方案"]
    }

    # 身份伪造工厂数据 (Phase 3)
    FAKE_AUTHORS = [
        "张伟", "王强", "李明", "刘洋", "陈杰", "杨帆", "赵勇", "黄涛", "周杰", "吴磊",
        "Admin", "Administrator", "Developer", "IT_Dept", "System", "Team_Lead",
        "Zhang Wei", "Li Ming", "Wang Qiang", "Liu Yang", "Chen Jie",
        "dev01", "dev_master", "soft_admin"
    ]

    FAKE_COMPANIES = [
        "信息技术部", "研发中心", "软件开发组", "技术支持部", "产品研发部",
        "IT Department", "R&D Center", "Tech Team", "Software Group"
    ]

    FAKE_TOOLS = [
        "Microsoft Office Word", "Microsoft Word 2019", "Microsoft Word 2016",
        "WPS Office", "WPS 2019", "WPS 2023",
        "Apache POI", "LibreOffice/7.3.7.2$Linux_X86_64"
    ]

    def __init__(self, plan: Dict[str, Any], seed: Optional[int] = None):
        """
        初始化差异化增强器

        Args:
            plan: 项目规划字典
            seed: 随机种子（可选，默认基于项目名生成）
        """
        self.plan = plan
        self.project_name = plan.get("project_name", "系统")

        # 生成确定性随机种子
        if seed is None:
            seed_str = hashlib.md5(self.project_name.encode()).hexdigest()[:8]
            seed = int(seed_str, 16)

        self.rng = random.Random(seed)

        # 选择本次使用的表达方式
        self.selected_intro = self.rng.choice(self.INTRO_TEMPLATES)
        self.selected_step_prefix = self.rng.choice(self.STEP_PREFIXES)

    def get_fake_metadata(self) -> Dict[str, Any]:
        """
        生成伪造的文档元数据 (Phase 3)
        包括：作者、公司、创建工具、创建时间、修改时间
        """
        from datetime import datetime, timedelta

        # 1. 生成开发周期 (3-6个月前开始)
        days_back = self.rng.randint(90, 180)
        start_date = datetime.now() - timedelta(days=days_back)

        # 2. 创建时间 (Start date + 1-30 days)
        create_offset = self.rng.randint(1, 30)
        create_time = start_date + timedelta(days=create_offset)

        # 3. 修改时间 (Create time + 30-60 days, ensuring < now)
        modify_offset = self.rng.randint(30, 60)
        modify_time = create_time + timedelta(days=modify_offset)
        if modify_time > datetime.now():
            modify_time = datetime.now() - timedelta(hours=self.rng.randint(1, 24))

        return {
            "author": self.rng.choice(self.FAKE_AUTHORS),
            "company": self.rng.choice(self.FAKE_COMPANIES),
            "creator": self.rng.choice(self.FAKE_TOOLS),
            "created": create_time,
            "modified": modify_time,
            "last_modified_by": self.rng.choice(self.FAKE_AUTHORS) # 可能与作者不同
        }

    def get_chapter_title(self, key: str) -> str:
        """获取章节标题变体 (Phase 2)"""
        if key in self.CHAPTER_TITLES:
            return self.rng.choice(self.CHAPTER_TITLES[key])
        return key

    def get_structure_strategy(self) -> Dict[str, bool]:
        """生成文档结构随机化策略 (Phase 2)"""
        return {
            "merge_install_into_intro": self.rng.choice([True, False]), # 是否将安装合并到简介
            "separate_db_design": self.rng.choice([True, False]),       # 是否单独列出数据库设计
            "append_faq": self.rng.choice([True, False]),               # 是否添加FAQ章节
            "swap_design_manual_order": self.rng.choice([True, False])  # 是否交换设计和操作手册顺序
        }

    def get_intro_text(self, industry: str = "业务管理") -> str:
        """
        获取系统介绍文本

        Args:
            industry: 行业领域

        Returns:
            str: 差异化的系统介绍
        """
        return self.selected_intro.format(
            project_name=self.project_name,
            industry=industry
        )

    def vary_verb(self, verb: str) -> str:
        """
        将动词替换为同义词

        Args:
            verb: 原始动词

        Returns:
            str: 替换后的动词
        """
        if verb in self.FEATURE_VERBS:
            return self.rng.choice(self.FEATURE_VERBS[verb])
        return verb

    def get_step_prefix(self, step_index: int) -> str:
        """
        获取步骤前缀

        Args:
            step_index: 步骤索引（从0开始）

        Returns:
            str: 步骤前缀
        """
        if step_index < len(self.selected_step_prefix):
            return self.selected_step_prefix[step_index]
        return f"步骤{step_index + 1}"

    def vary_connector(self, connector_type: str) -> str:
        """
        替换连接词

        Args:
            connector_type: 连接词类型（如"功能"、"用户可以"等）

        Returns:
            str: 替换后的连接词
        """
        if connector_type in self.CONNECTORS:
            return self.rng.choice(self.CONNECTORS[connector_type])
        return connector_type

    def get_feature_description(self, count: int = 3) -> List[str]:
        """
        获取系统特点描述

        Args:
            count: 需要的特点数量

        Returns:
            List[str]: 特点描述列表
        """
        # 打乱并选择指定数量
        features = self.FEATURE_DESCRIPTIONS.copy()
        self.rng.shuffle(features)
        return features[:count]

    def vary_tech_term(self, term: str) -> str:
        """
        替换技术术语

        Args:
            term: 原始术语

        Returns:
            str: 替换后的术语
        """
        if term in self.TECH_DESCRIPTIONS:
            return self.rng.choice(self.TECH_DESCRIPTIONS[term])
        return term

    def enrich_page_description(self, original_desc: str, page_title: str) -> str:
        """
        丰富页面描述

        Args:
            original_desc: 原始描述
            page_title: 页面标题

        Returns:
            str: 增强后的描述
        """
        # 添加多样化的前缀
        prefixes = [
            f"{page_title}是{self.project_name}的重要组成部分。",
            f"在{page_title}中，",
            f"{page_title}提供了完善的功能。",
            f"通过{page_title}，",
            ""  # 有时不添加前缀
        ]

        prefix = self.rng.choice(prefixes)

        # 添加多样化的后缀
        suffixes = [
            "帮助用户高效完成业务操作。",
            "提升工作效率和管理水平。",
            "实现业务流程的标准化管理。",
            "为决策提供数据支持。",
            ""  # 有时不添加后缀
        ]

        suffix = self.rng.choice(suffixes)

        # 组合描述
        parts = [p for p in [prefix, original_desc, suffix] if p]
        return "".join(parts)

    def generate_widget_intro(self, widget_title: str, widget_type: str) -> str:
        """
        生成组件介绍文本

        Args:
            widget_title: 组件标题
            widget_type: 组件类型（chart/table）

        Returns:
            str: 组件介绍
        """
        if widget_type == "table":
            templates = [
                f"{widget_title}以表格形式展示详细数据，支持排序、筛选等操作。",
                f"该数据表（{widget_title}）提供了完整的信息浏览和管理功能。",
                f"{widget_title}表格展示了各项数据指标，便于用户快速查阅。",
                f"通过{widget_title}，用户可以便捷地浏览和处理相关数据。"
            ]
        else:  # chart
            templates = [
                f"{widget_title}通过图表形式直观展示数据趋势和分布情况。",
                f"该图表（{widget_title}）以可视化方式呈现关键指标。",
                f"{widget_title}采用图形化展示，让数据分析更加清晰明了。",
                f"通过{widget_title}，用户能够快速掌握数据变化趋势。"
            ]

        return self.rng.choice(templates)

    def generate_operation_guide(self, operation: str, details: str = "") -> str:
        """
        生成操作指南文本

        Args:
            operation: 操作名称
            details: 操作详情

        Returns:
            str: 操作指南
        """
        # 替换动词
        varied_op = self.vary_verb(operation)

        # 选择引导词
        guides = [
            f"{self.vary_connector('用户可以')}{varied_op}{details}。",
            f"{self.vary_connector('点击')}相应按钮即可{varied_op}{details}。",
            f"系统支持{varied_op}{details}功能。",
            f"{varied_op}{details}操作简单便捷。"
        ]

        return self.rng.choice(guides)

    def shuffle_sections(self, sections: List[str], keep_first: bool = True) -> List[str]:
        """
        打乱章节顺序（可选保持第一章节）

        Args:
            sections: 章节列表
            keep_first: 是否保持第一章节不动

        Returns:
            List[str]: 打乱后的章节列表
        """
        if keep_first and len(sections) > 1:
            first = sections[0]
            rest = sections[1:]
            self.rng.shuffle(rest)
            return [first] + rest
        else:
            shuffled = sections.copy()
            self.rng.shuffle(shuffled)
            return shuffled

    def get_conclusion_text(self) -> str:
        """
        获取结语文本 (增强版：组合式长段落)
        """
        # 第一部分：架构与设计总结
        part1_templates = [
            f"综上所述，{self.project_name}凭借先进的技术架构与模块化设计，构建了一个高可用、高扩展的业务管理平台。",
            f"总体而言，{self.project_name}采用现代化开发模式，在确保系统稳定性的同时，实现了界面交互的流畅性与数据存储的安全性。",
            f"回顾全文，{self.project_name}通过精心设计的交互界面与强大的后台逻辑，完美契合了当前业务场景的实际需求，体现了软件工程的高标准规范。",
            f"本说明书详细阐述了{self.project_name}的各项功能与操作流程，系统整体设计遵循高内聚低耦合原则，具备良好的可维护性。"
        ]

        # 第二部分：价值与效能
        part2_templates = [
            "系统不仅实现了核心业务流程的自动化闭环，更通过多维度的数据可视化分析功能，为管理层提供了精准且直观的决策支持。",
            "其完善的功能矩阵覆盖了日常作业的各个环节，有效解决了传统手工模式下的痛点，降低了人力成本，显著提升了整体运营效率。",
            "在实际应用中，系统展现出了卓越的性能表现，能够从容应对高并发访问与海量数据处理的挑战，确保了业务连续性。",
            "通过对业务数据的深度挖掘与整合，系统打破了信息孤岛，促进了各部门间的协同工作，实现了资源的优化配置。"
        ]

        # 第三部分：展望与愿景
        part3_templates = [
            "未来，我们将持续关注用户反馈，不断迭代优化功能细节，致力于为用户提供更加智能、便捷、人性化的服务体验。",
            "随着业务的不断发展，本系统也将保持灵活的演进能力，持续引入前沿技术，为行业的数字化转型注入源源不断的动力。",
            "相信通过本系统的深入应用与推广，定能推动相关业务管理迈向标准化、规范化、智能化的新台阶，创造更大的社会与经济价值。",
            "作为信息化建设的重要成果，{self.project_name}将成为推动业务创新的坚实基石，助力企业在激烈的市场竞争中保持优势。"
        ]

        # 随机组合，形成一个丰满的段落
        p1 = self.rng.choice(part1_templates)
        p2 = self.rng.choice(part2_templates)
        p3 = self.rng.choice(part3_templates).format(self=self) # part3 中可能包含 self引用

        return f"{p1}{p2}{p3}"

    def get_deployment_guide(self, language: str = "python") -> Dict[str, Any]:
        """
        生成部署说明章节内容 (Phase 5)
        """
        language = language.lower()

        # 1. 环境要求
        hardware_reqs = [
            "CPU: 4核心 2.0GHz 及以上",
            "内存: 8GB RAM 及以上",
            "硬盘: 50GB 可用存储空间",
            "网络: 10Mbps 及以上宽带",
            "服务器架构: x86_64 / ARM64"
        ]

        if language == "java":
            software_reqs = [
                "操作系统: CentOS 7.6 / Ubuntu 20.04 / Windows Server 2019",
                "JDK版本: OpenJDK 17 或 Oracle JDK 17",
                "数据库: MySQL 8.0+",
                "缓存服务: Redis 6.0+",
                "Web服务器: Nginx 1.18+"
            ]
            deploy_cmd = "java -jar app.jar --spring.profiles.active=prod"
        else: # python
            software_reqs = [
                "操作系统: CentOS 7.6 / Ubuntu 20.04 / Windows Server 2019",
                "Python版本: Python 3.10+",
                "数据库: MySQL 8.0+",
                "缓存服务: Redis 6.0+",
                "Web服务器: Nginx 1.18+ (配合 Gunicorn/Uvicorn)"
            ]
            deploy_cmd = "uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4"

        # 2. 部署步骤 (差异化)
        steps = [
            {
                "title": "环境准备",
                "content": f"首先确保服务器已安装必要的运行环境。可使用命令 {self.vary_verb('检查')} 版本信息。"
            },
            {
                "title": "代码获取与编译",
                "content": f"从代码仓库{self.vary_verb('获取')}源代码，并执行构建脚本。确保依赖包下载完整。"
            },
            {
                "title": "数据库初始化",
                "content": f"登录MySQL数据库，{self.vary_verb('创建')}业务数据库，并{self.vary_verb('导入')}初始化SQL脚本(init.sql)。"
            },
            {
                "title": "配置文件修改",
                "content": "根据实际生产环境，修改配置文件中的数据库连接串、Redis地址及相关密钥信息。"
            },
            {
                "title": "服务启动",
                "content": f"执行启动命令：`{deploy_cmd}`。观察控制台日志，出现\"Started\"字样即表示启动成功。"
            }
        ]

        # 3. 常见问题 (FAQ)
        faqs = [
            {
                "q": "启动时提示端口被占用怎么办？",
                "a": "使用 `netstat -tlnp` 命令检查端口占用情况，修改配置文件中的 server.port 端口号。"
            },
            {
                "q": "数据库连接超时如何解决？",
                "a": "检查防火墙设置是否放通了3306端口，并确认配置文件中的数据库账号密码正确。"
            },
            {
                "q": "上传文件失败显示权限不足？",
                "a": "请检查上传目录的文件权限，建议执行 `chmod 755 -R upload_dir` 赋予读写权限。"
            }
        ]

        self.rng.shuffle(hardware_reqs)
        # self.rng.shuffle(software_reqs) # 软件要求一般有顺序，不乱序

        return {
            "hardware": hardware_reqs,
            "software": software_reqs,
            "steps": steps,
            "faqs": faqs
        }
