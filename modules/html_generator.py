"""
HTML 生成器模块 (V2.3 Refactored)
集成 Layout -> Content -> Assembler 三阶段生成管线
增强版：支持 CSS 类名混淆
"""
import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, List
from config import BASE_DIR
from core.llm_budget import llm_budget
from modules.layout_template_generator import LayoutTemplateGenerator
from modules.page_content_generator import PageContentGenerator
from modules.html_assembler import HTMLAssembler
from modules.ui_skill_orchestrator import build_ui_skill_artifacts
from modules.vendor_assets import ensure_vendor_assets_for_html_dir

logger = logging.getLogger(__name__)

class HTMLGenerator:
    """
    HTML 生成器 (V2.3 Orchestrator)
    协调 Layout, Content, Assembler 三大组件完成页面生成
    增强功能：类名混淆支持
    """

    def __init__(self, plan: Dict[str, Any], api_key: str = None):
        """
        初始化生成器
        Args:
            plan: 项目规划数据 (包含 genome, pages, menu_list)
            api_key: LLM API Key
        """
        self.plan = plan
        self.project_name = plan.get('project_name', 'UnknownProject')

        # V2.3 Pipeline Components
        self.layout_generator = LayoutTemplateGenerator(api_key=api_key)
        self.content_generator = PageContentGenerator(api_key=api_key)
        self.assembler = HTMLAssembler()
        self.page_delay_min = 0.1
        self.page_delay_span = 0.2
        self.max_page_workers = self._resolve_page_worker_count(default_workers=2)
        self.max_failure_ratio = 0.35
        self.ui_blueprint_map: Dict[str, Any] = {}
        self.runtime_skill_constraints: Dict[str, Any] = {}
        self.ui_skill_profile: Dict[str, Any] = {}

    def _resolve_page_worker_count(self, default_workers: int = 2) -> int:
        """
        根据内容生成器的网关模式动态调整并发，降低 responses 中转链路断流概率。
        """
        client = getattr(self.content_generator, "client", None)
        if not client:
            return max(1, int(default_workers))

        try:
            http_mode = bool(client._should_use_http_compatible())
            api_style = str(client._resolve_api_style())
        except Exception:
            return max(1, int(default_workers))

        if http_mode and api_style == "responses":
            self.page_delay_min = 0.25
            self.page_delay_span = 0.35
            logger.info("检测到 http/responses 模式，HTML阶段启用稳态串行策略（max_page_workers=1）")
            return 1
        if http_mode:
            self.page_delay_min = 0.15
            self.page_delay_span = 0.25
            return min(max(1, int(default_workers)), 2)
        return max(1, int(default_workers))

    def generate_all_pages(self, output_base_dir: Path = None) -> Path:
        """
        执行完整生成流程
        """
        if output_base_dir is None:
            output_base_dir = BASE_DIR / "temp_build"

        html_output_dir = output_base_dir / self.project_name / "html"
        html_output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"开始生成 HTML (V2.3 Pipeline), 输出目录: {html_output_dir}")

        self._ensure_ui_skill_artifacts()
        vendor_prepare = ensure_vendor_assets_for_html_dir(
            html_dir=html_output_dir,
            frontend_constraints=(self.runtime_skill_constraints.get("frontend") or {}),
        )
        if vendor_prepare.get("missing"):
            logger.warning("vendor 回退资产缺失: %s", ",".join(vendor_prepare.get("missing") or []))

        # 1. 准备项目级数据
        genome = self.plan.get("genome", {})
        menu_list = self.plan.get("menu_list", [])

        # 2. 生成母版 (Master Template) - 现在返回 (template, class_map)
        logger.info("Step 1/3: 生成项目级 HTML 母版...")
        try:
            template_result = self.layout_generator.generate_template(
                genome,
                menu_list,
                skill_profile=self.ui_skill_profile,
                return_class_map=True,
            )
            if isinstance(template_result, tuple) and len(template_result) == 2:
                master_template, class_map = template_result
            else:
                master_template = str(template_result)
                class_map = getattr(self.layout_generator, "class_map", {}) or {}
            logger.info(f"母版生成成功，类名映射数量: {len(class_map)}")
        except Exception as e:
            logger.error(f"母版生成失败: {e}")
            master_template = "<html><body><h1>Critical Error: Template Generation Failed</h1>{{ main_content_area }}</body></html>"
            class_map = {}

        # 3. 遍历页面生成
        pages = self.plan.get('pages', {})
        generated_count = 0

        logger.info(f"Step 2/3: 开始生成 {len(pages)} 个页面的内容...")

        def process_page(item):
            page_id, page_data = item
            page_title = page_data.get('page_title', '未命名页面')
            logger.debug(f"处理页面: {page_title} ({page_id})")
            page_blueprint = self.ui_blueprint_map.get(str(page_id), {})

            page_info = {
                "title": page_title,
                "description": page_data.get('page_description', ''),
                "page_id": page_id
            }

            content_data = self.content_generator.generate_content(
                genome,
                page_info,
                page_blueprint=page_blueprint,
                style_context=(self.ui_skill_profile.get("design_decision") or {}),
            )
            final_html = self.assembler.assemble(
                master_template,
                content_data,
                page_info,
                class_map,
                project_name=self.project_name,
                page_blueprint=page_blueprint,
                runtime_skill_constraints=self.runtime_skill_constraints,
            )
            return page_id, page_title, final_html

        current_run_id = llm_budget.current_run_id()
        current_stage = llm_budget.current_stage()

        def process_page_with_budget(item):
            # ThreadPoolExecutor 线程不会继承 thread-local，显式透传预算上下文
            with llm_budget.run_scope(current_run_id):
                with llm_budget.stage_scope(current_stage):
                    return process_page(item)

        page_items = list(pages.items())
        worker_count = min(self.max_page_workers, max(1, len(page_items)))
        failed_count = 0

        if worker_count == 1:
            for item in page_items:
                try:
                    page_id, page_title, final_html = process_page_with_budget(item)
                    output_file = html_output_dir / f"{page_id}.html"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(final_html)
                    logger.info(f"✓ 已生成: {page_id}.html - {page_title}")
                    generated_count += 1
                    time.sleep(self.page_delay_min + random.random() * self.page_delay_span)
                except Exception as e:
                    failed_count += 1
                    page_id = item[0]
                    logger.error(f"生成页面 {page_id} 失败: {e}")
                    self._write_error_page(html_output_dir / f"{page_id}.html", str(e))
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {executor.submit(process_page_with_budget, item): item for item in page_items}
                for future in as_completed(future_map):
                    item = future_map[future]
                    page_id = item[0]
                    try:
                        page_id, page_title, final_html = future.result()
                        output_file = html_output_dir / f"{page_id}.html"
                        with open(output_file, 'w', encoding='utf-8') as f:
                            f.write(final_html)
                        logger.info(f"✓ 已生成: {page_id}.html - {page_title}")
                        generated_count += 1
                    except Exception as e:
                        failed_count += 1
                        logger.error(f"生成页面 {page_id} 失败: {e}")
                        self._write_error_page(html_output_dir / f"{page_id}.html", str(e))

        # 质量闸门：失败比例过高则中断上游流水线
        total_pages = len(page_items)
        if total_pages > 0:
            failure_ratio = failed_count / total_pages
            if failure_ratio > self.max_failure_ratio:
                raise RuntimeError(
                    f"HTML 页面生成失败率过高: {failed_count}/{total_pages} ({failure_ratio:.0%})"
                )
            if generated_count == 0:
                raise RuntimeError("HTML 页面全部生成失败，流程中止")

        logger.info(f"Step 3/3: HTML 生成完成，共 {generated_count} 个页面")
        return html_output_dir

    def _ensure_ui_skill_artifacts(self) -> None:
        """
        确保 UI 技能编排产物存在，并加载 page_id -> blueprint 映射。
        """
        project_dir = BASE_DIR / "output" / self.project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        try:
            artifacts = build_ui_skill_artifacts(
                project_name=self.project_name,
                plan=self.plan,
                project_dir=project_dir,
                force=False,
            )
            blueprint = artifacts.get("blueprint") or {}
            profile = artifacts.get("profile") or {}
            page_map = blueprint.get("page_map") or {}
            if isinstance(page_map, dict):
                self.ui_blueprint_map = page_map
            else:
                self.ui_blueprint_map = {}
            self.ui_skill_profile = profile if isinstance(profile, dict) else {}
            self.runtime_skill_constraints = (
                (artifacts.get("runtime_skill_plan") or {}).get("constraints") if isinstance(artifacts.get("runtime_skill_plan"), dict) else {}
            ) or {}
            logger.info(
                "UI 技能蓝图已加载: pages=%s, mode=%s, token_policy=%s",
                len(self.ui_blueprint_map),
                str((artifacts.get("profile") or {}).get("mode") or ""),
                str((artifacts.get("profile") or {}).get("token_policy") or ""),
            )
        except Exception as e:
            self.ui_blueprint_map = {}
            self.ui_skill_profile = {}
            self.runtime_skill_constraints = {}
            logger.warning(f"加载 UI 技能蓝图失败，回退默认生成: {e}")

    def _write_error_page(self, path: Path, error_msg: str):
        """写入错误页面，保证文件存在"""
        content = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Generation Error</title></head>
        <body style="padding: 2rem; font-family: sans-serif; color: #721c24; background-color: #f8d7da;">
            <h1>生成失败</h1>
            <p>Page ID: {path.stem}</p>
            <pre>{error_msg}</pre>
        </body>
        </html>
        """
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

# 兼容旧代码的顶层函数接口
def generate_html_pages(json_path: Path, output_base_dir: Path = None) -> Path:
    with open(json_path, 'r', encoding='utf-8') as f:
        plan = json.load(f)

    generator = HTMLGenerator(plan)
    return generator.generate_all_pages(output_base_dir)
