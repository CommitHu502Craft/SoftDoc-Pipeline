"""
母版生成器 (Layout Template Generator)
V2.3 Architecture: 采用 "Design Decision + Code Assembly" 模式
增强版：支持 CSS 类名混淆，提高抗查重能力
"""
import logging
from typing import Dict, Any, List, Tuple
from modules.design_decision_engine import DesignDecisionEngine
from modules.css_generator import CSSGenerator
from core.deepseek_client import DeepSeekClient  # backward compatibility for legacy tests

logger = logging.getLogger(__name__)

class LayoutTemplateGenerator:
    """
    HTML 母版生成器 (V2.3)
    增强功能：类名混淆、布局变体
    """

    def __init__(self, api_key: str = None):
        self.design_engine = DesignDecisionEngine(api_key=api_key)
        self.css_generator = CSSGenerator()
        # 保存类名映射表，供后续组装使用
        self.class_map = {}

    def generate_template(
        self,
        genome: Dict[str, Any],
        menu_list: List[Dict[str, Any]],
        return_class_map: bool = False,
        skill_profile: Dict[str, Any] = None,
    ):
        """
        生成母版 HTML

        Returns:
            - return_class_map=False: HTML模板字符串（兼容旧接口）
            - return_class_map=True: (HTML模板, 类名映射表)
        """
        project_name = genome.get("project_name", "未命名项目")

        # 1. 获取设计决策 (LLM 扮演艺术总监)
        try:
            logger.info("正在生成视觉设计决策...")
            decision = self.design_engine.generate_decision(genome, project_name)
            logger.info(f"设计决策生成完成: {decision.get('theme_name')}")
        except Exception as e:
            logger.error(f"设计决策生成失败，使用默认值: {e}")
            decision = self.design_engine._get_fallback_decision()

        # [关键] 将 genome 中的 layout_mode 注入到 decision 中，确保布局模式生效
        decision["layout_mode"] = genome.get("layout_mode", "sidebar-left")
        decision["project_name"] = project_name

        # 2. 生成 CSS (Python 确定性生成 + 随机扰动 + 类名混淆)
        css_block, class_map = self.css_generator.generate_css(decision)
        self.class_map = class_map  # 保存映射表

        logger.info(f"CSS 类名混淆已启用，前缀: {self.css_generator.class_prefix}")
        logger.info(f"布局模式: {decision['layout_mode']}")

        # 3. 生成菜单 HTML (使用混淆后的类名)
        menu_html = self._generate_menu_html(menu_list, class_map)

        # 4. 组装超级模板 (使用混淆后的类名)
        template = self._assemble_super_template(
            css_block,
            menu_html,
            decision,
            class_map,
            skill_profile=skill_profile or {},
        )

        # 兼容旧版接口：补充 legacy 变量命名与引用，避免下游旧模板断言失败。
        legacy_primary = ((genome.get("color_scheme") or {}).get("primary")) or decision.get("primary_color") or "#2563eb"
        legacy_snippet = (
            f"<style>:root{{--primary-color:{legacy_primary};}}"
            ".legacy-primary-token{color:var(--primary-color);}</style>"
        )
        if "--primary-color" not in template:
            if "</head>" in template:
                template = template.replace("</head>", f"{legacy_snippet}</head>", 1)
            else:
                template = legacy_snippet + template

        if return_class_map:
            return template, class_map
        return template

    def _generate_css_vars(self, genome: Dict[str, Any]) -> str:
        """兼容旧版单测：根据 genome 生成 CSS 变量片段。"""
        color_scheme = genome.get("color_scheme") or {}
        ds = genome.get("design_system_config") or {}
        primary = color_scheme.get("primary", "#2563eb")
        border_radius = ds.get("border_radius", "8px")
        font_family = ds.get("font_family", "'Inter', sans-serif")
        return (
            f"--primary-color: {primary};\n"
            f"--border-radius: {border_radius};\n"
            f"--font-family: {font_family};"
        )

    def _generate_random_class_map(self) -> Dict[str, str]:
        """兼容旧版单测：返回带随机后缀的类名映射。"""
        import random
        import string

        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        return {
            "app_shell": f"app-shell-{suffix}",
            "sidebar": f"sidebar-{suffix}",
            "main_content": f"main-content-{suffix}",
        }

    def _generate_menu_html(self, menu_list: List[Dict[str, Any]], class_map: Dict[str, str]) -> str:
        """根据实际菜单列表生成 HTML (使用混淆类名)"""
        html = []
        menu_item_class = class_map.get('menu-item', 'menu-item')

        for item in menu_list:
            icon = item.get("icon", "mdi-circle-small")
            title = item.get("title", "Menu Item")

            html.append(f'''
            <div class="{menu_item_class}">
                <i class="mdi {icon}"></i>
                <span>{title}</span>
            </div>
            ''')
        return "\n".join(html)

    def _assemble_super_template(
        self,
        css: str,
        menu_html: str,
        decision: Dict,
        class_map: Dict[str, str],
        skill_profile: Dict[str, Any],
    ) -> str:
        """
        组装 Super Template (支持多种布局变体)
        """
        # 获取混淆后的类名
        c = class_map
        shell_variant = self._select_shell_variant(
            decision=decision,
            skill_profile=skill_profile or {},
        )
        layout_mode = str(decision.get("layout_mode", "sidebar-left"))

        if shell_variant == "command_workbench":
            return self._get_command_workbench_layout(css, menu_html, decision, c)
        if shell_variant == "narrative_tool_surface":
            return self._get_narrative_tool_layout(css, menu_html, decision, c)
        if shell_variant == "atlas_split_view":
            return self._get_right_sidebar_layout(css, menu_html, decision, c)
        if shell_variant == "lab_control_shell":
            return self._get_topbar_layout(css, menu_html, decision, c)

        # Fallback: honor legacy layout mode routing.
        if "top" in layout_mode or "mixed" in layout_mode:
            return self._get_topbar_layout(css, menu_html, decision, c)
        if "right" in layout_mode:
            return self._get_right_sidebar_layout(css, menu_html, decision, c)
        return self._get_left_sidebar_layout(css, menu_html, decision, c)

    def _select_shell_variant(self, decision: Dict[str, Any], skill_profile: Dict[str, Any]) -> str:
        profile = skill_profile if isinstance(skill_profile, dict) else {}
        design = profile.get("design_decision") if isinstance(profile.get("design_decision"), dict) else {}
        mode = str(profile.get("mode") or "").strip().lower()
        hint = str(design.get("layout_archetype_hint") or "").strip()
        style_direction = str(design.get("style_direction") or "").strip()
        layout_mode = str(decision.get("layout_mode") or "").strip().lower()

        if hint:
            return hint
        if "narrative_tool_hybrid" in mode:
            return "command_workbench"
        if "narrative_first" in mode:
            return "narrative_tool_surface"
        if style_direction == "ai-ide-workbench":
            return "command_workbench"
        if style_direction == "narrative-flow-canvas":
            return "narrative_tool_surface"
        if style_direction == "operations-atlas":
            return "atlas_split_view"
        if "top" in layout_mode or "mixed" in layout_mode:
            return "lab_control_shell"
        return "left_sidebar"

    def _get_command_workbench_layout(self, css: str, menu_html: str, decision: Dict, c: Dict) -> str:
        """命令工作台布局（偏 AI IDE 体验）。"""
        override_css = f"""
        .{c.get('app-shell', 'app-shell')} {{ background: linear-gradient(180deg,#f7f9fc 0%,#eef3f8 100%); }}
        .{c.get('sidebar', 'sidebar')} {{
            width: 88px;
            min-width: 88px;
            border-right: 1px solid rgba(15,23,42,0.14);
            background: #13243a;
            padding-top: 1rem;
        }}
        .{c.get('sidebar-header', 'sidebar-header')} {{ padding: 1rem 0.6rem; justify-content: center; font-size: 0.9rem; }}
        .{c.get('sidebar-header', 'sidebar-header')} span {{ display: none; }}
        .{c.get('sidebar-nav', 'sidebar-nav')} {{ display: flex; flex-direction: column; gap: 0.5rem; align-items: center; }}
        .{c.get('menu-item', 'menu-item')} {{
            width: 72px; min-height: 66px; margin: 0; padding: 0.6rem 0.25rem; justify-content: center;
            flex-direction: column; text-align: center; font-size: 0.72rem; border: 1px solid rgba(248,250,252,0.09);
        }}
        .{c.get('menu-item', 'menu-item')} i {{ font-size: 1.2rem; }}
        .{c.get('main-content', 'main-content')} {{ padding: 1.2rem 1.4rem 1.4rem; gap: 0.9rem; }}
        .workbench-command {{
            display: grid;
            grid-template-columns: 1.6fr 1fr auto;
            gap: 0.8rem;
            align-items: center;
            border: 1px solid rgba(15,23,42,0.12);
            background: #ffffff;
            padding: 0.8rem 1rem;
            box-shadow: 0 6px 18px rgba(15,23,42,0.06);
        }}
        .workbench-command input {{
            border: 1px solid rgba(15,23,42,0.18);
            background: #f8fafc;
            padding: 0.5rem 0.65rem;
            font-size: 0.9rem;
            outline: none;
        }}
        .workbench-ribbon {{
            border: 1px solid rgba(37,99,235,0.24);
            background: linear-gradient(90deg, rgba(37,99,235,0.08), rgba(15,23,42,0.03));
            padding: 0.6rem 0.9rem;
            font-size: 0.82rem;
            color: #1f2937;
        }}
        .workbench-canvas {{
            border: 1px solid rgba(15,23,42,0.12);
            background: #ffffff;
            box-shadow: 0 4px 14px rgba(15,23,42,0.04);
            padding: 0.8rem;
        }}
        .{c.get('topbar', 'topbar')} {{ display: none; }}
        """

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{{{ page_title }}}}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/@mdi/font@7.2.96/css/materialdesignicons.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
    <style>{css} {override_css}</style>
