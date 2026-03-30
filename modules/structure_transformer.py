from __future__ import annotations

import ast
import random
import re
from typing import List


class StructureTransformer:
    """Low-risk structural noise injector driven by semantic comments."""

    def _comment_prefix(self, language: str) -> str:
        if language == "Python":
            return "#"
        if language in {"Java", "Go", "Node.js", "PHP"}:
            return "//"
        return "#"

    def _method_pattern(self, language: str) -> str:
        if language == "Python":
            return r"^\s*def\s+[A-Za-z_][A-Za-z0-9_]*\s*\("
        if language == "Java":
            return r"^\s*(public|private|protected)\s+.*\s+[A-Za-z_][A-Za-z0-9_]*\s*\("
        if language == "PHP":
            return r"^\s*(public|private|protected)?\s*function\s+[A-Za-z_][A-Za-z0-9_]*\s*\("
        if language == "Go":
            return r"^\s*func\s+\(?[A-Za-z_][A-Za-z0-9_]*\)?\s*[A-Za-z_][A-Za-z0-9_]*\s*\("
        if language == "Node.js":
            return r"^\s*(async\s+)?function\s+[A-Za-z_][A-Za-z0-9_]*\s*\("
        return r"^$"

    def apply_semantic_noise(
        self,
        code: str,
        language: str,
        semantic_comments: List[str],
        insert_ratio: float = 0.18,
    ) -> str:
        if not code.strip() or not semantic_comments:
            return code

        method_pattern = re.compile(self._method_pattern(language))
        comment_prefix = self._comment_prefix(language)
        lines = code.splitlines()
        new_lines: List[str] = []

        rng = random.Random(len(code) + len(semantic_comments) * 13)
        comment_idx = 0

        for line in lines:
            new_lines.append(line)
            if not method_pattern.match(line):
                continue
            if rng.random() > insert_ratio:
                continue

            indent = len(line) - len(line.lstrip())
            if language in {"Python", "PHP"}:
                indent += 4
            elif language in {"Java", "Go", "Node.js"}:
                indent += 4

            text = semantic_comments[comment_idx % len(semantic_comments)]
            comment_idx += 1
            new_lines.append(" " * indent + f"{comment_prefix} {text}")

        # Add one semantic banner at the end for low-line files.
        if len(new_lines) < 40:
            tail = semantic_comments[-1]
            new_lines.append(f"{comment_prefix} semantic-tail: {tail}")

        return "\n".join(new_lines) + ("\n" if code.endswith("\n") else "")

    def rewrite_semantic_equivalent(self, code: str, language: str, intensity: float = 0.12) -> str:
        """
        语义等价改写（结构级，不走字符串替换）。
        当前主攻 Python AST；其他语言保持原样，避免高风险误改。
        """
        if language != "Python" or not code.strip():
            return code
        try:
            tree = ast.parse(code)
            rng = random.Random(len(code) * 17 + 23)
            rewriter = _PythonSemanticRewriter(rng=rng, intensity=max(0.01, min(0.45, float(intensity))))
            tree = rewriter.visit(tree)
            ast.fix_missing_locations(tree)
            if hasattr(ast, "unparse"):
                new_code = ast.unparse(tree)
                return new_code + ("\n" if code.endswith("\n") else "")
            return code
        except Exception:
            return code


class _PythonSemanticRewriter(ast.NodeTransformer):
    """
    Python 语义等价改写器。
    只做低风险等价变换，优先保证可运行性。
    """

    def __init__(self, rng: random.Random, intensity: float) -> None:
        self.rng = rng
        self.intensity = intensity
        self._cmp_swap_map = {
            ast.Lt: ast.Gt,
            ast.Gt: ast.Lt,
            ast.LtE: ast.GtE,
            ast.GtE: ast.LtE,
            ast.Eq: ast.Eq,
            ast.NotEq: ast.NotEq,
        }

    def visit_If(self, node: ast.If):
        self.generic_visit(node)
        # cond -> not(not(cond))
        if self.rng.random() < self.intensity:
            node.test = ast.UnaryOp(
                op=ast.Not(),
                operand=ast.UnaryOp(op=ast.Not(), operand=node.test),
            )
        return node

    def visit_Compare(self, node: ast.Compare):
        self.generic_visit(node)
        # 仅处理单比较表达式，确保等价转换简单可靠。
        if len(node.ops) != 1 or len(node.comparators) != 1:
            return node
        if self.rng.random() >= self.intensity:
            return node

        op_type = type(node.ops[0])
        if op_type not in self._cmp_swap_map:
            return node
        swapped_op = self._cmp_swap_map[op_type]()
        node.left, node.comparators[0] = node.comparators[0], node.left
        node.ops[0] = swapped_op
        return node

