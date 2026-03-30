"""
自动化软著申请材料生成系统 - 主入口 (V2.2 Charter/Spec Pipeline)
"""
import asyncio
import json
import argparse
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from config import OUTPUT_DIR, BASE_DIR
from modules.project_planner import ProjectPlanner
from modules.html_generator import HTMLGenerator
from modules.screenshot_engine import capture_screenshots_sync
from modules.document_generator import DocumentGenerator
from modules.code_pdf_generator import CodePDFGenerator
from modules.code_transformer import CodeTransformer
from modules.fingerprint_auditor import FingerprintAuditor
from modules.project_charter import (
    default_project_charter_template,
    load_project_charter,
    normalize_project_charter,
    save_project_charter,
    validate_project_charter,
)
from modules.executable_spec_builder import (
    build_executable_spec,
    save_executable_spec,
    validate_executable_spec,
)
from modules.runtime_verifier import run_runtime_verification
from modules.freeze_package import build_freeze_package
from modules.artifact_naming import preferred_artifact_path
from core.parallel_executor import ParallelExecutor
from modules.copyright_differentiator import CopyrightFieldsDifferentiator
from modules.word_to_pdf import convert_word_to_pdf
from core.pipeline_orchestrator import PipelineOrchestrator

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def run_api_preflight() -> None:
    """在执行 LLM 相关步骤前做一次连通性预检"""
    from core.deepseek_client import DeepSeekClient

    logger.info("Preflight: 检查 API 连通性...")
    client = DeepSeekClient()
    if not client.test_connection():
        raise RuntimeError("API 连通性预检失败，请检查 API Key/端点/模型/协议配置")
    logger.info("Preflight: API 连通性通过")


def resolve_project_charter(project_name: str, project_dir: Path, charter_file: Optional[Path] = None) -> Dict[str, Any]:
    """解析并校验项目章程；不通过则阻断流程。"""
    raw_charter: Dict[str, Any] = {}
    if charter_file and charter_file.exists():
        with open(charter_file, "r", encoding="utf-8") as f:
            raw_charter = json.load(f)
    else:
        raw_charter = load_project_charter(project_dir) or {}

    charter = normalize_project_charter(raw_charter, project_name=project_name)
    errors = validate_project_charter(charter)
    if errors:
        if not raw_charter:
            template = default_project_charter_template(project_name)
            save_project_charter(project_dir, template)
        raise ValueError(
            "项目章程不完整，流程已阻断。请在 output/<项目名>/project_charter.json 补全以下字段："
            + "；".join(errors)
        )
    save_project_charter(project_dir, charter)
    return charter


def save_plan_snapshots(plan: Dict[str, Any], json_path: Path, project_dir: Path) -> None:
    """
    保存规划到用户指定路径，并同步到标准路径，避免后续步骤读取偏差。
    """
    canonical_path = project_dir / "project_plan.json"
    targets = []
    for path in [json_path, canonical_path]:
        normalized = Path(path)
        if str(normalized) not in [str(p) for p in targets]:
            targets.append(normalized)

    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)