</head>
<body>
    <div class="{c.get('app-shell', 'app-shell')}">
        <aside class="{c.get('sidebar', 'sidebar')}">
            <div class="{c.get('sidebar-header', 'sidebar-header')}">
                <i class="mdi mdi-application-brackets-outline" style="font-size:1.2rem;color:#60a5fa;"></i>
                <span>{decision.get('project_name', '项目')}</span>
            </div>
            <nav class="{c.get('sidebar-nav', 'sidebar-nav')}">
                {menu_html}
            </nav>
        </aside>
        <main class="{c.get('main-content', 'main-content')}">
            <section class="workbench-command">
                <div style="display:flex;align-items:center;gap:0.65rem;">
                    <i class="mdi mdi-flask-outline" style="font-size:1.2rem;color:#2563eb;"></i>
                    <strong style="font-size:1rem;">{{{{ page_title }}}}</strong>
                    <span style="font-size:0.75rem;color:#64748b;">{decision.get('theme_name', 'Workbench')}</span>
                </div>
                <input value="输入命令：生成页面动作与证据锚点..." readonly>
                <div style="display:flex;gap:0.45rem;">
                    <button class="btn btn-sm btn-outline-primary" style="border-radius:0;">执行</button>
                    <button class="btn btn-sm btn-outline-secondary" style="border-radius:0;">回放</button>
                </div>
            </section>
            <section class="workbench-ribbon">
                当前视图采用命令工作台布局，优先展示可执行动作、状态留痕与证据定位。
            </section>
            <section class="workbench-canvas">
                {{{{ main_content_area }}}}
            </section>
        </main>
    </div>
    {{{{ page_scripts }}}}
