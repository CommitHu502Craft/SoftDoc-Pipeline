"""
AST级代码混淆器
使用抽象语法树技术进行结构性混淆，防止代码查重
不会破坏代码逻辑，只改变变量名、函数名等标识符
"""
import ast
import random
import string
from pathlib import Path
from typing import Dict, Set, Optional
import logging

logger = logging.getLogger(__name__)


class NameObfuscator(ast.NodeTransformer):
    """AST节点转换器 - 混淆变量名和函数名"""

    # Python关键字和内置函数，不能混淆
    RESERVED_NAMES = {
        # 关键字
        'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
        'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
        'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
        'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return',
        'try', 'while', 'with', 'yield',
        # 常用内置函数
        'print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict',
        'set', 'tuple', 'bool', 'type', 'isinstance', 'open', 'input',
        'enumerate', 'zip', 'map', 'filter', 'sum', 'max', 'min', 'abs',
        'round', 'sorted', 'reversed', 'any', 'all', 'super', 'property',
        'staticmethod', 'classmethod', '__init__', '__str__', '__repr__',
        # 常见库名（不混淆导入的模块名）
        'os', 'sys', 're', 'json', 'time', 'datetime', 'random', 'math',
        'pandas', 'numpy', 'requests', 'flask', 'django', 'matplotlib',
        'self', 'cls',  # 类相关
    }

    def __init__(self, prefix: str = "v_"):
        """
        初始化混淆器
        :param prefix: 混淆后变量名的前缀，例如 "v_" 或 "var_"
        """
        self.prefix = prefix
        self.name_mapping: Dict[str, str] = {}  # 原名 -> 混淆名
        self.used_names: Set[str] = set()  # 已使用的混淆名
        self.scope_stack = []  # 作用域栈
        self.counter = 0  # 计数器

    def _generate_obfuscated_name(self, original_name: str) -> str:
        """生成混淆后的名称"""
        # 如果已经映射过，直接返回
        if original_name in self.name_mapping:
            return self.name_mapping[original_name]

        # 如果是保留名称，不混淆
        if original_name in self.RESERVED_NAMES:
            return original_name

        # 如果是魔法方法（__xxx__），不混淆
        if original_name.startswith('__') and original_name.endswith('__'):
            return original_name

        # 如果是私有变量（_xxx），保留下划线前缀
        if original_name.startswith('_') and not original_name.startswith('__'):
            prefix = '_' + self.prefix
        else:
            prefix = self.prefix

        # 生成新名称
        while True:
            # 策略1: 使用计数器（简单但有效）
            new_name = f"{prefix}{self.counter}"
            self.counter += 1

            # 策略2: 或者使用随机字符串（更难识别）
            # new_name = prefix + ''.join(random.choices(string.ascii_lowercase, k=6))

            if new_name not in self.used_names:
                self.used_names.add(new_name)
                self.name_mapping[original_name] = new_name
                return new_name

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """访问函数定义节点"""
        # 不混淆魔法方法
        if not (node.name.startswith('__') and node.name.endswith('__')):
            # 混淆函数名
            node.name = self._generate_obfuscated_name(node.name)

        # 混淆参数名
        for arg in node.args.args:
            if arg.arg not in self.RESERVED_NAMES:
                arg.arg = self._generate_obfuscated_name(arg.arg)

        # 继续处理函数体
        self.generic_visit(node)
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:
        """访问变量名节点"""
        if isinstance(node.ctx, (ast.Store, ast.Load, ast.Del)):
            if node.id not in self.RESERVED_NAMES:
                node.id = self._generate_obfuscated_name(node.id)
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        """访问参数节点"""
        if node.arg not in self.RESERVED_NAMES:
            node.arg = self._generate_obfuscated_name(node.arg)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        """访问类定义节点"""
        # 混淆类名（可选，根据需求决定）
        # node.name = self._generate_obfuscated_name(node.name)

        # 继续处理类体
        self.generic_visit(node)
        return node