async def full_pipeline(project_name: str, json_path: Path, charter_file: Optional[Path] = None):
    """
    V2.1 异步全流水线
    逻辑:
    1. 规划 (Planner) -> 串行
    2. 资源 (Layout)  -> 串行
    3. 内容 (Content + Code + Doc) -> 并行 (High Concurrency)
    4. 后处理 (Screenshot + PDF)   -> 并行
    5. 审计 (Audit)   -> 串行
    """
    start_time = time.time()
    logger.info(f"🚀 启动 V2.2 全异步流水线: {project_name}")
    if PipelineOrchestrator.needs_llm_preflight(["plan", "html", "code"]):
        run_api_preflight()

    project_dir = OUTPUT_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    charter = resolve_project_charter(project_name, project_dir, charter_file)

    # ==========================================
    # Phase 1: 项目规划 (Project Planning)
    # ==========================================
    phase_start = time.time()
    logger.info("\n[Phase 1] 项目规划 (Project Planning)...")

    planner = ProjectPlanner()
    plan = planner.generate_full_plan(project_name, project_charter=charter)

    # 保存规划文件
    save_plan_snapshots(plan, json_path, project_dir)

    logger.info(f"✓ 规划完成，耗时: {time.time() - phase_start:.2f}s")

    # ==========================================
    # Phase 1.5: 可执行规格 (Spec-first)
    # ==========================================
    phase_start = time.time()
    logger.info("\n[Phase 1.5] 生成可执行规格 (Spec-first)...")

    spec = plan.get("executable_spec") or build_executable_spec(plan, charter)
    spec_errors = validate_executable_spec(spec)
    if spec_errors:
        raise RuntimeError("可执行规格校验失败: " + "；".join(spec_errors))
    spec_path = save_executable_spec(project_dir, spec)
    plan["executable_spec"] = spec
    save_plan_snapshots(plan, json_path, project_dir)
    logger.info(f"✓ 规格生成完成: {spec_path}，耗时: {time.time() - phase_start:.2f}s")

    # ==========================================
    # Phase 2: 并行内容生成 (Parallel Generation)
    # ==========================================
    phase_start = time.time()
    logger.info("\n[Phase 2] 并行内容生成 (HTML/Code/Doc)...")

    # executor = ParallelExecutor()  # 未使用，已注释

    # 初始化各个生成器
    html_gen = HTMLGenerator(plan)
    code_transformer = CodeTransformer(plan)

    # 路径准备
    html_output_dir = BASE_DIR / "temp_build" / project_name / "html"
    code_output_dir = OUTPUT_DIR / project_name / "aligned_code"
    screenshot_dir = OUTPUT_DIR / project_name / "screenshots"
    doc_output_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="manual_docx")
    code_pdf_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="code_pdf")

    # --- 定义并发任务 ---

    # Task A: HTML 生成 (Layout -> Content -> Assemble)
    # HTMLGenerator.generate_all_pages 内部已经实现了部分并行逻辑(如果改造了的话)，
    # 但目前我们将其视为一个整体的大任务，或者可以在这里进一步拆解。
    # 为了简化，我们调用 generate_all_pages，它内部会利用 ParallelExecutor (如果已集成)
    # 或者我们让它在线程池中运行（因为它主要还是 IO + 计算）
    async def task_generate_html():
        logger.info("  -> 启动 HTML 生成任务...")
        return await asyncio.to_thread(html_gen.generate_all_pages, BASE_DIR / "temp_build")

    # Task B: 代码转换 (IO 密集 + CPU 密集)
    # CodeTransformer.transform_seed_to_project 内部已经使用了 ParallelExecutor
    async def task_generate_code():
        logger.info("  -> 启动代码转换任务...")
        return await asyncio.to_thread(code_transformer.transform_seed_to_project, code_output_dir)

    # Task C: 软著字段生成 (轻量级)
    async def task_generate_copyright_fields():
        logger.info("  -> 启动软著字段生成...")
        copyright_txt_path = OUTPUT_DIR / project_name / "软著平台字段.txt"
        # 确保父目录存在
        copyright_txt_path.parent.mkdir(parents=True, exist_ok=True)
        if "copyright_fields" in plan:
            diff = CopyrightFieldsDifferentiator(seed=project_name)
            cf = plan["copyright_fields"]
            industry = cf.get("industry", "业务管理")
            if isinstance(industry, list):
                industry = industry[0] if industry else "业务管理"

            dev_purpose = diff.rewrite_purpose(cf.get("development_purpose", ""), industry)
            main_funcs = diff.rewrite_main_functions(cf.get("main_functions", ""))
            tech_features = diff.rewrite_technical_features(cf.get("technical_features", ""))

            content = f"""============================================================
软著平台填写字段 - {project_name}
============================================================

【开发目的】
{dev_purpose}

【面向领域/行业】
{industry}

【软件的主要功能】
{main_funcs}

【软件的技术特点】
{tech_features}
"""
            with open(copyright_txt_path, "w", encoding="utf-8") as f:
                f.write(content)
            return str(copyright_txt_path)
        return None

    # 并发执行 A, B, C
    # 注意: DocumentGenerator 依赖截图，所以不能在这里并行执行，必须等截图完成后
    html_result, code_files, copyright_file = await asyncio.gather(
        task_generate_html(),
        task_generate_code(),
        task_generate_copyright_fields()
    )
    if not code_files:
        raise RuntimeError("代码阶段未产出文件，流程中止（质量闸门或生成异常）")

    logger.info(f"✓ 内容生成完成，耗时: {time.time() - phase_start:.2f}s")

    # ==========================================
    # Phase 3: 后处理 (Post-Processing)
    # ==========================================
    phase_start = time.time()
    logger.info("\n[Phase 3] 后处理 (Screenshot & PDF)...")

    # 此时 HTML 和 Code 均已就绪

    # Task D: 截图 (依赖 HTML)
    async def task_screenshots():
        logger.info("  -> 启动截图引擎...")
        # 使用 capture_screenshots_sync 函数
        return await asyncio.to_thread(
            capture_screenshots_sync,
            html_dir=html_output_dir,
            output_dir=screenshot_dir
        )

    # Task E: 代码 PDF (依赖 Code)
    async def task_code_pdf():
        logger.info("  -> 启动源码 PDF 生成...")
        # 构造 CodePDFGenerator (正确的参数顺序)
        pdf_gen = CodePDFGenerator(
            project_name=project_name,
            version="V1.0.0",
            html_dir=str(html_output_dir),
            include_html=False
        )
        # 调用 generate() 方法 (正确的参数顺序)
        success = await asyncio.to_thread(
            pdf_gen.generate,
            code_dir=str(code_output_dir),
            output_path=str(code_pdf_path)
        )
        return success

    # 并发执行 D, E
    await asyncio.gather(task_screenshots(), task_code_pdf())

    logger.info(f"✓ 后处理完成，耗时: {time.time() - phase_start:.2f}s")

    # ==========================================
    # Phase 4: 运行验证 (Verification)
    # ==========================================
    phase_start = time.time()
    logger.info("\n[Phase 4] 运行验证 (Smoke + Replay)...")
    verify_passed, verify_report_path, verify_report = await asyncio.to_thread(
        run_runtime_verification,
        project_name,
        project_dir,
        html_output_dir,
    )
    logger.info(f"✓ 运行验证报告: {verify_report_path}")
    if not verify_passed:
        raise RuntimeError(f"运行验证失败: {verify_report.get('summary', {})}")
    logger.info(f"✓ 运行验证通过，耗时: {time.time() - phase_start:.2f}s")

    # ==========================================
    # Phase 5: 文档生成 (Documentation)
    # ==========================================
    # 文档生成依赖截图，所以必须在 Phase 3 之后
    phase_start = time.time()
    logger.info("\n[Phase 5] 文档生成 (Word Manual)...")

    template_path = BASE_DIR / "templates" / "manual_template.docx"
    if template_path.exists():
        # DocumentGenerator 构造函数接收所有参数
        doc_gen = DocumentGenerator(
            plan_path=str(json_path),
            screenshot_dir=str(screenshot_dir),
            template_path=str(template_path),
            output_path=str(doc_output_path)
        )
        # generate() 方法无参数
        await asyncio.to_thread(doc_gen.generate)
        logger.info(f"✓ 说明书生成完成: {doc_output_path}")

        # 与 GUI/API 保持一致：生成 Word 后自动导出 PDF
        doc_pdf_path = preferred_artifact_path(project_dir, project_name=project_name, artifact_key="manual_pdf")
        pdf_ok = await asyncio.to_thread(convert_word_to_pdf, doc_output_path, doc_pdf_path)
        if pdf_ok:
            logger.info(f"✓ 说明书PDF生成完成: {doc_pdf_path}")
        else:
            raise RuntimeError("说明书 PDF 转换失败，流程中止")
    else:
        logger.warning(f"跳过说明书生成: 模板不存在 {template_path}")

    logger.info(f"✓ 文档阶段耗时: {time.time() - phase_start:.2f}s")

    # ==========================================
    # Phase 6: 审计与收尾 (Audit & Finalize)
    # ==========================================
    logger.info("\n[Phase 6] 最终审计 (Audit)...")

    auditor = FingerprintAuditor()
    artifacts = auditor.compute_project_fingerprints(str(OUTPUT_DIR / project_name))
    report = auditor.check_similarity(artifacts)

    if not report["is_safe"]:
        logger.warning(f"⚠️ 风险警告: 项目相似度过高 (Score: {report['similarity_score']})")
    else:
        logger.info(f"✓ 指纹检测通过 (Score: {report['similarity_score']})")

    auditor.add_to_history(project_name, artifacts)

    # ==========================================
    # Phase 7: 冻结提交包 (Freeze Package)
    # ==========================================
    freeze_result = await asyncio.to_thread(
        build_freeze_package,
        project_name,
        project_dir,
        html_output_dir,
    )
    logger.info(f"✓ 冻结提交包已生成: {freeze_result.get('zip_path')}")

    total_time = time.time() - start_time
    logger.info(f"\n✨ 全流程执行完毕! 总耗时: {total_time:.2f}s")
    logger.info(f"输出目录: {OUTPUT_DIR / project_name}")


