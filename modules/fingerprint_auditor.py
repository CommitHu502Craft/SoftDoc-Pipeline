"""
指纹自审模块 (Fingerprint Auditor)
用于检测当前生成项目与历史项目的相似度，防止软著申请查重风险。

核心功能：
1. 计算代码、HTML、文档的结构指纹 (SimHash / Structure Hash)
2. 维护历史项目指纹数据库
3. 提供相似度检测报告
"""
import sqlite3
import json
import logging
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime
from bs4 import BeautifulSoup

# 获取模块级日志记录器
logger = logging.getLogger(__name__)

class FingerprintAuditor:
    """
    项目指纹审计员
    负责计算、存储和比对项目指纹
    """

    # 相似度阈值配置
    SIMILARITY_THRESHOLD = 0.6  # 超过此值视为风险 (Risky)
    BLOCK_THRESHOLD = 0.8       # 超过此值建议拦截 (Blocked)

    def __init__(self, db_path: str = "data/fingerprints.db"):
        """
        初始化审计员

        Args:
            db_path: SQLite 数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建历史记录表
        # code_fingerprint: 存储代码的 SimHash (64位整数或十六进制字符串)
        # html_fingerprint: 存储 HTML 结构的哈希
        # artifacts_summary: 存储其他元数据的 JSON
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                code_fingerprint TEXT,
                html_fingerprint TEXT,
                artifacts_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def check_similarity(self, new_artifacts: Dict[str, Any]) -> Dict[str, Any]:
        """
        对比新材料与历史记录的相似度

        Args:
            new_artifacts: 包含当前项目指纹的字典
                {
                    "project_name": str,
                    "code_fingerprint": str, # Hex string
                    "html_fingerprint": str, # Hex string
                }

        Returns:
            Dict: 检测报告
            {
                "is_safe": bool,
                "similarity_score": float,  # 0-1, 最大相似度
                "similar_projects": list,   # [(name, score), ...]
                "recommendation": str       # "safe" / "risky" / "blocked"
            }
        """
        current_code_fp = new_artifacts.get("code_fingerprint", "0")
        current_html_fp = new_artifacts.get("html_fingerprint", "0")
        project_name = new_artifacts.get("project_name", "Unknown")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 获取所有历史记录
        cursor.execute('SELECT project_name, code_fingerprint, html_fingerprint FROM history WHERE project_name != ?', (project_name,))
        history = cursor.fetchall()
        conn.close()

        max_similarity = 0.0
        similar_projects = []

        for h_name, h_code_fp, h_html_fp in history:
            # 计算综合相似度
            # 代码权重 0.7, HTML 权重 0.3
            code_sim = self._calculate_simhash_similarity(current_code_fp, h_code_fp)
            html_sim = self._calculate_simhash_similarity(current_html_fp, h_html_fp)

            # 加权平均
            weighted_sim = (code_sim * 0.7) + (html_sim * 0.3)

            if weighted_sim > 0.4: # 只记录有一定相似度的
                similar_projects.append((h_name, round(weighted_sim, 3)))

            if weighted_sim > max_similarity:
                max_similarity = weighted_sim

        # 排序相似项目
        similar_projects.sort(key=lambda x: x[1], reverse=True)
        similar_projects = similar_projects[:5] # 只保留前5个

        # 判定结果
        recommendation = "safe"
        is_safe = True

        if max_similarity >= self.BLOCK_THRESHOLD:
            recommendation = "blocked"
            is_safe = False
        elif max_similarity >= self.SIMILARITY_THRESHOLD:
            recommendation = "risky"
            is_safe = True # 标记为风险但默认不阻塞，由用户决定

        logger.info(f"指纹审计完成 - 项目: {project_name}, 最大相似度: {max_similarity:.2f}, 结果: {recommendation}")

        return {
            "is_safe": is_safe,
            "similarity_score": round(max_similarity, 3),
            "similar_projects": similar_projects,
            "recommendation": recommendation
        }

    def evaluate_project_novelty(
        self,
        project_name: str,
        project_dir: str,
        persist_report: bool = True,
        update_history: bool = False,
    ) -> Dict[str, Any]:
        """
        计算当前项目的新颖性报告（供门禁/冻结包复用）。
        """
        artifacts = self.compute_project_fingerprints(project_dir)
        artifacts["project_name"] = project_name
        similarity = self.check_similarity(artifacts)
        report = {
            "project_name": project_name,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "code_fingerprint": artifacts.get("code_fingerprint", ""),
            "html_fingerprint": artifacts.get("html_fingerprint", ""),
            "max_similarity": float(similarity.get("similarity_score") or 0.0),
            "similar_projects": similarity.get("similar_projects") or [],
            "recommendation": str(similarity.get("recommendation") or "safe"),
            "novelty_score": round(1.0 - float(similarity.get("similarity_score") or 0.0), 4),
            "risk_level": (
                "high"
                if str(similarity.get("recommendation")) == "blocked"
                else ("medium" if str(similarity.get("recommendation")) == "risky" else "low")
            ),
            "passed": str(similarity.get("recommendation") or "safe") != "blocked",
        }

        project_path = Path(project_dir)
        if persist_report:
            try:
                out = project_path / "novelty_quality_report.json"
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"写入 novelty_quality_report 失败: {e}")

        if update_history:
            self.add_to_history(project_name, artifacts)

        return report

    def add_to_history(self, project_name: str, artifacts: Dict[str, Any]):
        """
        将新生成的材料指纹存入数据库

        Args:
            project_name: 项目名称
            artifacts: 指纹数据
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 检查是否存在，存在则更新
            cursor.execute('SELECT id FROM history WHERE project_name = ?', (project_name,))
            existing = cursor.fetchone()

            summary = json.dumps({k: v for k, v in artifacts.items() if k not in ['code_fingerprint', 'html_fingerprint']})

            if existing:
                cursor.execute('''
                    UPDATE history
                    SET code_fingerprint = ?, html_fingerprint = ?, artifacts_summary = ?, created_at = CURRENT_TIMESTAMP
                    WHERE project_name = ?
                ''', (artifacts.get('code_fingerprint'), artifacts.get('html_fingerprint'), summary, project_name))
                logger.info(f"更新历史指纹记录: {project_name}")
            else:
                cursor.execute('''
                    INSERT INTO history (project_name, code_fingerprint, html_fingerprint, artifacts_summary)
                    VALUES (?, ?, ?, ?)
                ''', (project_name, artifacts.get('code_fingerprint'), artifacts.get('html_fingerprint'), summary))
                logger.info(f"新增历史指纹记录: {project_name}")

            conn.commit()
        except Exception as e:
            logger.error(f"保存指纹失败: {e}")
        finally:
            conn.close()

    def compute_project_fingerprints(self, project_dir: str) -> Dict[str, str]:
        """
        计算整个项目的指纹集合

        Args:
            project_dir: 项目输出目录路径

        Returns:
            Dict: 指纹集合
        """
        project_path = Path(project_dir)

        # 1. 计算代码指纹
        code_files = []
        code_dir = project_path / "aligned_code"
        if code_dir.exists():
            # 收集主要代码文件
            for ext in ['*.py', '*.java', '*.go', '*.js', '*.php']:
                for f in code_dir.rglob(ext):
                    if f.is_file():
                        code_files.append(str(f))

        code_fp = self._compute_code_fingerprint(code_files)

        # 2. 计算 HTML 指纹
        html_files = []
        # 注意：HTML 通常在 temp_build 中，或者如果是 web ui 则在 output 中
        # 这里假设在 code_dir 或者是 temp_build 对应的 html 目录
        # 为了简化，我们假设用户传入的是 output/{project}，我们需要找对应的 html
        # 尝试寻找 temp_build/{project}/html
        temp_build_html = project_path.parent.parent / "temp_build" / project_path.name / "html"

        if temp_build_html.exists():
             for f in temp_build_html.glob("*.html"):
                 html_files.append(str(f))

        html_content_list = []
        for hf in html_files:
            try:
                with open(hf, 'r', encoding='utf-8') as f:
                    html_content_list.append(f.read())
            except:
                pass

        html_fp = self._compute_html_fingerprint(html_content_list)

        return {
            "code_fingerprint": code_fp,
            "html_fingerprint": html_fp
        }

    def _compute_code_fingerprint(self, file_paths: List[str]) -> str:
        """
        使用 SimHash 算法计算代码指纹
        """
        if not file_paths:
            return "0" * 16

        features = {}

        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 简单的分词: 按非字母数字字符分割
                tokens = re.split(r'[^a-zA-Z0-9_]+', content)

                # 过滤掉短词和常见关键词 (简单停用词表)
                stop_words = {'if', 'else', 'for', 'while', 'return', 'import', 'from', 'def', 'class', 'public', 'private', 'void', 'int', 'var'}

                for token in tokens:
                    token = token.lower()
                    if len(token) > 2 and token not in stop_words:
                        features[token] = features.get(token, 0) + 1

            except Exception as e:
                logger.warning(f"读取代码文件失败 {file_path}: {e}")

        return self._simhash(features)

    def _compute_html_fingerprint(self, html_contents: List[str]) -> str:
        """
        提取 DOM 结构计算结构指纹
        """
        if not html_contents:
            return "0" * 16

        features = {}

        for html in html_contents:
            try:
                soup = BeautifulSoup(html, 'html.parser')

                # 提取标签序列
                tags = [tag.name for tag in soup.find_all()]

                # 生成 N-gram 特征 (3-gram)
                # 例如: html-body-div, body-div-container
                if len(tags) >= 3:
                    for i in range(len(tags) - 2):
                        gram = f"{tags[i]}-{tags[i+1]}-{tags[i+2]}"
                        features[gram] = features.get(gram, 0) + 1
                else:
                    # 如果标签太少，直接用标签名
                    for tag in tags:
                        features[tag] = features.get(tag, 0) + 1

            except Exception as e:
                logger.warning(f"解析 HTML 失败: {e}")

        return self._simhash(features)

    def _simhash(self, features: Dict[str, int], hash_bits: int = 64) -> str:
        """
        标准 SimHash 实现

        Args:
            features: 特征及其权重字典 {feature_str: weight}
            hash_bits: 哈希位数 (64)

        Returns:
            str: 十六进制指纹字符串
        """
        v = [0] * hash_bits

        for feature, weight in features.items():
            # 获取特征的哈希值
            h = int(hashlib.md5(feature.encode('utf-8')).hexdigest(), 16)

            for i in range(hash_bits):
                bitmask = 1 << i
                if h & bitmask:
                    v[i] += weight
                else:
                    v[i] -= weight

        # 生成指纹
        fingerprint = 0
        for i in range(hash_bits):
            if v[i] > 0:
                fingerprint |= (1 << i)

        # 返回十六进制字符串 (定长)
        return hex(fingerprint)[2:].zfill(hash_bits // 4)

    def _calculate_simhash_similarity(self, fp1: str, fp2: str) -> float:
        """
        计算两个 SimHash 指纹的相似度
        使用海明距离 (Hamming Distance)
        """
        try:
            # 转换为整数
            int_1 = int(fp1, 16)
            int_2 = int(fp2, 16)

            # 计算异或 (不同位为1)
            xor = int_1 ^ int_2

            # 计算海明距离 (不同位的个数)
            hamming_distance = bin(xor).count('1')

            # 计算相似度 (假设64位)
            # 距离越小越相似
            bits = 64
            similarity = 1 - (hamming_distance / bits)

            return max(0.0, min(1.0, similarity))

        except ValueError:
            return 0.0

# 便捷测试入口
if __name__ == "__main__":
    auditor = FingerprintAuditor()
    print("FingerprintAuditor initialized.")

    # 模拟测试
    test_features_1 = {"function_a": 1, "class_user": 2, "import_os": 1}
    fp1 = auditor._simhash(test_features_1)
    print(f"Fingerprint 1: {fp1}")

    test_features_2 = {"function_a": 1, "class_admin": 2, "import_sys": 1}
    fp2 = auditor._simhash(test_features_2)
    print(f"Fingerprint 2: {fp2}")

    sim = auditor._calculate_simhash_similarity(fp1, fp2)
    print(f"Similarity: {sim}")
