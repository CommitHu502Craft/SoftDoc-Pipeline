import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union


class ForbiddenPatternIndex:
    """Indexes high-risk token windows from seed code to detect verbatim carry-over."""

    def __init__(
        self,
        seed_files: Dict[str, str],
        window_size: int = 9,
        max_patterns: int = 12000,
        min_line_length: int = 72,
        extra_corpus: Optional[List[str]] = None,
        feedback_path: Optional[str] = None,
        feedback_limit: int = 200,
    ) -> None:
        self.window_size = max(6, int(window_size))
        self.max_patterns = max(1000, int(max_patterns))
        self.min_line_length = max(40, int(min_line_length))

        window_counter = Counter()
        line_counter = Counter()

        corpus: List[str] = []
        for _, content in (seed_files or {}).items():
            if content:
                corpus.append(content)

        for content in (extra_corpus or []):
            if content:
                corpus.append(content)

        if feedback_path:
            corpus.extend(self._load_feedback_snippets(feedback_path, limit=feedback_limit))

        for content in corpus:
            tokens = self._tokenize(content)
            if len(tokens) >= self.window_size:
                for i in range(0, len(tokens) - self.window_size + 1):
                    window = tokens[i : i + self.window_size]
                    digest = self._hash_window(window)
                    window_counter[digest] += 1

            for raw_line in content.splitlines():
                line = self._normalize_line(raw_line)
                if len(line) >= self.min_line_length:
                    line_counter[line] += 1

        self.forbidden_windows = {
            key for key, _ in window_counter.most_common(self.max_patterns)
        }
        self.forbidden_lines = {
            line for line, _ in line_counter.items() if len(line) >= self.min_line_length
        }

    @staticmethod
    def _load_feedback_snippets(feedback_path: str, limit: int = 200) -> List[str]:
        snippets: List[str] = []
        path = Path(feedback_path)
        if not path.exists():
            return snippets
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    snippet = str(record.get("snippet", "") or "")
                    if snippet:
                        snippets.append(snippet)
                    if len(snippets) >= max(20, int(limit)):
                        break
        except Exception:
            return []
        return snippets

    @staticmethod
    def collect_history_corpus(
        history_roots: List[str],
        max_files: int = 120,
        max_total_chars: int = 2_000_000,
    ) -> List[str]:
        """
        收集历史项目代码片段，用于“负约束检索”。
        目标是提取高频片段，不追求完整索引，避免初始化开销过大。
        """
        roots = [Path(x) for x in (history_roots or []) if x]
        exts = {".py", ".java", ".go", ".js", ".php", ".ts"}
        snippets: List[str] = []
        total_chars = 0
        file_count = 0

        for root in roots:
            if not root.exists():
                continue
            for fp in root.rglob("*"):
                if not fp.is_file() or fp.suffix.lower() not in exts:
                    continue
                try:
                    text = fp.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if not text.strip():
                    continue

                # 只取前后片段，兼顾速度与代表性
                lines = text.splitlines()
                head = lines[:120]
                tail = lines[-120:] if len(lines) > 120 else []
                snippet = "\n".join(head + tail)
                snippets.append(snippet)
                total_chars += len(snippet)
                file_count += 1

                if file_count >= max_files or total_chars >= max_total_chars:
                    return snippets
        return snippets

    @staticmethod
    def append_feedback(
        feedback_path: str,
        file_path: str,
        code: str,
        report: Dict[str, Union[float, int, List[str]]],
        novelty_score: float = 0.0,
    ) -> None:
        """
        将“高相似风险样本”回流为下轮负约束数据。
        """
        if not feedback_path or not code.strip():
            return
        path = Path(feedback_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [x for x in code.splitlines() if x.strip()]
        snippet = "\n".join(lines[:80] + lines[-80:] if len(lines) > 160 else lines)
        payload = {
            "file_path": file_path,
            "novelty_score": round(float(novelty_score or 0.0), 4),
            "forbidden_risk": round(float(report.get("risk_score", 0.0)), 4),
            "window_density": round(float(report.get("window_density", 0.0)), 4),
            "line_hits": int(report.get("line_hits", 0)),
            "samples": report.get("samples", [])[:3],
            "snippet": snippet,
        }
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            return

    @staticmethod
    def _tokenize(code: str) -> List[str]:
        return re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", code or "")

    @staticmethod
    def _hash_window(window_tokens: Iterable[str]) -> str:
        joined = " ".join(window_tokens)
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _normalize_line(line: str) -> str:
        line = re.sub(r"\s+", "", line or "")
        return line.strip()

    def inspect(self, code: str) -> Dict[str, Union[float, int, List[str]]]:
        tokens = self._tokenize(code)
        total_windows = max(0, len(tokens) - self.window_size + 1)

        window_hits = 0
        window_samples: List[str] = []
        if total_windows > 0 and self.forbidden_windows:
            for i in range(0, total_windows):
                window = tokens[i : i + self.window_size]
                digest = self._hash_window(window)
                if digest in self.forbidden_windows:
                    window_hits += 1
                    if len(window_samples) < 3:
                        window_samples.append(" ".join(window))

        line_hits = 0
        if self.forbidden_lines:
            for raw_line in code.splitlines():
                line = self._normalize_line(raw_line)
                if line and line in self.forbidden_lines:
                    line_hits += 1

        density = (window_hits / total_windows) if total_windows else 0.0
        risk_score = min(1.0, density * 2.5 + (line_hits / 30.0))

        return {
            "window_hits": int(window_hits),
            "line_hits": int(line_hits),
            "window_density": float(round(density, 4)),
            "risk_score": float(round(risk_score, 4)),
            "samples": window_samples,
        }

    @staticmethod
    def is_risky(report: Dict[str, Union[float, int, List[str]]], density_threshold: float = 0.08) -> bool:
        if not report:
            return False
        if float(report.get("risk_score", 0.0)) >= 0.35:
            return True
        if float(report.get("window_density", 0.0)) >= float(density_threshold):
            return True
        if int(report.get("line_hits", 0)) >= 6:
            return True
        return False