def main():
    parser = argparse.ArgumentParser(description="自动化软著申请材料生成系统 (V2.2)")
    parser.add_argument("--project", "-p", required=True, help="项目名称")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 路径")
    parser.add_argument("--charter-file", default=None, help="项目章程 JSON 文件路径")
    parser.add_argument("--full-pipeline", action="store_true", help="执行完整流水线")

    # 单步模式
    parser.add_argument("--plan-only", action="store_true", help="仅生成项目规划")
    parser.add_argument("--html-only", action="store_true", help="仅生成 HTML")
    parser.add_argument("--code-only", action="store_true", help="仅生成代码")
    parser.add_argument("--screenshot-only", action="store_true", help="仅生成截图")
    parser.add_argument("--pdf-only", action="store_true", help="仅生成代码 PDF")
    parser.add_argument("--doc-only", action="store_true", help="仅生成说明书")

    args = parser.parse_args()

    if args.project:
        json_path = Path(args.output) if args.output else OUTPUT_DIR / args.project / "project_plan.json"
        charter_path = Path(args.charter_file) if args.charter_file else None

        if args.full_pipeline:
            # 运行异步流水线
            try:
                asyncio.run(full_pipeline(args.project, json_path, charter_file=charter_path))
            except KeyboardInterrupt:
                logger.info("用户中断执行")
            except Exception as e:
                logger.error(f"执行失败: {e}", exc_info=True)

        elif args.plan_only:
            # 仅生成规划
            logger.info("执行模式: 仅生成项目规划")
            try:
                if PipelineOrchestrator.needs_llm_preflight(["plan"]):
                    run_api_preflight()
                project_dir = OUTPUT_DIR / args.project
                project_dir.mkdir(parents=True, exist_ok=True)
                charter = resolve_project_charter(args.project, project_dir, charter_path)
                planner = ProjectPlanner()
                plan = planner.generate_full_plan(args.project, project_charter=charter)
                spec = plan.get("executable_spec") or build_executable_spec(plan, charter)
                spec_errors = validate_executable_spec(spec)
                if spec_errors:
                    raise RuntimeError("可执行规格校验失败: " + "；".join(spec_errors))
                plan["executable_spec"] = spec
                save_plan_snapshots(plan, json_path, project_dir)
                spec_path = save_executable_spec(project_dir, spec)
                logger.info(f"✓ 规划文件已保存: {json_path}")
                logger.info(f"✓ 可执行规格已保存: {spec_path}")
            except Exception as e:
                logger.error(f"规划生成失败: {e}", exc_info=True)

        elif args.html_only:
            # 仅生成 HTML
            logger.info("执行模式: 仅生成 HTML")
            try:
                if PipelineOrchestrator.needs_llm_preflight(["html"]):
                    run_api_preflight()
                if not json_path.exists():
                    logger.error(f"规划文件不存在: {json_path}，请先运行 --plan-only")
                    return

                with open(json_path, "r", encoding="utf-8") as f:
                    plan = json.load(f)

                html_gen = HTMLGenerator(plan)
                html_output_dir = html_gen.generate_all_pages(BASE_DIR / "temp_build")
                logger.info(f"✓ HTML 生成完成: {html_output_dir}")
            except Exception as e:
                logger.error(f"HTML 生成失败: {e}", exc_info=True)

        elif args.code_only:
            # 仅生成代码
            logger.info("执行模式: 仅生成代码")
            try:
                if PipelineOrchestrator.needs_llm_preflight(["code"]):
                    run_api_preflight()
                if not json_path.exists():
                    logger.error(f"规划文件不存在: {json_path}，请先运行 --plan-only")
                    return

                with open(json_path, "r", encoding="utf-8") as f:
                    plan = json.load(f)
                project_dir = OUTPUT_DIR / args.project
                spec_path = project_dir / "project_executable_spec.json"
                if not spec_path.exists():
                    charter = resolve_project_charter(args.project, project_dir, charter_path)
                    spec = build_executable_spec(plan, charter)
                    spec_errors = validate_executable_spec(spec)
                    if spec_errors:
                        raise RuntimeError("可执行规格校验失败: " + "；".join(spec_errors))
                    save_executable_spec(project_dir, spec)
                    plan["executable_spec"] = spec
                else:
                    with open(spec_path, "r", encoding="utf-8") as sf:
                        plan["executable_spec"] = json.load(sf)

                code_transformer = CodeTransformer(plan)
                code_output_dir = OUTPUT_DIR / args.project / "aligned_code"
                code_files = code_transformer.transform_seed_to_project(code_output_dir)
                if not code_files:
                    raise RuntimeError("代码生成未产出文件，请检查质量报告与日志")
                logger.info(f"✓ 代码生成完成: {len(code_files)} 个文件")
            except Exception as e:
                logger.error(f"代码生成失败: {e}", exc_info=True)

        elif args.screenshot_only:
            # 仅生成截图
            logger.info("执行模式: 仅生成截图")
            try:
                html_dir = BASE_DIR / "temp_build" / args.project / "html"
                screenshot_dir = OUTPUT_DIR / args.project / "screenshots"

                if not html_dir.exists():
                    logger.error(f"HTML 目录不存在: {html_dir}，请先运行 --html-only")
                    return

                capture_screenshots_sync(html_dir, screenshot_dir)
                logger.info(f"✓ 截图生成完成: {screenshot_dir}")
            except Exception as e:
                logger.error(f"截图生成失败: {e}", exc_info=True)

        elif args.pdf_only:
            # 仅生成代码 PDF
            logger.info("执行模式: 仅生成代码 PDF")
            try:
                code_dir = OUTPUT_DIR / args.project / "aligned_code"
                html_dir = BASE_DIR / "temp_build" / args.project / "html"
                project_dir = OUTPUT_DIR / args.project
                pdf_path = preferred_artifact_path(project_dir, project_name=args.project, artifact_key="code_pdf")

                if not code_dir.exists():
                    logger.error(f"代码目录不存在: {code_dir}，请先运行 --code-only")
                    return

                pdf_gen = CodePDFGenerator(
                    project_name=args.project,
                    version="V1.0.0",
                    html_dir=str(html_dir) if html_dir.exists() else None,
                    include_html=False
                )
                success = pdf_gen.generate(str(code_dir), str(pdf_path))
                if success:
                    logger.info(f"✓ PDF 生成完成: {pdf_path}")
                else:
                    logger.error("PDF 生成失败")
            except Exception as e:
                logger.error(f"PDF 生成失败: {e}", exc_info=True)

        elif args.doc_only:
            # 仅生成说明书
            logger.info("执行模式: 仅生成说明书")
            try:
                screenshot_dir = OUTPUT_DIR / args.project / "screenshots"
                template_path = BASE_DIR / "templates" / "manual_template.docx"
                project_dir = OUTPUT_DIR / args.project
                doc_path = preferred_artifact_path(project_dir, project_name=args.project, artifact_key="manual_docx")

                if not json_path.exists():
                    logger.error(f"规划文件不存在: {json_path}，请先运行 --plan-only")
                    return

                if not screenshot_dir.exists():
                    logger.error(f"截图目录不存在: {screenshot_dir}，请先运行 --screenshot-only")
                    return

                if not template_path.exists():
                    logger.error(f"模板文件不存在: {template_path}")
                    return

                doc_gen = DocumentGenerator(
                    plan_path=str(json_path),
                    screenshot_dir=str(screenshot_dir),
                    template_path=str(template_path),
                    output_path=str(doc_path)
                )
                verify_passed, verify_report_path, verify_report = run_runtime_verification(
                    args.project,
                    OUTPUT_DIR / args.project,
                    BASE_DIR / "temp_build" / args.project / "html",
                )
                if not verify_passed:
                    raise RuntimeError(f"运行验证失败: {verify_report.get('summary', {})}")
                logger.info(f"✓ 运行验证通过: {verify_report_path}")
                doc_gen.generate()
                logger.info(f"✓ 说明书生成完成: {doc_path}")

                doc_pdf_path = preferred_artifact_path(project_dir, project_name=args.project, artifact_key="manual_pdf")
                if convert_word_to_pdf(doc_path, doc_pdf_path):
                    logger.info(f"✓ 说明书PDF生成完成: {doc_pdf_path}")
                else:
                    raise RuntimeError("说明书 PDF 转换失败")
            except Exception as e:
                logger.error(f"说明书生成失败: {e}", exc_info=True)

        else:
            # 没有指定模式，提示用户
            logger.info("请指定执行模式:")
            logger.info("  --full-pipeline   执行完整流水线")
            logger.info("  --plan-only       仅生成项目规划")
            logger.info("  --html-only       仅生成 HTML")
            logger.info("  --code-only       仅生成代码")
            logger.info("  --screenshot-only 仅生成截图")
            logger.info("  --pdf-only        仅生成代码 PDF")
            logger.info("  --doc-only        仅生成说明书")
            logger.info("")
            logger.info("示例: python main.py -p '项目名' --full-pipeline")

if __name__ == "__main__":
    main()
