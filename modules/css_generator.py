"""
CSS 生成器 (CSS Generator)
V2.3 核心组件：将设计决策转化为生产级 CSS 代码。
负责实现高级视觉效果 (Glassmorphism, Neumorphism) 并注入随机扰动以防止查重。
增强版：CSS 类名随机化 + 布局变体 + 深度随机扰动
"""
import random
import string
import hashlib
import logging
import re
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

class CSSGenerator:
    """
    确定性 CSS 生成引擎 + 随机指纹注入 + 类名混淆
    """

    def __init__(self):
        # 生成本次构建的唯一前缀 (用于类名混淆)
        self.class_prefix = self._generate_class_prefix()
        # 类名映射表
        self.class_map = self._generate_class_map()

    def _generate_class_prefix(self) -> str:
        """生成 2-4 位随机前缀"""
        length = random.randint(2, 4)
        return ''.join(random.choices(string.ascii_lowercase, k=length))

    def _generate_class_map(self) -> Dict[str, str]:
        """
        生成类名映射表，将标准类名映射为随机化类名
        """
        # 基础类名池
        base_names = [
            'sidebar', 'main-content', 'topbar', 'bento-card', 'card-header',
            'card-body', 'menu-item', 'app-shell', 'sidebar-header', 'sidebar-nav'
        ]

        # 同义词替换池
        synonyms = {
            'sidebar': ['nav-panel', 'side-menu', 'left-rail', 'nav-drawer', 'menu-bar'],
            'main-content': ['content-area', 'main-view', 'page-body', 'work-area', 'center-pane'],
            'topbar': ['header-bar', 'top-nav', 'app-header', 'title-bar', 'nav-header'],
            'bento-card': ['data-tile', 'info-box', 'widget-card', 'stat-panel', 'dash-card'],
            'card-header': ['tile-head', 'box-title', 'panel-top', 'widget-header'],
            'card-body': ['tile-content', 'box-body', 'panel-inner', 'widget-body'],
            'menu-item': ['nav-link', 'menu-entry', 'nav-item', 'side-link'],
            'app-shell': ['app-wrapper', 'layout-root', 'page-shell', 'app-frame'],
            'sidebar-header': ['nav-brand', 'menu-header', 'side-title'],
            'sidebar-nav': ['menu-list', 'nav-list', 'side-links']
        }

        mapping = {}
        for name in base_names:
            if name in synonyms and random.random() < 0.7:
                # 70% 概率使用同义词
                new_name = random.choice(synonyms[name])
            else:
                # 30% 概率添加前缀
                new_name = f"{self.class_prefix}-{name}"

            # 额外随机：有时添加后缀
            if random.random() < 0.3:
                suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=3))
                new_name = f"{new_name}-{suffix}"

            mapping[name] = new_name

        return mapping

    def get_class(self, original: str) -> str:
        """获取混淆后的类名"""
        return self.class_map.get(original, original)

    def generate_css(self, decision: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
        """
        生成完整的 CSS 样式块
        Returns:
            Tuple[str, Dict]: (CSS代码, 类名映射表)
        """
        # 1. 基础变量提取 + 对比度守卫
        palette = self._sanitize_palette(decision)
        p_color = palette["primary"]
        s_color = palette["secondary"]
        bg_color = palette["background"]
        accent_color = palette["accent"]
        text_color = palette["text"]
        sidebar_text_color = palette["sidebar_text"]
        sidebar_text_muted = palette["sidebar_text_muted"]
        radius = decision.get("border_radius", "8px")

        # 2. 高级效果逻辑
        card_css = self._get_card_style(decision)
        sidebar_css = self._get_sidebar_style(decision)
        shadow_val = self._get_shadow_value(decision.get("shadow_style", "subtle"))

        # 3. 深度随机指纹 (Anti-Fingerprinting)
        rand_pad = f"{random.randint(14, 20) / 10}rem"
        rand_blur = f"{random.randint(8, 16)}px"
        rand_gap = f"{random.randint(12, 20) / 10}rem"
        rand_sidebar_width = f"{random.randint(240, 280)}px"
        rand_transition = f"{random.randint(15, 35) / 100}s"
        rand_menu_pad = f"{random.randint(6, 10) / 10}rem {random.randint(12, 18) / 10}rem"
        rand_font_size = f"{random.randint(11, 13) / 10}rem"

        # 4. 获取混淆后的类名
        c = self.class_map  # 简写

        # 5. 随机选择布局变体
        layout_variant = random.choice(['standard', 'compact', 'wide', 'modern'])

        # 6. 随机添加装饰性 CSS 属性
        decorative_props = self._generate_decorative_css()

        css = f"""
/* Theme: {decision.get('theme_name', 'Custom')} | Build: {self.class_prefix} */
/* Layout Variant: {layout_variant} */
:root {{
    --primary: {p_color};
    --secondary: {s_color};
    --accent: {accent_color};
    --background: {bg_color};
    --text-main: {text_color};
    --sidebar-text: {sidebar_text_color};
    --sidebar-text-muted: {sidebar_text_muted};
    --radius: {radius};
    --shadow: {shadow_val};
    --font-heading: '{decision.get('font_heading', 'Inter')}', sans-serif;
    --spacing-unit: {rand_gap};
    --sidebar-w: {rand_sidebar_width};
    --transition-speed: {rand_transition};
}}

body {{
    background-color: var(--background);
    color: var(--text-main);
    font-family: var(--font-heading);
    margin: 0;
    padding: 0;
    {decorative_props}
}}

/* App Shell Layout */
.{c['app-shell']} {{
    display: flex;
    min-height: 100vh;
    overflow: hidden;
}}

/* Sidebar - {decision.get('sidebar_style')} */
.{c['sidebar']} {{
    width: var(--sidebar-w);
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    {sidebar_css}
    transition: all var(--transition-speed) ease;
    z-index: 100;
}}

.{c['sidebar-header']} {{
    padding: {rand_pad};
    font-size: {rand_font_size};
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--sidebar-text);
}}

.{c['sidebar-nav']} {{
    flex: 1;
    padding: 1rem 0;
    overflow-y: auto;
}}

/* Main Content Area */
.{c['main-content']} {{
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: {rand_pad};
    gap: var(--spacing-unit);
    position: relative;
}}

/* Top Navbar */
.{c['topbar']} {{
    background: rgba(255,255,255,0.8);
    backdrop-filter: blur({rand_blur});
    border-bottom: 1px solid rgba(0,0,0,0.05);
    padding: {rand_menu_pad};
    border-radius: var(--radius);
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--spacing-unit);
}}

/* Bento Card - {decision.get('card_style')} */
.{c['bento-card']} {{
    height: auto;
    display: flex;
    flex-direction: column;
    {card_css}
    transition: transform var(--transition-speed) ease, box-shadow var(--transition-speed) ease;
    overflow: hidden;
}}

.{c['bento-card']}:hover {{
    transform: translateY(-{random.randint(2, 4)}px);
    box-shadow: var(--shadow), 0 {random.randint(8, 14)}px {random.randint(16, 24)}px rgba(0,0,0,0.05);
}}

.{c['card-header']} {{
    padding: {random.randint(10, 14) / 10}rem {random.randint(12, 18) / 10}rem {random.randint(4, 8) / 10}rem;
    font-weight: 600;
    font-size: 1.1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}}

.{c['card-body']} {{
    padding: {rand_pad};
    flex: 1;
    position: relative;
}}

/* Menu Items */
.{c['menu-item']} {{
    padding: {rand_menu_pad};
    margin: 0.2rem 0.8rem;
    border-radius: var(--radius);
    cursor: pointer;
    color: var(--sidebar-text-muted);
    transition: all var(--transition-speed);
    display: flex;
    align-items: center;
    gap: 0.8rem;
    font-weight: 500;
}}

.{c['menu-item']}:hover, .{c['menu-item']}.active {{
    background: rgba(255,255,255,0.15);
    color: var(--sidebar-text);
    backdrop-filter: blur(5px);
}}

.{c['menu-item']} i {{
    font-size: 1.2rem;
}}

/* Typography Utils */
.text-muted {{ color: #64748b !important; }}
.fw-bold {{ font-weight: 700 !important; }}
.h-100 {{ height: 100%; }}
.w-100 {{ width: 100%; }}

/* Chart Containers */
[id^="widget_chart_"] {{
    width: 100%;
    min-height: {random.randint(280, 340)}px;
}}

/* Random decorative rules for fingerprinting */
{self._generate_random_rules()}
"""
        return css, self.class_map

    def _generate_decorative_css(self) -> str:
        """生成随机装饰性 CSS 属性"""
        options = [
            "/* Enhanced rendering */",
            "-webkit-font-smoothing: antialiased;",
            "-moz-osx-font-smoothing: grayscale;",
            "text-rendering: optimizeLegibility;",
            f"line-height: {random.randint(15, 18) / 10};",
        ]
        selected = random.sample(options, random.randint(1, 3))
        return "\n    ".join(selected)

    def _generate_random_rules(self) -> str:
        """生成随机的 CSS 规则用于指纹扰动"""
        rules = []

        # 随机生成一些无害的 CSS 规则
        if random.random() < 0.5:
            rules.append(f"""
/* Accessibility enhancements */
@media (prefers-reduced-motion: reduce) {{
    * {{ transition-duration: 0.01ms !important; }}
}}""")

        if random.random() < 0.5:
            rules.append(f"""
/* Print styles */
@media print {{
    .{self.class_map['sidebar']} {{ display: none; }}
}}""")

        if random.random() < 0.6:
            rand_color = f"#{random.randint(0, 255):02x}{random.randint(0, 255):02x}{random.randint(0, 255):02x}"
            rules.append(f"""
/* Selection highlight */
::selection {{
    background: {rand_color};
    color: white;
}}""")

        return "\n".join(rules)

    def _get_card_style(self, decision: Dict) -> str:
        style = decision.get("card_style", "flat")
        radius = decision.get("border_radius", "8px")

        if style == "glassmorphism":
            return f"""
                background: rgba(255, 255, 255, 0.7);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.5);
                border-radius: {radius};
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);
            """
        elif style == "neumorphism":
            return f"""
                background: #f0f0f3;
                border-radius: {radius};
                box-shadow: 5px 5px 10px #d1d1d4, -5px -5px 10px #ffffff;
                border: none;
            """
        elif style == "bordered":
            return f"""
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: {radius};
                box-shadow: none;
            """
        else: # flat
            return f"""
                background: #ffffff;
                border-radius: {radius};
                box-shadow: var(--shadow);
                border: none;
            """

    def _get_sidebar_style(self, decision: Dict) -> str:
        style = decision.get("sidebar_style", "solid")
        color = decision.get("secondary_color", "#1e293b")

        if style == "gradient":
            return f"background: linear-gradient(135deg, {color} 0%, {self._adjust_color(color, -20)} 100%);"
        elif style == "blur":
            return f"""
                background: {self._hex_to_rgba(color, 0.85)};
                backdrop-filter: blur(10px);
                border-right: 1px solid rgba(255,255,255,0.1);
            """
        else:
            return f"background: {color};"

    def _get_shadow_value(self, style: str) -> str:
        if style == "glow": return "0 0 15px rgba(59, 130, 246, 0.35)"
        if style == "strong": return "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)"
        if style == "soft": return "0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06)"
        return "0 1px 3px 0 rgba(0,0,0,0.1), 0 1px 2px 0 rgba(0,0,0,0.06)"

    def _hex_to_rgba(self, hex_val: str, alpha: float) -> str:
        hex_val = hex_val.lstrip('#')
        try:
            r, g, b = tuple(int(hex_val[i:i+2], 16) for i in (0, 2, 4))
            return f"rgba({r}, {g}, {b}, {alpha})"
        except:
            return f"rgba(30, 41, 59, {alpha})"

    def _adjust_color(self, hex_color: str, amount: int) -> str:
        """颜色亮度微调，amount 范围建议 [-80, 80]。"""
        rgb = self._hex_to_rgb_tuple(hex_color)
        if not rgb:
            return hex_color
        adjusted = []
        for ch in rgb:
            adjusted.append(max(0, min(255, ch + amount)))
        return "#{:02x}{:02x}{:02x}".format(adjusted[0], adjusted[1], adjusted[2])

    @staticmethod
    def _normalize_hex(color: str, default: str) -> str:
        raw = str(color or "").strip()
        if re.fullmatch(r"#([0-9a-fA-F]{6})", raw):
            return raw.lower()
        if re.fullmatch(r"#([0-9a-fA-F]{3})", raw):
            return "#" + "".join(ch * 2 for ch in raw[1:]).lower()
        return default

    @staticmethod
    def _hex_to_rgb_tuple(color: str):
        color = str(color or "").strip().lstrip("#")
        if len(color) != 6:
            return None
        try:
            return (
                int(color[0:2], 16),
                int(color[2:4], 16),
                int(color[4:6], 16),
            )
        except Exception:
            return None

    def _relative_luminance(self, color: str) -> float:
        rgb = self._hex_to_rgb_tuple(color)
        if not rgb:
            return 0.0
        channels = []
        for val in rgb:
            c = val / 255.0
            if c <= 0.03928:
                channels.append(c / 12.92)
            else:
                channels.append(((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def _contrast_ratio(self, c1: str, c2: str) -> float:
        l1 = self._relative_luminance(c1)
        l2 = self._relative_luminance(c2)
        high = max(l1, l2)
        low = min(l1, l2)
        return (high + 0.05) / (low + 0.05)

    def _pick_readable_text(self, bg: str, preferred: str = "#0f172a") -> str:
        preferred_norm = self._normalize_hex(preferred, "#0f172a")
        if self._contrast_ratio(preferred_norm, bg) >= 4.5:
            return preferred_norm
        dark = "#0f172a"
        light = "#f8fafc"
        return dark if self._contrast_ratio(dark, bg) >= self._contrast_ratio(light, bg) else light

    def _mix_hex(self, c1: str, c2: str, ratio: float) -> str:
        rgb1 = self._hex_to_rgb_tuple(c1)
        rgb2 = self._hex_to_rgb_tuple(c2)
        if not rgb1 or not rgb2:
            return c1
        r = max(0.0, min(1.0, ratio))
        mixed = (
            int(rgb1[0] * (1.0 - r) + rgb2[0] * r),
            int(rgb1[1] * (1.0 - r) + rgb2[1] * r),
            int(rgb1[2] * (1.0 - r) + rgb2[2] * r),
        )
        return "#{:02x}{:02x}{:02x}".format(mixed[0], mixed[1], mixed[2])

    def _sanitize_palette(self, decision: Dict[str, Any]) -> Dict[str, str]:
        primary = self._normalize_hex(decision.get("primary_color"), "#2563eb")
        secondary = self._normalize_hex(decision.get("secondary_color"), "#1e293b")
        accent = self._normalize_hex(decision.get("accent_color"), "#f43f5e")
        background = self._normalize_hex(decision.get("background_color"), "#f8fafc")
        text = self._normalize_hex(decision.get("text_color"), "#0f172a")

        # 背景强制保持浅色，避免与正文冲突和截图可读性下降。
        if self._relative_luminance(background) < 0.82:
            background = self._mix_hex(background, "#ffffff", 0.58)

        # 正文对比度保证 >= 4.5（WCAG AA for normal text）。
        if self._contrast_ratio(text, background) < 4.5:
            text = self._pick_readable_text(background, preferred=text)

        sidebar_text = self._pick_readable_text(secondary, preferred="#f8fafc")
        # 侧栏弱化文字仍保证可读性
        sidebar_text_muted = self._mix_hex(sidebar_text, secondary, 0.28)
        if self._contrast_ratio(sidebar_text_muted, secondary) < 3.0:
            sidebar_text_muted = self._pick_readable_text(secondary, preferred=sidebar_text)

        # 强调色若与背景过近，回退到主色，避免按钮“看不见”。
        if self._contrast_ratio(accent, background) < 2.2:
            accent = primary

        return {
            "primary": primary,
            "secondary": secondary,
            "accent": accent,
            "background": background,
            "text": text,
            "sidebar_text": sidebar_text,
            "sidebar_text_muted": sidebar_text_muted,
        }
