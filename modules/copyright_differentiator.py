"""
软著平台字段差异化增强器 (Enhanced V2.1)
对开发目的、主要功能等关键文本进行深度重写，避免"套话"和雷同
"""
import random
import hashlib
import re
from typing import Dict, Any, List

class CopyrightFieldsDifferentiator:
    """软著平台字段差异化器 (Anti-Duplication Edition)"""

    # =========================================================================
    # 1. 词汇库 (Vocabulary)
    # =========================================================================

    # 高频套话 -> 替换词库 (避免使用过于通用的词)
    BUZZWORD_REPLACEMENTS = {
        "信息化": ["数字化", "数据化", "业务线上化", "信息互联", "数字转型"],
        "智能化": ["自动化", "智能辅助", "智慧", "自动处理", "辅助决策"],
        "数字化": ["电子化", "数据驱动", "数智化", "无纸化"],
        "平台": ["系统", "环境", "中心", "工作台", "服务端"],
        "解决方案": ["应用系统", "支撑工具", "业务平台", "管理软件"],
        "全方位": ["多维度", "系统性", "整体", "端到端"],
        "高效": ["快速", "敏捷", "实时", "高吞吐"],
        "便捷": ["易用", "灵活", "直观", "简便"],
    }

    # 行业同义词 (用于扩充 industry 字段)
    INDUSTRY_SYNONYMS = {
        "医疗": ["临床诊疗", "健康服务", "医护工作", "医疗卫生"],
        "教育": ["教学管理", "教育培训", "校园服务", "教务工作"],
        "金融": ["金融服务", "资金管理", "信贷业务", "投资理财"],
        "制造": ["工业生产", "加工制造", "生产运营", "供应链"],
        "物流": ["仓储运输", "配送服务", "供应链管理", "物流调度"],
        "电商": ["在线交易", "网络零售", "电子上午", "数字营销"],
        "政务": ["行政办公", "公共服务", "政务处理", "行政管理"],
        "企业": ["公司运营", "机构管理", "商业经营", "组织协同"],
    }

    # =========================================================================
    # 2. 模板库 (Templates)
    # =========================================================================

    # 开发目的 - 视角A: 问题导向 (Problem-Oriented)
    PURPOSE_A = [
        "针对{industry}过程中存在的{pain_point}问题，本软件通过{tech_method}，实现了{core_value}。",
        "鉴于传统{industry}模式下{pain_point}的局限性，开发本系统以达成{core_value}的目标。",
        "为克服{industry}场景中{pain_point}的难点，设计并实现了本软件，旨在提供{core_value}。",
    ]

    # 开发目的 - 视角B: 效率/价值导向 (Value-Oriented)
    PURPOSE_B = [
        "为进一步提升{industry}的作业效率，本系统致力于实现{core_value}，并优化{process}流程。",
        "本软件旨在构建高效的{industry}环境，通过优化{process}，切实提高{core_value}。",
        "立足于{industry}的实际业务需求，本软件以提升{core_value}为核心，整合了{process}功能。",
    ]

    # 开发目的 - 视角C: 技术驱动导向 (Tech-Driven)
    PURPOSE_C = [
        "应用{tech_stack}技术架构，构建{industry}管理体系，以支撑{process}的稳定运行。",
        "结合当前成熟的{tech_stack}技术，开发本{industry}软件，旨在为用户提供稳定的{process}服务。",
        "采用{tech_stack}设计理念，实现{industry}数据的集中管理，从而达成{core_value}。",
    ]

    # 开发目的 - 视角D: 极简风格 (Minimalist)
    PURPOSE_D = [
        "本软件主要用于{industry}，核心解决{pain_point}问题。",
        "专为{industry}设计，通过{process}功能，满足用户对{core_value}的需求。",
        "一款面向{industry}的应用软件，旨在实现{process}的{replacement_digital}管理。",
    ]

    # 主要功能 - 列表引导语
    FUNC_PREFIXES = [
        "软件包含以下核心模块：",
        "本系统具备多项关键能力，具体如下：",
        "主要功能涵盖了业务全流程，包括：",
        "系统功能结构主要由以下部分组成：",
        "本软件重点实现了以下业务功能：",
        "" # 空前缀
    ]

    # 技术特点 - 句式结构
    TECH_STRUCTURES = [
        "系统采用{arch}架构，基于{lang}语言开发，具备{feature}特性。",
        "技术栈选用{lang}与{arch}组合，重点强化了{feature}能力。",
        "基于{arch}设计思想，使用{lang}进行实现，确保了系统的{feature}。",
        "本软件在技术上采用{arch}模式，利用{lang}的高效特性，实现了{feature}。",
    ]

    def __init__(self, seed: str = None):
        """初始化差异化器"""
        if seed:
            seed_int = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
            self.rng = random.Random(seed_int)
        else:
            self.rng = random.Random()

    def _replace_buzzwords(self, text: str) -> str:
        """替换高频套话"""
        if not text:
            return text

        for buzzword, replacements in self.BUZZWORD_REPLACEMENTS.items():
            if buzzword in text:
                # 50% 概率进行替换，保留一定原词
                if self.rng.random() > 0.5:
                    new_word = self.rng.choice(replacements)
                    text = text.replace(buzzword, new_word, 1) # 只替换第一个，避免语义崩坏
        return text

    def _extract_keywords(self, text: str) -> Dict[str, str]:
        """从原文中简单的提取/猜测关键词 (模拟NLP)"""
        # 默认值
        keywords = {
            "pain_point": "数据分散且管理困难",
            "core_value": "业务流程的规范化",
            "process": "数据处理",
            "tech_method": "现代信息技术手段",
            "replacement_digital": "数字化"
        }

        # 简单规则提取
        if "效率" in text:
            keywords["core_value"] = "工作效率的显著提升"
            keywords["pain_point"] = "人工操作效率低下"
        elif "安全" in text:
            keywords["core_value"] = "数据资产的安全保障"
            keywords["pain_point"] = "传统方式存在安全隐患"
        elif "决策" in text:
            keywords["core_value"] = "科学的辅助决策支持"
            keywords["pain_point"] = "缺乏数据支撑"

        return keywords

    def rewrite_purpose(self, original: str, industry: str = "业务") -> str:
        """
        深度改写开发目的
        策略：完全抛弃原文结构，只保留行业属性，使用新模板生成
        """
        # 1. 扩展行业描述
        industry_term = industry
        # 尝试匹配行业同义词
        for key, synonyms in self.INDUSTRY_SYNONYMS.items():
            if key in industry:
                industry_term = self.rng.choice(synonyms)
                break

        # 2. 提取/生成上下文关键词
        kw = self._extract_keywords(original)

        # 3. 随机选择一种视角模板
        category = self.rng.choice(["A", "B", "C", "D"])
        if category == "A":
            template = self.rng.choice(self.PURPOSE_A)
        elif category == "B":
            template = self.rng.choice(self.PURPOSE_B)
        elif category == "C":
            template = self.rng.choice(self.PURPOSE_C)
        else:
            template = self.rng.choice(self.PURPOSE_D)

        # 4. 填充模板参数
        # 随机化技术栈词汇
        tech_stacks = ["B/S", "微服务", "分布式", "模块化", "云原生"]

        result = template.format(
            industry=industry_term,
            pain_point=kw["pain_point"],
            core_value=kw["core_value"],
            process=kw["process"],
            tech_method=kw["tech_method"],
            tech_stack=self.rng.choice(tech_stacks),
            replacement_digital=kw["replacement_digital"]
        )

        # 5. 最后做一次禁词替换
        return self._replace_buzzwords(result)

    def rewrite_main_functions(self, original: str) -> str:
        """
        改写主要功能
        策略：识别列表结构 -> 打乱顺序 -> 变换连接词 -> 替换高频词
        """
        # 1. 尝试拆解功能点
        # 常见的分割符：1. 2. 3. 或 (1) (2) 或 ;
        # 统一替换分号
        text = original.replace("；", ";").replace("。", ";")

        # 尝试按序号拆分
        import re
        # 匹配 "1." 或 "1、" 或 "(1)" 开头的段落
        segments = re.split(r'(?:\d+[\.、]|\(\d+\))', text)
        segments = [s.strip(" ;") for s in segments if len(s.strip()) > 5] # 过滤过短的碎片

        if not segments:
            # 如果没有序号，尝试按分号拆分
            segments = [s.strip() for s in text.split(";") if len(s.strip()) > 5]

        if not segments:
            # 如果还是拆不出来，就直接做词汇替换
            return self._replace_buzzwords(original)

        # 2. 打乱顺序 (保留第一个，通常第一个是总述或最重要的)
        if len(segments) > 2:
            first = segments[0]
            rest = segments[1:]
            self.rng.shuffle(rest)
            segments = [first] + rest

        # 3. 重组文本
        prefix = self.rng.choice(self.FUNC_PREFIXES)

        # 随机选择一种列表风格
        style = self.rng.choice(["number", "semicolon", "paragraph"])

        result = ""
        if style == "number":
            lines = [f"{i+1}、{seg}" for i, seg in enumerate(segments)]
            result = prefix + "\n" + "\n".join(lines)
        elif style == "semicolon":
            result = prefix + "; ".join(segments) + "。"
        else:
            # 段落式：用连接词串起来
            connectors = ["首先", "其次", "此外", "同时", "最后"]
            sentences = []
            for i, seg in enumerate(segments):
                conn = connectors[min(i, len(connectors)-1)] if i > 0 else ""
                # 去掉 seg 结尾的标点
                seg = seg.strip(";,。")
                if conn:
                    sentences.append(f"{conn}，{seg}")
                else:
                    sentences.append(seg)
            result = prefix + "。".join(sentences) + "。"

        # 4. 词汇替换
        return self._replace_buzzwords(result)

    def rewrite_technical_features(self, original: str) -> str:
        """
        改写技术特点
        """
        # 如果原文很短，可能是生成的占位符，直接重新生成
        if len(original) < 20:
            arch = self.rng.choice(["B/S", "前后端分离", "微服务", "分层"])
            lang = self.rng.choice(["Python", "Java", "Go", "Node.js"])
            feature = self.rng.choice(["高可用性", "易扩展性", "数据安全性", "并发处理能力"])
            template = self.rng.choice(self.TECH_STRUCTURES)
            return template.format(arch=arch, lang=lang, feature=feature)

        # 否则进行词汇替换和简单修饰
        text = self._replace_buzzwords(original)

        # 随机添加前缀修饰
        if not any(text.startswith(x) for x in ["本", "该", "系统"]):
             prefix = self.rng.choice(["本系统", "该软件", "平台"])
             text = prefix + text

        return text