class ASTObfuscator:
    """AST代码混淆器主类"""

    def __init__(self, prefix: str = "v_", obfuscate_functions: bool = True):
        """
        初始化混淆器
        :param prefix: 变量名前缀
        :param obfuscate_functions: 是否混淆函数名
        """
        self.prefix = prefix
        self.obfuscate_functions = obfuscate_functions

    def obfuscate_code(self, source_code: str) -> Optional[str]:
        """
        混淆Python源代码
        :param source_code: 原始代码
        :return: 混淆后的代码，失败返回None
        """
        try:
            # 解析代码为AST
            tree = ast.parse(source_code)

            # 应用混淆转换
            obfuscator = NameObfuscator(prefix=self.prefix)
            new_tree = obfuscator.visit(tree)

            # 修复AST（必需，否则代码可能不合法）
            ast.fix_missing_locations(new_tree)

            # 将AST转回代码
            import astor  # 需要安装: pip install astor
            obfuscated_code = astor.to_source(new_tree)

            logger.info(f"成功混淆代码，映射了 {len(obfuscator.name_mapping)} 个名称")
            return obfuscated_code

        except ImportError:
            # 如果没有astor，使用compile + unparse（Python 3.9+）
            try:
                obfuscated_code = ast.unparse(new_tree)
                logger.info(f"成功混淆代码（使用ast.unparse），映射了 {len(obfuscator.name_mapping)} 个名称")
                return obfuscated_code
            except AttributeError:
                logger.error("需要安装 astor 库: pip install astor")
                logger.error("或使用 Python 3.9+ (内置 ast.unparse)")
                return None

        except SyntaxError as e:
            logger.error(f"代码语法错误，无法混淆: {e}")
            return None
        except Exception as e:
            logger.error(f"混淆失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def obfuscate_file(self, input_path: Path, output_path: Optional[Path] = None) -> bool:
        """
        混淆单个Python文件
        :param input_path: 输入文件路径
        :param output_path: 输出文件路径，如果为None则覆盖原文件
        :return: 是否成功
        """
        try:
            # 读取源文件
            with open(input_path, 'r', encoding='utf-8') as f:
                source_code = f.read()

            # 混淆代码
            obfuscated = self.obfuscate_code(source_code)
            if obfuscated is None:
                return False

            # 写入输出文件
            if output_path is None:
                output_path = input_path

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(obfuscated)

            logger.info(f"✓ 混淆完成: {input_path} -> {output_path}")
            return True

        except Exception as e:
            logger.error(f"处理文件失败 {input_path}: {e}")
            return False

    def obfuscate_directory(self, input_dir: Path, output_dir: Optional[Path] = None,
                           recursive: bool = True) -> Dict[str, bool]:
        """
        批量混淆目录中的所有Python文件
        :param input_dir: 输入目录
        :param output_dir: 输出目录，如果为None则覆盖原文件
        :param recursive: 是否递归处理子目录
        :return: {文件路径: 是否成功} 字典
        """
        results = {}

        # 查找所有Python文件
        pattern = "**/*.py" if recursive else "*.py"
        py_files = list(input_dir.glob(pattern))

        logger.info(f"找到 {len(py_files)} 个Python文件")

        for py_file in py_files:
            # 跳过 __init__.py 和测试文件（可选）
            if py_file.name == '__init__.py':
                logger.info(f"跳过: {py_file}")
                continue

            # 计算输出路径
            if output_dir:
                relative_path = py_file.relative_to(input_dir)
                out_path = output_dir / relative_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                out_path = None

            # 混淆文件
            success = self.obfuscate_file(py_file, out_path)
            results[str(py_file)] = success

        # 统计结果
        success_count = sum(1 for v in results.values() if v)
        logger.info(f"混淆完成: {success_count}/{len(results)} 个文件成功")

        return results


def obfuscate_project_code(project_dir: Path, backup: bool = True) -> bool:
    """
    混淆项目中的所有代码文件
    :param project_dir: 项目目录（包含aligned_code的目录）
    :param backup: 是否备份原文件
    :return: 是否成功
    """
    code_dir = project_dir / "aligned_code"

    if not code_dir.exists():
        logger.error(f"代码目录不存在: {code_dir}")
        return False

    # 备份原文件
    if backup:
        backup_dir = project_dir / "aligned_code_backup"
        if backup_dir.exists():
            import shutil
            shutil.rmtree(backup_dir)

        import shutil
        shutil.copytree(code_dir, backup_dir)
        logger.info(f"已备份原代码到: {backup_dir}")

    # 执行混淆
    obfuscator = ASTObfuscator(prefix="var_")
    results = obfuscator.obfuscate_directory(code_dir, recursive=True)

    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    logger.info(f"项目混淆完成: {success_count}/{total_count} 成功")

    return success_count == total_count


# 命令行使用示例
if __name__ == "__main__":
    import sys

    # 示例：混淆单个文件
    if len(sys.argv) > 1:
        input_file = Path(sys.argv[1])
        output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None

        obfuscator = ASTObfuscator(prefix="v_")
        success = obfuscator.obfuscate_file(input_file, output_file)

        if success:
            print("✓ 混淆成功")
        else:
            print("✗ 混淆失败")
    else:
        # 演示
        demo_code = """
def calculate_area(width, height):
    '''计算矩形面积'''
    result = width * height
    return result

def main():
    w = 10
    h = 20
    area = calculate_area(w, h)
    print(f"面积: {area}")

if __name__ == "__main__":
    main()
"""
        print("原始代码:")
        print(demo_code)
        print("\n" + "="*50 + "\n")

        obfuscator = ASTObfuscator(prefix="v_")
        obfuscated = obfuscator.obfuscate_code(demo_code)

        if obfuscated:
            print("混淆后代码:")
            print(obfuscated)
        else:
            print("混淆失败，请检查是否安装了 astor 库")
            print("安装命令: pip install astor")
