import ast
import random
import re
import logging
try:
    import astor
except ImportError:
    astor = None

logger = logging.getLogger(__name__)

class ControlFlowTransformer:
    """
    控制流变换引擎 (Phase 1)
    通过改变代码的 AST 结构 (Control Flow Graph)，对抗基于结构的查重算法。
    """

    def transform(self, code: str, language: str) -> str:
        """
        入口方法
        """
        try:
            # 映射 Node.js 到 JavaScript
            lang = "JavaScript" if language == "Node.js" else language

            if lang == "Python":
                return self._transform_python(code)
            elif lang in ["Java", "JavaScript", "Go", "PHP"]:
                return self._transform_c_style(code, lang)
        except Exception as e:
            logger.error(f"控制流变换失败 ({language}): {e}")
            return code # 失败降级

        return code

    def _transform_python(self, code: str) -> str:
        """Python AST 变换"""
        try:
            tree = ast.parse(code)
            transformer = PythonASTObfuscator()
            tree = transformer.visit(tree)
            ast.fix_missing_locations(tree)

            # 优先使用 ast.unparse (Python 3.9+)
            if hasattr(ast, 'unparse'):
                return ast.unparse(tree)
            elif astor:
                return astor.to_source(tree)
            else:
                # 只有在环境极度受限时才会走到这里
                return code
        except Exception as e:
            logger.warning(f"Python parse error: {e}")
            return code

    def _transform_c_style(self, code: str, language: str) -> str:
        """基于正则的通用变换 (Java, JS, Go, PHP)"""
        lines = code.split('\n')
        new_lines = []

        # 1. 冗余嵌套 (Redundant Nesting)
        # 策略: 随机选中一行语句，包裹在 if (true) { ... } 中
        # 需要排除: import, package, return (可能导致不可达代码), 类定义等

        skip_keywords = [
            'import ', 'package ', 'return', 'throw', 'break', 'continue',
            'public class', 'class ', 'interface ', 'type ', 'func ',
            'function ', '@', 'export '
        ]
        if language == "PHP":
            skip_keywords.extend(['namespace ', 'use '])

        block_open = "{"
        block_close = "}"
        if_true = "if (true)"
        if language == "Go":
            if_true = "if true"
        elif language == "Python": # Should not happen, but strictly speaking
            if_true = "if True:"

        for line in lines:
            stripped = line.strip()

            # 简单判断是否是独立语句 (以分号结尾，且不是特殊结构)
            # Go 语言不一定以分号结尾，判断比较宽松
            is_statement = False
            if language == "Go":
                # Go: 简单赋值或调用，不以 { 结尾
                if len(stripped) > 5 and not stripped.endswith('{') and not stripped.endswith('}') and not stripped.startswith('//'):
                    is_statement = True
            else:
                # Java/JS/PHP: 以分号结尾
                is_statement = stripped.endswith(';')

            should_skip = any(k in stripped for k in skip_keywords)

            # 5% 概率进行包裹 (降低概率以免代码过于臃肿)
            if is_statement and not should_skip and random.random() < 0.05:
                # 获取缩进
                indent_match = re.match(r'^(\s*)', line)
                indent = indent_match.group(1) if indent_match else ""

                new_lines.append(f"{indent}{if_true} {block_open}")
                new_lines.append(line)
                new_lines.append(f"{indent}{block_close}")
            else:
                new_lines.append(line)

        return "\n".join(new_lines)

class PythonASTObfuscator(ast.NodeTransformer):
    """Python AST 混淆器"""

    def visit_FunctionDef(self, node):
        self.generic_visit(node)

        # 策略1: 冗余嵌套 (包裹整个函数体)
        # def func(): body -> def func(): if 1==1: body
        # 仅当函数体不为空且不全是 docstring 时
        if len(node.body) > 0 and random.random() < 0.2:
            # 检查是否有 docstring，如果有，保留在最前面
            body_start_idx = 0
            if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Str, ast.Constant)):
                body_start_idx = 1

            if body_start_idx < len(node.body):
                real_body = node.body[body_start_idx:]
                doc_string = node.body[:body_start_idx]

                if_node = ast.If(
                    test=ast.Compare(
                        left=ast.Constant(value=1),
                        ops=[ast.Eq()],
                        comparators=[ast.Constant(value=1)]
                    ),
                    body=real_body,
                    orelse=[]
                )

                node.body = doc_string + [if_node]

        return node

    def visit_If(self, node):
        self.generic_visit(node)

        # 策略2: 插入无效分支
        # if cond: ... -> if cond: ... else: pass (如果原来没有else)
        if not node.orelse and random.random() < 0.2:
            node.orelse = [ast.Pass()]

        return node