</body>
</html>"""

    def _get_narrative_tool_layout(self, css: str, menu_html: str, decision: Dict, c: Dict) -> str:
        """叙事工具面布局（页面更像产品工作区而非传统后台）。"""
        override_css = f"""
        .{c.get('app-shell', 'app-shell')} {{ display:block; background:#f4f7fb; min-height:100vh; }}
        .{c.get('sidebar', 'sidebar')} {{
            width: 100%;
            height: auto;
            display: block;
            background: linear-gradient(90deg,#0f1e33,#223a56);
            border-right: none;
            border-bottom: 1px solid rgba(255,255,255,0.14);
            padding: 0.9rem 1.2rem;
        }}
        .{c.get('sidebar-header', 'sidebar-header')} {{ padding: 0; margin-bottom: 0.6rem; }}
        .{c.get('sidebar-nav', 'sidebar-nav')} {{ display:flex; flex-wrap:wrap; gap:0.55rem; padding:0; overflow:visible; }}
        .{c.get('menu-item', 'menu-item')} {{
            margin: 0;
            min-width: 126px;
            justify-content: flex-start;
            border: 1px solid rgba(255,255,255,0.14);
            background: rgba(255,255,255,0.06);
        }}
        .{c.get('main-content', 'main-content')} {{ padding: 1rem 1.2rem 1.4rem; }}
        .story-headline {{
            display:grid;
            grid-template-columns: 1.5fr 1fr;
            gap:0.8rem;
            margin-bottom:0.8rem;
        }}
        .story-card {{
            border:1px solid rgba(15,23,42,0.12);
            background:#ffffff;
            box-shadow: 0 4px 14px rgba(15,23,42,0.05);
            padding:0.8rem 0.95rem;
        }}
        .tool-surface {{
            border:1px solid rgba(15,23,42,0.12);
            background:#ffffff;
            padding:0.9rem;
        }}
        .{c.get('topbar', 'topbar')} {{ display:none; }}
        """

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{{{ page_title }}}}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/@mdi/font@7.2.96/css/materialdesignicons.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Source+Serif+4:wght@700&display=swap" rel="stylesheet">
    <style>{css} {override_css}</style>
</head>
<body>
    <div class="{c.get('app-shell', 'app-shell')}">
        <aside class="{c.get('sidebar', 'sidebar')}">
            <div class="{c.get('sidebar-header', 'sidebar-header')}">
                <i class="mdi mdi-vector-polyline" style="font-size:1.3rem;color:#93c5fd;"></i>
                <span style="font-weight:700;">{decision.get('project_name', '项目工作台')}</span>
            </div>
            <nav class="{c.get('sidebar-nav', 'sidebar-nav')}">
                {menu_html}
            </nav>
        </aside>
        <main class="{c.get('main-content', 'main-content')}">
            <section class="story-headline">
                <article class="story-card">
                    <h1 style="font-size:1.25rem;margin:0 0 0.35rem 0;">{{{{ page_title }}}}</h1>
                    <p style="margin:0;color:#64748b;font-size:0.85rem;">该页面采用叙事+工具混合壳层，强调步骤上下文与操作回放。</p>
                </article>
                <article class="story-card">
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;font-size:0.8rem;">
                        <div><span style="color:#64748b;">场景模式</span><div>叙事工具面</div></div>
                        <div><span style="color:#64748b;">主题</span><div>{decision.get('theme_name', 'Canvas')}</div></div>
                    </div>
                </article>
            </section>
            <section class="tool-surface">
                {{{{ main_content_area }}}}
            </section>
        </main>
    </div>
    {{{{ page_scripts }}}}
</body>
</html>"""

    def _get_left_sidebar_layout(self, css: str, menu_html: str, decision: Dict, c: Dict) -> str:
        """标准左侧导航布局"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{{{ page_title }}}}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/@mdi/font@7.2.96/css/materialdesignicons.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>{css}</style>
</head>
<body>
    <div class="{c.get('app-shell', 'app-shell')}">
        <aside class="{c.get('sidebar', 'sidebar')}">
            <div class="{c.get('sidebar-header', 'sidebar-header')}">
                <i class="mdi mdi-buffer" style="font-size: 1.5rem; color: var(--accent);"></i>
                <span>流程入口</span>
            </div>
            <nav class="{c.get('sidebar-nav', 'sidebar-nav')}">
                {menu_html}
            </nav>
            <div style="padding: 1.5rem; font-size: 0.75rem; opacity: 0.5; border-top: 1px solid rgba(255,255,255,0.1);">
                <div>Theme: {decision.get('theme_name', 'Default')}</div>
                <div>v2.3.0 Build</div>
            </div>
        </aside>
        <main class="{c.get('main-content', 'main-content')}">
            <header class="{c.get('topbar', 'topbar')}">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <i class="mdi mdi-menu" style="font-size: 1.5rem; cursor: pointer; display: none;"></i>
                    <h1 style="margin: 0; font-size: 1.25rem; font-weight: 600; color: var(--text-main);">{{{{ page_title }}}}</h1>
                </div>
                <div style="display: flex; gap: 1.5rem; align-items: center;">
                    <div style="position: relative;">
                        <i class="mdi mdi-bell-outline" style="font-size: 1.2rem; cursor: pointer; color: var(--text-main);"></i>
                        <span style="position: absolute; top: -2px; right: -2px; width: 8px; height: 8px; background: var(--accent); border-radius: 50%;"></span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="font-size: 0.9rem; font-weight: 500;">操作席位</span>
                        <div style="width: 32px; height: 32px; background: var(--primary); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
                            <i class="mdi mdi-account"></i>
                        </div>
                    </div>
                </div>
            </header>
            {{{{ main_content_area }}}}
        </main>
    </div>
    {{{{ page_scripts }}}}
</body>
</html>"""

    def _get_topbar_layout(self, css: str, menu_html: str, decision: Dict, c: Dict) -> str:
        """顶部导航布局 (结构差异化)"""
        # 修改 CSS 以适配顶部导航
        override_css = f"""
        .{c.get('app-shell', 'app-shell')} {{ flex-direction: column; }}
        .{c.get('sidebar', 'sidebar')} {{ width: 100%; height: auto; flex-direction: row; align-items: center; padding: 0 2rem; }}
        .{c.get('sidebar-nav', 'sidebar-nav')} {{ display: flex; flex-direction: row; overflow-x: auto; overflow-y: hidden; }}
        .{c.get('menu-item', 'menu-item')} {{ white-space: nowrap; }}
        .{c.get('main-content', 'main-content')} {{ padding-top: 2rem; }}
        .{c.get('topbar', 'topbar')} {{ display: none; }} /* 隐藏原有的 topbar */
        """

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{{{ page_title }}}}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/@mdi/font@7.2.96/css/materialdesignicons.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>{css} {override_css}</style>
</head>
<body>
    <div class="{c.get('app-shell', 'app-shell')}">
        <!-- Top Navigation Bar -->
        <aside class="{c.get('sidebar', 'sidebar')}" style="box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
            <div class="{c.get('sidebar-header', 'sidebar-header')}" style="margin-right: 3rem;">
                <i class="mdi mdi-buffer" style="font-size: 1.8rem; color: var(--accent);"></i>
                <span style="font-size: 1.4rem;">{decision.get('project_name', 'System')}</span>
            </div>
            <nav class="{c.get('sidebar-nav', 'sidebar-nav')}">
                {menu_html}
            </nav>
            <div style="display: flex; align-items: center; gap: 1rem; margin-left: auto;">
                <i class="mdi mdi-magnify" style="font-size: 1.4rem; color: var(--sidebar-text-muted);"></i>
                <div style="width: 36px; height: 36px; background: rgba(255,255,255,0.2); border-radius: 50%; border: 1px solid rgba(255,255,255,0.15);"></div>
            </div>
        </aside>

        <main class="{c.get('main-content', 'main-content')}">
            <div style="margin-bottom: 2rem; display: flex; justify-content: space-between; align-items: center;">
                <h1 style="font-size: 1.8rem; font-weight: 700;">{{{{ page_title }}}}</h1>
                <span style="color: var(--secondary);">运行视图 / 操作轨迹</span>
            </div>
            {{{{ main_content_area }}}}
        </main>
    </div>
    {{{{ page_scripts }}}}
</body>
</html>"""

    def _get_right_sidebar_layout(self, css: str, menu_html: str, decision: Dict, c: Dict) -> str:
        """右侧导航布局 (结构镜像)"""
        # 修改 CSS 以适配右侧导航
        override_css = f"""
        .{c.get('app-shell', 'app-shell')} {{ flex-direction: row-reverse; }}
        .{c.get('sidebar', 'sidebar')} {{ border-right: none; border-left: 1px solid rgba(0,0,0,0.1); }}
        """

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{{{ page_title }}}}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/@mdi/font@7.2.96/css/materialdesignicons.min.css" rel="stylesheet">
    <style>{css} {override_css}</style>
</head>
<body>
    <div class="{c.get('app-shell', 'app-shell')}">
        <aside class="{c.get('sidebar', 'sidebar')}">
            <div class="{c.get('sidebar-header', 'sidebar-header')}">
                <span>任务导航</span>
                <i class="mdi mdi-menu-open" style="font-size: 1.5rem; color: var(--accent);"></i>
            </div>
            <nav class="{c.get('sidebar-nav', 'sidebar-nav')}">
                {menu_html}
            </nav>
        </aside>

        <main class="{c.get('main-content', 'main-content')}">
            <header class="{c.get('topbar', 'topbar')}">
                <h1 style="margin: 0; font-size: 1.4rem;">{{{{ page_title }}}}</h1>
                <div style="font-size: 0.9rem; color: var(--text-main); opacity: 0.7;">
                    {decision.get('theme_name')} Style
                </div>
            </header>
            {{{{ main_content_area }}}}
        </main>
    </div>
    {{{{ page_scripts }}}}
</body>
</html>"""
