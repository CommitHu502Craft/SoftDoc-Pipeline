import ast
import logging
import math
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Set, Optional

logger = logging.getLogger(__name__)


class NoveltyAnalyzer:
    """Per-file novelty scoring using token, AST and structural similarity."""

    def __init__(
        self,
        seed_files: Dict[str, str],
        language: str,
        enable_embedding: bool = False,
        embedding_weight: float = 0.15,
        embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        embedding_max_chars: int = 2400,
    ) -> None:
        self.language = (language or "").lower()
        self.enable_embedding = bool(enable_embedding)
        self.embedding_weight = max(0.0, min(float(embedding_weight or 0.0), 0.4))
        self.embedding_model_name = str(embedding_model_name or "sentence-transformers/all-MiniLM-L6-v2")
        self.embedding_max_chars = max(400, min(int(embedding_max_chars or 2400), 8000))
        self._embedder = None
        if self.enable_embedding and self.embedding_weight > 0:
            self._embedder = self._init_embedder()

        self.seed_profiles: Dict[str, Dict[str, Any]] = {}
        for path, content in (seed_files or {}).items():
            self.seed_profiles[path] = self._build_profile(content)

    def _init_embedder(self):
        """
        初始化向量编码器（可选能力）。
        若环境缺失 sentence-transformers 或模型加载失败，自动降级关闭。
        """
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.embedding_model_name)
            logger.info(f"NoveltyAnalyzer embedding enabled: {self.embedding_model_name}")
            return model
        except Exception as e:
            logger.warning(f"Embedding similarity disabled: {e}")
            return None

    def _normalize_embedding_text(self, code: str) -> str:
        text = (code or "").strip()
        if not text:
            return ""
        # 统一空白，防止仅因缩进差异导致向量噪声。
        text = re.sub(r"\s+", " ", text)
        if len(text) > self.embedding_max_chars:
            text = text[: self.embedding_max_chars]
        return text

    def _embed_code(self, code: str) -> Optional[List[float]]:
        if self._embedder is None:
            return None
        text = self._normalize_embedding_text(code)
        if not text:
            return None
        try:
            vec = self._embedder.encode([text], normalize_embeddings=True)
            if hasattr(vec, "tolist"):
                vec = vec.tolist()
            if isinstance(vec, list) and vec and isinstance(vec[0], list):
                return [float(x) for x in vec[0]]
            return [float(x) for x in vec]
        except Exception:
            return None

    @staticmethod
    def _cosine_similarity(a: Optional[List[float]], b: Optional[List[float]]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(0.0, min(1.0, dot / (norm_a * norm_b)))

    def _build_profile(self, code: str) -> Dict[str, Any]:
        tokens = self._tokenize(code)
        token_grams = self._ngrams(tokens, 3)
        skeleton = self._line_skeleton_ngrams(code, 3)
        identifiers = self._extract_identifiers(tokens)
        signatures = self._extract_signatures(code)
        call_edges = self._extract_call_edges(code)

        profile: Dict[str, Any] = {
            "token_grams": token_grams,
            "skeleton": skeleton,
            "token_count": len(tokens),
            "identifiers": identifiers,
            "signatures": signatures,
            "call_edges": call_edges,
        }
        embedding = self._embed_code(code)
        if embedding is not None:
            profile["embedding"] = embedding

        ast_counter = self._ast_counter(code)
        if ast_counter is not None:
            profile["ast_counter"] = ast_counter

        return profile

    @staticmethod
    def _tokenize(code: str) -> List[str]:
        return [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", code or "")]

    def _keywords(self) -> Set[str]:
        common = {
            "if", "else", "for", "while", "return", "try", "except", "catch", "finally", "class",
            "def", "function", "import", "from", "with", "new", "this", "self", "null", "true",
            "false", "const", "let", "var", "public", "private", "protected", "static",
        }
        lang = self.language
        if lang == "python":
            common |= {"lambda", "yield", "async", "await", "pass", "raise", "global", "nonlocal"}
        elif lang in {"java", "go", "php", "node.js", "javascript"}:
            common |= {"package", "interface", "extends", "implements", "switch", "case"}
        return common

    def _extract_identifiers(self, tokens: List[str]) -> Set[str]:
        kw = self._keywords()
        return {t for t in tokens if len(t) >= 4 and t not in kw and not t.isdigit()}

    @staticmethod
    def _ngrams(tokens: Iterable[str], n: int) -> Set[str]:
        values = list(tokens)
        if len(values) < n:
            return set(values)
        return {" ".join(values[i : i + n]) for i in range(0, len(values) - n + 1)}

    @staticmethod
    def _line_skeleton(line: str) -> str:
        # Remove literals and normalize identifiers/numbers to structure placeholders.
        line = re.sub(r"(['\"]).*?\1", "STR", line)
        line = re.sub(r"\b\d+\b", "NUM", line)
        line = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", "ID", line)
        line = re.sub(r"\s+", "", line)
        return line.strip()

    def _line_skeleton_ngrams(self, code: str, n: int) -> Set[str]:
        skeleton_lines = [self._line_skeleton(x) for x in (code or "").splitlines() if x.strip()]
        skeleton_lines = [x for x in skeleton_lines if x]
        if len(skeleton_lines) < n:
            return set(skeleton_lines)
        return {"|".join(skeleton_lines[i : i + n]) for i in range(0, len(skeleton_lines) - n + 1)}

    def _extract_signatures(self, code: str) -> Set[str]:
        signatures: Set[str] = set()
        text = code or ""
        if self.language == "python":
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        argc = len(node.args.args) + len(node.args.kwonlyargs)
                        signatures.add(f"{node.name}/{argc}")
            except Exception:
                pass
            return signatures

        patterns = [
            r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*\{",
            r"\bfunc\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
        ]
        for pat in patterns:
            for name, args in re.findall(pat, text):
                argc = len([x for x in args.split(",") if x.strip()])
                signatures.add(f"{name.lower()}/{argc}")
        return signatures

    def _extract_call_edges(self, code: str) -> Set[str]:
        """
        近似调用图特征。
        非 Python 语言采用轻量近似，不要求编译器级精度。
        """
        edges: Set[str] = set()
        text = code or ""

        if self.language == "python":
            try:
                tree = ast.parse(text)
            except Exception:
                return edges

            class Visitor(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.current = "<module>"
                    self.edges: Set[str] = set()

                def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
                    prev = self.current
                    self.current = node.name
                    self.generic_visit(node)
                    self.current = prev

                def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
                    prev = self.current
                    self.current = node.name
                    self.generic_visit(node)
                    self.current = prev

                def visit_Call(self, node: ast.Call) -> Any:
                    callee = ""
                    if isinstance(node.func, ast.Name):
                        callee = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        callee = node.func.attr
                    if callee:
                        self.edges.add(f"{self.current.lower()}->{callee.lower()}")
                    self.generic_visit(node)

            visitor = Visitor()
            visitor.visit(tree)
            return visitor.edges

        calls = [x.lower() for x in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)]
        kw = self._keywords()
        calls = [x for x in calls if x not in kw and len(x) >= 3]
        if not calls:
            return edges
        # 用相邻调用序列近似“行为路径”。
        for i in range(0, len(calls) - 1):
            edges.add(f"{calls[i]}->{calls[i+1]}")
        return edges

    def _ast_counter(self, code: str) -> Optional[Counter]:
        if self.language != "python":
            return None
        try:
            tree = ast.parse(code)
        except Exception:
            return None
        counter = Counter()
        for node in ast.walk(tree):
            counter[type(node).__name__] += 1
        return counter

    @staticmethod
    def _jaccard_set(a: Set[str], b: Set[str]) -> float:
        if not a and not b:
            return 0.0
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        if union == 0:
            return 0.0
        return inter / union

    @staticmethod
    def _jaccard_counter(a: Counter, b: Counter) -> float:
        if not a and not b:
            return 0.0
        keys = set(a) | set(b)
        if not keys:
            return 0.0
        inter = sum(min(a.get(k, 0), b.get(k, 0)) for k in keys)
        union = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
        if union == 0:
            return 0.0
        return inter / union

    def _pair_similarity(self, profile_a: Dict[str, Any], profile_b: Dict[str, Any]) -> Dict[str, float]:
        token_sim = self._jaccard_set(
            profile_a.get("token_grams", set()),
            profile_b.get("token_grams", set()),
        )
        struct_sim = self._jaccard_set(
            profile_a.get("skeleton", set()),
            profile_b.get("skeleton", set()),
        )

        ast_a = profile_a.get("ast_counter")
        ast_b = profile_b.get("ast_counter")
        ast_sim = 0.0
        if isinstance(ast_a, Counter) and isinstance(ast_b, Counter):
            ast_sim = self._jaccard_counter(ast_a, ast_b)

        identifier_sim = self._jaccard_set(
            profile_a.get("identifiers", set()),
            profile_b.get("identifiers", set()),
        )
        signature_sim = self._jaccard_set(
            profile_a.get("signatures", set()),
            profile_b.get("signatures", set()),
        )
        call_edge_sim = self._jaccard_set(
            profile_a.get("call_edges", set()),
            profile_b.get("call_edges", set()),
        )
        emb_a = profile_a.get("embedding")
        emb_b = profile_b.get("embedding")
        embedding_available = (
            isinstance(emb_a, list)
            and isinstance(emb_b, list)
            and len(emb_a) > 0
            and len(emb_a) == len(emb_b)
        )
        embedding_sim = self._cosine_similarity(emb_a, emb_b)

        # 多视角融合：token + AST + 结构 + 标识符 + 签名 + 调用关系
        if self.language == "python":
            blended_base = (
                token_sim * 0.35
                + ast_sim * 0.25
                + struct_sim * 0.12
                + identifier_sim * 0.10
                + signature_sim * 0.10
                + call_edge_sim * 0.08
            )
        else:
            blended_base = (
                token_sim * 0.45
                + struct_sim * 0.20
                + identifier_sim * 0.20
                + signature_sim * 0.10
                + call_edge_sim * 0.05
            )
        # 只有当这对样本都具备可用向量时才做融合，防止“缺向量=0”被误当作低相似。
        if self._embedder is not None and self.embedding_weight > 0 and embedding_available:
            blended = blended_base * (1.0 - self.embedding_weight) + embedding_sim * self.embedding_weight
        else:
            blended = blended_base

        return {
            "token_similarity": round(token_sim, 4),
            "ast_similarity": round(ast_sim, 4),
            "struct_similarity": round(struct_sim, 4),
            "identifier_similarity": round(identifier_sim, 4),
            "signature_similarity": round(signature_sim, 4),
            "call_edge_similarity": round(call_edge_sim, 4),
            "embedding_similarity": round(embedding_sim, 4),
            "blended_similarity": round(blended, 4),
        }

    def evaluate(self, code: str, source_code: str = "") -> Dict[str, Any]:
        candidate_profile = self._build_profile(code)

        max_seed = {
            "path": "",
            "token_similarity": 0.0,
            "ast_similarity": 0.0,
            "struct_similarity": 0.0,
            "identifier_similarity": 0.0,
            "signature_similarity": 0.0,
            "call_edge_similarity": 0.0,
            "embedding_similarity": 0.0,
            "blended_similarity": 0.0,
        }

        for path, seed_profile in self.seed_profiles.items():
            score = self._pair_similarity(candidate_profile, seed_profile)
            if score["blended_similarity"] > max_seed["blended_similarity"]:
                max_seed = {"path": path, **score}

        source_similarity = {
            "token_similarity": 0.0,
            "ast_similarity": 0.0,
            "struct_similarity": 0.0,
            "identifier_similarity": 0.0,
            "signature_similarity": 0.0,
            "call_edge_similarity": 0.0,
            "embedding_similarity": 0.0,
            "blended_similarity": 0.0,
        }
        if source_code:
            source_profile = self._build_profile(source_code)
            source_similarity = self._pair_similarity(candidate_profile, source_profile)

        max_similarity = max(max_seed["blended_similarity"], source_similarity["blended_similarity"])
        novelty_score = max(0.0, 1.0 - max_similarity)

        if max_similarity >= 0.78:
            risk_level = "high"
        elif max_similarity >= 0.62:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "novelty_score": round(novelty_score, 4),
            "max_similarity": round(max_similarity, 4),
            "risk_level": risk_level,
            "seed_best_match": max_seed,
            "source_similarity": source_similarity,
        }

