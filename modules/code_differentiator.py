"""
代码差异化引擎
通过多维度差异化让每个项目生成的代码具有独特性，解决软著申请"与已登记软件存在雷同"的问题
"""
import random
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime


class CodeDifferentiator:
    """代码差异化引擎"""

    # 8种注释样式配置
    COMMENT_STYLES = {
        "style_a": {
            "name": "经典边框",
            "python": {
                "header": "# " + "=" * 60,
                "line": "# {content}",
                "footer": "# " + "=" * 60
            },
            "java": {
                "header": "/**\n * " + "=" * 58,
                "line": " * {content}",
                "footer": " * " + "=" * 58 + "\n */"
            }
        },
        "style_b": {
            "name": "短横线边框",
            "python": {
                "header": "# " + "-" * 60,
                "line": "# {content}",
                "footer": "# " + "-" * 60
            },
            "java": {
                "header": "/**\n * " + "-" * 58,
                "line": " * {content}",
                "footer": " * " + "-" * 58 + "\n */"
            }
        },
        "style_c": {
            "name": "星号边框",
            "python": {
                "header": "# " + "*" * 60,
                "line": "# {content}",
                "footer": "# " + "*" * 60
            },
            "java": {
                "header": "/**\n * " + "*" * 58,
                "line": " * {content}",
                "footer": " * " + "*" * 58 + "\n */"
            }
        },
        "style_d": {
            "name": "双线框",
            "python": {
                "header": "# ╔" + "═" * 60 + "╗",
                "line": "# ║ {content:<58} ║",
                "footer": "# ╚" + "═" * 60 + "╝"
            },
            "java": {
                "header": "/**\n * ╔" + "═" * 58 + "╗",
                "line": " * ║ {content:<56} ║",
                "footer": " * ╚" + "═" * 58 + "╝\n */"
            }
        },
        "style_e": {
            "name": "单线框",
            "python": {
                "header": "# ┌" + "─" * 60 + "┐",
                "line": "# │ {content:<58} │",
                "footer": "# └" + "─" * 60 + "┘"
            },
            "java": {
                "header": "/**\n * ┌" + "─" * 58 + "┐",
                "line": " * │ {content:<56} │",
                "footer": " * └" + "─" * 58 + "┘\n */"
            }
        },
        "style_f": {
            "name": "加号边框",
            "python": {
                "header": "# +" + "-" * 60 + "+",
                "line": "# | {content:<58} |",
                "footer": "# +" + "-" * 60 + "+"
            },
            "java": {
                "header": "/**\n * +" + "-" * 58 + "+",
                "line": " * | {content:<56} |",
                "footer": " * +" + "-" * 58 + "+\n */"
            }
        },
        "style_g": {
            "name": "波浪线边框",
            "python": {
                "header": "# " + "~" * 60,
                "line": "# {content}",
                "footer": "# " + "~" * 60
            },
            "java": {
                "header": "/**\n * " + "~" * 58,
                "line": " * {content}",
                "footer": " * " + "~" * 58 + "\n */"
            }
        },
        "style_h": {
            "name": "井号边框",
            "python": {
                "header": "# " + "#" * 60,
                "line": "# {content}",
                "footer": "# " + "#" * 60
            },
            "java": {
                "header": "/**\n * " + "#" * 58,
                "line": " * {content}",
                "footer": " * " + "#" * 58 + "\n */"
            }
        }
    }

    # 业务词根库（基于不同行业领域）
    BUSINESS_PREFIXES = {
        "林业": ["forest", "tree", "wood", "timber", "forestry"],
        "监测": ["monitor", "detect", "observe", "track", "sensor"],
        "管理": ["manage", "admin", "control", "handle", "govern"],
        "水土": ["soil", "water", "erosion", "conservation", "hydro"],
        "环境": ["env", "ecology", "green", "eco", "natural"],
        "物联网": ["iot", "device", "equipment", "hardware", "sensor"],
        "数据": ["data", "info", "record", "metric", "stat"],
        "系统": ["sys", "platform", "framework", "core", "base"],
        "安全": ["secure", "safe", "protect", "guard", "shield"],
        "农业": ["agri", "farm", "crop", "field", "rural"],
        "气象": ["weather", "climate", "meteo", "atmosphere", "forecast"],
        "地质": ["geo", "terrain", "land", "earth", "ground"],
        "能源": ["energy", "power", "fuel", "resource", "electric"],
        "交通": ["traffic", "transport", "vehicle", "road", "route"],
        "医疗": ["medical", "health", "clinic", "hospital", "care"],
        "教育": ["edu", "school", "learn", "teach", "academic"],
        "金融": ["finance", "bank", "fund", "invest", "asset"],
        "电商": ["ecommerce", "shop", "store", "market", "trade"],
        "物流": ["logistics", "delivery", "warehouse", "cargo", "supply"],
        "智慧": ["smart", "intelligent", "ai", "auto", "digital"]
    }

    # 动作词根
    ACTION_PREFIXES = {
        "查询": ["query", "search", "find", "fetch", "retrieve"],
        "创建": ["create", "add", "insert", "new", "build"],
        "更新": ["update", "modify", "edit", "change", "revise"],
        "删除": ["delete", "remove", "drop", "clear", "erase"],
        "分析": ["analyze", "process", "compute", "calculate", "eval"],
        "导出": ["export", "output", "extract", "dump", "save"],
        "导入": ["import", "load", "upload", "input", "restore"],
        "统计": ["stat", "count", "aggregate", "summarize", "report"],
        "验证": ["validate", "verify", "check", "confirm", "test"],
        "执行": ["execute", "run", "perform", "operate", "handle"]
    }

    def __init__(self, plan: Dict[str, Any], config: Optional[Dict[str, Any]] = None):
        """
        初始化差异化引擎

        Args:
            plan: 项目规划字典
            config: 差异化配置（可选）
        """
        self.plan = plan
        self.project_name = plan.get("project_name", "未命名项目")

        # 获取差异化配置
        self.config = config or plan.get("differentiation_config", {})

        # 生成确定性随机种子（基于项目名）
        seed_value = self.config.get("seed")
        if seed_value is None:
            seed_value = hashlib.md5(self.project_name.encode()).hexdigest()[:8]
            seed_value = int(seed_value, 16)

        self.rng = random.Random(seed_value)

        # 选择注释样式
        style_key = self.config.get("comment_style")
        if style_key is None or style_key not in self.COMMENT_STYLES:
            style_key = self.rng.choice(list(self.COMMENT_STYLES.keys()))
        self.comment_style = self.COMMENT_STYLES[style_key]

        # 提取业务前缀
        self.business_prefix = self._extract_business_prefix()

        # 获取版权信息
        self.copyright_fields = plan.get("copyright_fields", {})
        self.company_name = self.copyright_fields.get("company_name", "")
        self.copyright_year = datetime.now().year

    def _extract_business_prefix(self) -> str:
        """
        从项目名中提取业务前缀

        Returns:
            str: 业务前缀（如 forest, monitor 等）
        """
        # 如果配置中指定了前缀，直接使用
        configured_prefix = self.config.get("naming_prefix")
        if configured_prefix:
            return configured_prefix

        # 从项目名中查找匹配的业务词根
        project_name_lower = self.project_name.lower()

        # 收集所有匹配的词根
        matched_prefixes = []
        for keyword, prefixes in self.BUSINESS_PREFIXES.items():
            if keyword in self.project_name:
                matched_prefixes.extend(prefixes)

        # 如果找到匹配，随机选择一个
        if matched_prefixes:
            return self.rng.choice(matched_prefixes)

        # 默认返回通用前缀
        return self.rng.choice(["data", "biz", "core", "app", "sys"])

    def generate_file_header(self, filename: str, description: str, language: str = "python") -> str:
        """
        生成差异化的文件头注释

        Args:
            filename: 文件名
            description: 文件描述
            language: 编程语言（python 或 java）

        Returns:
            str: 格式化的文件头注释
        """
        style = self.comment_style[language]
        lines = []

        # 顶部边框
        lines.append(style["header"])

        # 项目信息
        lines.append(style["line"].format(content=f"项目: {self.project_name}"))
        lines.append(style["line"].format(content=f"模块: {filename}"))
        lines.append(style["line"].format(content=f"描述: {description}"))
        lines.append(style["line"].format(content=f"版本: {self.plan.get('version', 'V1.0.0')}"))

        # 添加版权信息（如果有）
        if self.company_name:
            lines.append(style["line"].format(content=f"版权: © {self.copyright_year} {self.company_name}"))

        # 底部边框
        lines.append(style["footer"])

        return "\n".join(lines)

    def generate_variable_name(self, action: str = "", entity: str = "", suffix: str = "") -> str:
        """
        生成业务化的变量名

        Args:
            action: 动作（如"查询"、"创建"）
            entity: 实体（如"数据"、"记录"）
            suffix: 后缀（如"service"、"repository"）

        Returns:
            str: 生成的变量名，如 forest_query_service
        """
        parts = []

        # 添加业务前缀
        parts.append(self.business_prefix)

        # 添加动作词根
        if action:
            action_words = self.ACTION_PREFIXES.get(action, [action.lower()])
            parts.append(self.rng.choice(action_words))

        # 添加实体
        if entity:
            parts.append(entity.lower())

        # 添加后缀
        if suffix:
            parts.append(suffix.lower())

        return "_".join(parts)

    def shuffle_imports(self, imports: List[str]) -> List[str]:
        """
        打乱 import 顺序（保持分组逻辑）

        Args:
            imports: import 语句列表

        Returns:
            List[str]: 打乱后的 import 列表
        """
        # 检查是否启用了打乱
        if not self.config.get("import_shuffle", True):
            return imports

        # 分组：标准库、第三方库、本地导入
        stdlib_imports = []
        thirdparty_imports = []
        local_imports = []

        for imp in imports:
            if imp.strip().startswith("from .") or imp.strip().startswith("from .."):
                local_imports.append(imp)
            elif any(lib in imp for lib in ["typing", "datetime", "json", "os", "sys", "logging", "pathlib", "re"]):
                stdlib_imports.append(imp)
            else:
                thirdparty_imports.append(imp)

        # 在各组内打乱
        self.rng.shuffle(stdlib_imports)
        self.rng.shuffle(thirdparty_imports)
        self.rng.shuffle(local_imports)

        # 合并（保持标准库、第三方、本地的顺序）
        result = []
        if stdlib_imports:
            result.extend(stdlib_imports)
        if thirdparty_imports:
            if result:
                result.append("")  # 空行分隔
            result.extend(thirdparty_imports)
        if local_imports:
            if result:
                result.append("")  # 空行分隔
            result.extend(local_imports)

        return result

    def shuffle_methods(self, methods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        打乱方法定义顺序（保留 __init__ 在前，私有方法在后）

        Args:
            methods: 方法定义列表

        Returns:
            List[Dict]: 打乱后的方法列表
        """
        # 检查是否启用了打乱
        if not self.config.get("method_order_shuffle", True):
            return methods

        # 分组
        init_methods = []
        public_methods = []
        private_methods = []

        for method in methods:
            method_name = method.get("name", "")
            if method_name == "__init__":
                init_methods.append(method)
            elif method_name.startswith("_"):
                private_methods.append(method)
            else:
                public_methods.append(method)

        # 打乱公共方法和私有方法
        self.rng.shuffle(public_methods)
        self.rng.shuffle(private_methods)

        # 合并：__init__ -> 公共方法 -> 私有方法
        return init_methods + public_methods + private_methods

    def get_random_comment_prefix(self) -> str:
        """
        获取随机的行内注释前缀

        Returns:
            str: 注释前缀，如 "业务逻辑处理"、"数据处理"等
        """
        prefixes = [
            "业务逻辑处理",
            "核心处理流程",
            "数据处理逻辑",
            "功能实现",
            "处理步骤",
            "执行流程",
            "业务规则",
            "逻辑处理"
        ]
        return self.rng.choice(prefixes)

    def get_copyright_header(self, language: str = "python") -> str:
        """
        生成版权声明头

        Args:
            language: 编程语言

        Returns:
            str: 版权声明
        """
        if not self.company_name:
            return ""

        if language == "python":
            return f"# Copyright © {self.copyright_year} {self.company_name}. All rights reserved.\n"
        else:  # java
            return f"/**\n * Copyright © {self.copyright_year} {self.company_name}. All rights reserved.\n */\n"

    def generate_verbose_docstring(self, func_name: str, params: List[str] = None, return_type: str = "void") -> str:
        """
        生成废话文学式的函数注释 (Phase 6)
        目的是增加代码文本量，降低查重率
        """
        if params is None:
            params = []

        # 废话动词库
        verbs = ["执行", "处理", "校验", "分析", "转换", "同步", "分发", "调度", "维护", "监控"]
        # 废话名词库
        nouns = ["业务逻辑", "核心数据", "上下文环境", "系统状态", "底层资源", "网络连接", "缓存一致性", "事务完整性"]
        # 废话形容词
        adjs = ["高可用", "分布式", "原子性", "幂等性", "强一致性", "低延迟", "异步", "并行"]

        # 1. 生成描述
        desc_parts = []
        desc_parts.append(f"本方法主要用于{self.rng.choice(verbs)}{self.rng.choice(adjs)}{self.rng.choice(nouns)}。")
        desc_parts.append(f"在{self.rng.choice(adjs)}架构下，通过{self.rng.choice(verbs)}机制确保{self.rng.choice(nouns)}的{self.rng.choice(nouns)}。")
        desc_parts.append(f"特别注意：此操作具有{self.rng.choice(adjs)}特征，请确保调用前已完成{self.rng.choice(nouns)}的初始化。")
        description = "".join(desc_parts)

        # 2. 生成参数说明
        param_docs = []
        for p in params:
            p_desc = f"传入的{self.rng.choice(adjs)}{self.rng.choice(nouns)}参数，用于{self.rng.choice(verbs)}后续流程"
            param_docs.append(f"@param {p} {p_desc}")

        # 3. 生成返回值说明
        return_doc = f"@return {return_type} 返回{self.rng.choice(adjs)}处理后的{self.rng.choice(nouns)}结果"

        # 4. 生成异常说明
        throws_doc = f"@throws BusinessException 当{self.rng.choice(nouns)}发生非预期{self.rng.choice(verbs)}时抛出"

        # 5. 组合
        return f"""
    /**
     * {description}
     *
     * {"".join([p + chr(10) + "     * " for p in param_docs])}
     * {return_doc}
     * {throws_doc}
     */
"""

    def apply_comment_irregularity(self, code: str, language: str = "python") -> str:
        """
        应用注释不规则性引擎，让代码更接近真实项目

        策略:
        - 25% 方法不写注释
        - 5% 注释含"笔误"（的→得，登录→登陆）
        - 15% 使用非正式表达
        - 随机插入真实风格注释

        Args:
            code: 原始代码
            language: 编程语言

        Returns:
            处理后的代码
        """
        # 笔误替换表
        TYPO_MAP = {
            "的": "得",
            "登录": "登陆",
            "帐号": "账号",
            "做": "作",
            "必须": "必需",
            "以及": "已及",
            "是否": "是不是",
        }

        # 非正式表达库
        INFORMAL_COMMENTS = {
            "python": [
                "# 这里有点hack，但能跑",
                "# 别问为什么，问就是历史遗留",
                "# 临时改的，有空再优化",
                "# 这段逻辑很绕，小心修改",
                "# 上游接口太奇怪了",
                "# 产品要求的，别删",
                "# 测试环境用的，生产别开",
                "# 这个值是试出来的",
                "# 不知道为什么要这样，但去掉就报错",
                "# 后面有人优化一下这里",
            ],
            "java": [
                "// 这里有点hack，但能跑",
                "// 别问为什么，问就是历史遗留",
                "// 临时改的，有空再优化",
                "// 这段逻辑很绕，小心修改",
                "// 上游接口太奇怪了",
                "// 产品要求的，别删",
                "// 测试环境用的，生产别开",
                "// 这个值是试出来的",
                "// 不知道为什么要这样，但去掉就报错",
                "// 后面有人优化一下这里",
            ]
        }

        lines = code.split('\n')
        new_lines = []

        lang_key = "python" if language.lower() == "python" else "java"
        informal_comments = INFORMAL_COMMENTS.get(lang_key, INFORMAL_COMMENTS["python"])

        # 检测注释行的模式
        comment_pattern = r'^\s*#' if lang_key == "python" else r'^\s*//'
        docstring_pattern = r'^\s*["\']' if lang_key == "python" else r'^\s*/\*'

        in_docstring = False
        method_count = 0

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 检测 docstring 开始/结束
            if lang_key == "python":
                if '"""' in stripped or "'''" in stripped:
                    count = stripped.count('"""') + stripped.count("'''")
                    if count == 1:
                        in_docstring = not in_docstring
                    # 如果同一行有两个，则不改变状态

            # 检测方法定义
            is_method_def = False
            if lang_key == "python" and stripped.startswith("def "):
                is_method_def = True
                method_count += 1
            elif lang_key == "java" and re.match(r'(public|private|protected)\s+', stripped):
                is_method_def = True
                method_count += 1

            # 处理注释行 - 应用笔误
            if re.match(comment_pattern, stripped) and not in_docstring:
                # 5% 概率添加笔误
                if self.rng.random() < 0.05:
                    for correct, typo in TYPO_MAP.items():
                        if correct in line and self.rng.random() < 0.5:
                            line = line.replace(correct, typo, 1)
                            break

            new_lines.append(line)

            # 15% 概率在方法后插入非正式注释
            if is_method_def and self.rng.random() < 0.15:
                indent = len(line) - len(line.lstrip())
                if lang_key == "python":
                    indent += 4
                else:
                    indent += 8
                informal = self.rng.choice(informal_comments)
                new_lines.append(" " * indent + informal)

        return "\n".join(new_lines)

    def remove_some_comments(self, code: str, language: str = "python", removal_rate: float = 0.25) -> str:
        """
        移除部分方法的注释，模拟真实项目中注释不完整的情况

        Args:
            code: 原始代码
            language: 编程语言
            removal_rate: 移除比例 (默认25%)

        Returns:
            处理后的代码
        """
        lines = code.split('\n')
        new_lines = []

        lang_key = "python" if language.lower() == "python" else "java"

        # Python 场景下移除 docstring 容易误删结束引号，导致整文件语法失效。
        # 这里保守处理：不做 docstring 删除，仅保留后续注释不规则增强。
        if lang_key == "python":
            return code

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 检测 Python docstring
            if lang_key == "python" and (stripped.startswith('"""') or stripped.startswith("'''")):
                # 25% 概率跳过整个 docstring
                if self.rng.random() < removal_rate:
                    quote = stripped[:3]
                    # 查找 docstring 结束
                    if stripped.endswith(quote) and len(stripped) > 3:
                        # 单行 docstring，跳过
                        i += 1
                        continue
                    else:
                        # 多行 docstring，找到结束位置
                        i += 1
                        while i < len(lines) and quote not in lines[i]:
                            i += 1
                        i += 1  # 跳过结束行
                        continue

            # 检测 Java 块注释
            if lang_key == "java" and stripped.startswith("/**"):
                if self.rng.random() < removal_rate:
                    # 跳过整个块注释
                    while i < len(lines) and "*/" not in lines[i]:
                        i += 1
                    i += 1  # 跳过 */ 行
                    continue

            new_lines.append(line)
            i += 1

        return "\n".join(new_lines)
