"""
批量混淆工具 - 用于混淆多个项目的代码
使用方法：
1. 单个项目：python -m modules.batch_obfuscator "项目名称"
2. 所有项目：python -m modules.batch_obfuscator --all
3. 指定多个：python -m modules.batch_obfuscator "项目1" "项目2"
"""
import sys
from pathlib import Path
import logging

from .ast_obfuscator import obfuscate_project_code
from config import OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BatchObfuscator")


def obfuscate_single_project(project_name: str, backup: bool = True) -> bool:
    """混淆单个项目"""
    project_dir = OUTPUT_DIR / project_name

    if not project_dir.exists():
        logger.error(f"项目不存在: {project_name}")
        return False

    logger.info(f"开始混淆项目: {project_name}")
    success = obfuscate_project_code(project_dir, backup=backup)

    if success:
        logger.info(f"✓ 项目 {project_name} 混淆成功")
    else:
        logger.error(f"✗ 项目 {project_name} 混淆失败")

    return success


def obfuscate_all_projects(backup: bool = True) -> dict:
    """混淆所有项目"""
    if not OUTPUT_DIR.exists():
        logger.error(f"输出目录不存在: {OUTPUT_DIR}")
        return {}

    projects = [
        d for d in OUTPUT_DIR.iterdir()
        if d.is_dir() and (d / "aligned_code").exists()
    ]

    if not projects:
        logger.warning("未找到任何项目")
        return {}

    logger.info(f"找到 {len(projects)} 个项目")

    results = {}
    for i, project_dir in enumerate(projects, 1):
        project_name = project_dir.name
        logger.info(f"\n[{i}/{len(projects)}] 处理: {project_name}")

        try:
            success = obfuscate_project_code(project_dir, backup=backup)
            results[project_name] = success
        except Exception as e:
            logger.error(f"处理 {project_name} 时出错: {e}")
            results[project_name] = False

    success_count = sum(1 for v in results.values() if v)
    logger.info(f"\n总结: {success_count}/{len(results)} 个项目混淆成功")

    return results


def main():
    """主函数"""
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        return

    backup = True
    if "--no-backup" in args:
        backup = False
        args.remove("--no-backup")

    if "--all" in args:
        obfuscate_all_projects(backup=backup)
    else:
        for project_name in args:
            obfuscate_single_project(project_name, backup=backup)


if __name__ == "__main__":
    main()
