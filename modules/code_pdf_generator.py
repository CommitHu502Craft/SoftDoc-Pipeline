"""
源代码鉴别材料 PDF 生成器
基于 reportlab 实现标准的源代码 PDF 排版，符合软著申请要求
"""
import logging
import random
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Dict
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CodePDFGenerator:
    """
    源代码 PDF 生成器。

    维护目标：
    1) 生成稳定、可交付的 60 页源码 PDF（3000 行上下）。
    2) 优先保留 AI 改写内容在首尾区间，提高软著材料差异化。
    3) 在代码量不足时自动补齐，避免人工返工。
    """

    # 排版参数
    LINES_PER_PAGE = 50  # 每页固定50行
    MAX_TOTAL_LINES = 3000  # 超过则截取,确保生成 60 页 PDF (50行/页×60页=3000行)
    HEAD_TAIL_SLICE_LINES = 1500  # 软著常用规则：前1500行 + 后1500行
    FONT_SIZE = 9  # 字体大小
    LINE_SPACING = 1.2  # 行间距倍数

    # 页面边距 (mm)
    MARGIN_TOP = 20
    MARGIN_BOTTOM = 20
    MARGIN_LEFT = 20
    MARGIN_RIGHT = 20

    # 代码文件扩展名映射
    CODE_EXT_MAP = {
        '.py': 'Python', '.java': 'Java', '.js': 'JavaScript', '.ts': 'TypeScript',
        '.jsx': 'React', '.tsx': 'React TS', '.cpp': 'C++', '.c': 'C',
        '.h': 'C/C++ Header', '.hpp': 'C++ Header', '.cs': 'C#', '.go': 'Go',
        '.rs': 'Rust', '.php': 'PHP', '.rb': 'Ruby', '.swift': 'Swift',
        '.kt': 'Kotlin', '.html': 'HTML', '.css': 'CSS', '.sql': 'SQL',
        '.yml': 'YAML', '.yaml': 'YAML', '.xml': 'XML', '.sh': 'Shell',
        '.md': 'Markdown', '.json': 'JSON', '.vue': 'Vue', '.bat': 'Batch'
    }

    # 允许的扩展名集合
    CODE_EXTENSIONS = set(CODE_EXT_MAP.keys())

    # 文件优先级分组 (数字越小优先级越高)
    # 后端业务代码优先，前端/配置文件靠后
    FILE_PRIORITY = {
        # 优先级 1: 核心后端代码
        '.java': 1, '.py': 1, '.go': 1, '.php': 1, '.cs': 1,
        '.rb': 1, '.kt': 1, '.swift': 1, '.rs': 1,
        # 优先级 2: C/C++ 代码
        '.c': 2, '.cpp': 2, '.h': 2, '.hpp': 2,
        # 优先级 3: SQL 数据库
        '.sql': 3,
        # 优先级 4: 前端脚本 (非HTML)
        '.js': 4, '.ts': 4, '.jsx': 4, '.tsx': 4, '.vue': 4,
        # 优先级 5: 样式文件
        '.css': 5,
        # 优先级 6: 配置文件
        '.yml': 6, '.yaml': 6, '.xml': 6, '.json': 6,
        # 优先级 7: HTML (最后)
        '.html': 7,
        # 优先级 8: 其他
        '.sh': 8, '.bat': 8, '.md': 8,
    }

    # 模拟元数据 (Phase 3: Enhanced Identity Pool)
    AUTHORS = [
        "Zhang Wei", "Wang Qiang", "Li Ming", "Liu Yang", "Chen Jie",
        "Admin", "Administrator", "Developer", "IT_Dept", "System",
        "Soft_Dev_Team", "R&D_Center"
    ]
    PRODUCERS = [
        'Microsoft® Word 2019', 'WPS Office', 'Adobe Acrobat Pro DC',
        'iText 7.1.15', 'LibreOffice 7.3'
    ]
    CREATORS = [
        'Microsoft® Word 2019', 'WPS Office', 'Microsoft® Word 2016',
        'Writer', 'Acrobat PDFMaker 21 for Word'
    ]

    def __init__(
        self,
        project_name: str,
        version: str = "V1.0",
        html_dir: str = None,
        include_html: bool = False
    ):
        """
        初始化PDF生成器

        Args:
            project_name: 项目名称
            version: 版本号
            html_dir: HTML 文件目录（可选）
            include_html: 是否把 HTML 文件纳入源码 PDF（默认关闭）
        """
        self.project_name = project_name
        self.version = version
        self.html_dir = html_dir
        self.include_html = include_html
        self.page_width, self.page_height = A4

        # 注册中文字体
        self._register_chinese_font()

        # 计算实际可用高度和行高
        usable_height = self.page_height - (self.MARGIN_TOP + self.MARGIN_BOTTOM) * mm - 30  # 减去页眉页脚
        self.line_height = usable_height / self.LINES_PER_PAGE

        logger.info(f"PDF生成器初始化: 每页{self.LINES_PER_PAGE}行, 行高{self.line_height:.2f}pt")

    def _get_pdf_date_format(self, dt: datetime) -> str:
        """生成 PDF 标准日期格式 D:YYYYMMDDHHmmSS"""
        return f"D:{dt.strftime('%Y%m%d%H%M%S')}+08'00'"
    
    def _register_chinese_font(self):
        """注册中文字体"""
        try:
            # Windows 系统字体路径
            font_paths = [
                "C:/Windows/Fonts/simsun.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",  # Linux
            ]
            
            for font_path in font_paths:
                if Path(font_path).exists():
                    pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
                    logger.info(f"成功注册中文字体: {font_path}")
                    return
            
            logger.warning("未找到中文字体，将使用默认字体（可能无法显示中文）")
        except Exception as e:
            logger.warning(f"字体注册失败: {e}，将使用默认字体")
    
    def _clean_code_line(self, line: str) -> str:
        """
        清洗单行代码
        
        Args:
            line: 原始代码行
            
        Returns:
            清洗后的代码行
        """
        # 移除 TODO 标记
        line = line.replace('TODO', '')
        line = line.replace('FIXME', '')
        
        # 移除所有缩进（前导空格）
        line = line.lstrip()
        
        # 移除行尾空格
        line = line.rstrip()
        
        return line
    
    def _wrap_long_line(self, line: str, max_length: int = 90) -> List[str]:
        """
        智能换行处理过长的代码行，避免 PDF 截断
        
        Args:
            line: 代码行
            max_length: 每行最大字符数（根据 PDF 页面宽度设定）
            
        Returns:
            换行后的行列表
        """
        if len(line) <= max_length:
            return [line]
        
        # 定义安全的换行点（按优先级排序）
        safe_breaks = [
            ', ',   # 逗号+空格
            '; ',   # 分号+空格
            ' && ', # 逻辑运算符
            ' || ',
            ' + ',  # 算术运算符
            ' - ',
            ' * ',
            ' = ',  # 赋值
            ' ',    # 普通空格
            ',',    # 逗号（不带空格）
            ';',    # 分号（不带空格）
        ]
        
        result = []
        remaining = line
        
        while len(remaining) > max_length:
            # 尝试找到最后一个安全换行点
            break_pos = -1
            for pattern in safe_breaks:
                pos = remaining.rfind(pattern, 0, max_length)
                if pos > 20:  # 至少保留 20 个字符，避免过短
                    break_pos = pos + len(pattern)
                    break
            
            if break_pos > 0:
                # 在安全点断行
                result.append(remaining[:break_pos].rstrip())
                remaining = remaining[break_pos:].lstrip()
            else:
                # 没有安全点，在最大长度处硬截断
                result.append(remaining[:max_length])
                remaining = remaining[max_length:]
        
        # 添加剩余部分
        if remaining:
            result.append(remaining)
        
        return result
    
    def _collect_code_lines(self, code_dir: str, force_include_html: bool = False) -> List[str]:
        """
        收集代码目录中的所有代码行

        排序策略：
        - 优先读取 AI 重写文件（来自 project_metadata.json 的 process_mode=ai_rewrite）
        - 其次读取仅混淆文件（process_mode=obfuscation）
        - 最后读取未标注文件（兜底）
        - 默认不收录 HTML 文件，避免源码 PDF 混入页面代码
        - 当 force_include_html=True 时，允许纳入 HTML 用于“行数不足补充”

        Args:
            code_dir: 主代码目录路径
            force_include_html: 是否强制纳入 HTML（用于行数兜底）

        Returns:
            代码行列表（已按首尾优化排序）

        注意：这里的排序不是“阅读友好”，而是服务软著截断策略。
        目标是让真正关键的 AI 改写代码更容易进入前1500/后1500区间。
        """
        code_path = Path(code_dir)

        # 收集所有代码文件（从主代码目录）
        # 默认排除 .html，避免源码 PDF 混入前端页面代码
        include_html_sources = self.include_html or force_include_html
        allowed_exts = set(self.CODE_EXTENSIONS)
        if not include_html_sources:
            allowed_exts.discard('.html')

        code_files = [
            file_path for file_path in code_path.rglob("*")
            if file_path.is_file() and file_path.suffix in allowed_exts
        ]

        # 可选：收集 HTML 目录（默认关闭）
        if include_html_sources and self.html_dir:
            html_path = Path(self.html_dir)
            if html_path.exists():
                html_files = [
                    file_path for file_path in html_path.glob("*.html")
                    if file_path.is_file()
                ]
                code_files.extend(html_files)
                logger.info(f"从 HTML 目录收集了 {len(html_files)} 个文件")

        # 去重（避免 code_dir 与 html_dir 重叠导致重复读取）
        dedup_files = []
        seen = set()
        for fp in code_files:
            try:
                key = str(fp.resolve())
            except Exception:
                key = str(fp)
            if key in seen:
                continue
            seen.add(key)
            dedup_files.append(fp)
        code_files = sorted(dedup_files, key=lambda p: str(p).lower())

        # 按元数据划分文件顺序：AI重写 -> 仅混淆 -> 兜底
        ai_rewrite_set = set()
        obfuscation_set = set()
        meta_path = code_path / "project_metadata.json"
        if meta_path.exists():
            try:
                import json
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                for item in meta.get("file_process", []):
                    rel = str(item.get("file_path", "")).replace("\\", "/")
                    if not rel:
                        continue
                    mode = item.get("process_mode", "")
                    if mode == "ai_rewrite":
                        ai_rewrite_set.add(rel)
                    else:
                        obfuscation_set.add(rel)
            except Exception as e:
                logger.warning(f"读取项目元数据失败，将回退关键词分组: {e}")
                # 没有 metadata 时不能中断流程，必须继续走关键词兜底，保证可出 PDF。

        CORE_KEYWORDS = ['controller', 'service', 'router', 'handler', 'view', 'api']
        ai_files = []
        obf_files = []
        fallback_files = []

        for f in code_files:
            try:
                rel = str(f.relative_to(code_path)).replace("\\", "/")
            except ValueError:
                rel = f.name

            if rel in ai_rewrite_set:
                ai_files.append(f)
            elif rel in obfuscation_set:
                obf_files.append(f)
            else:
                # 元数据缺失时，用关键词兜底：核心归 AI 优先，其他归基础
                is_core = any(kw in f.name.lower() for kw in CORE_KEYWORDS)
                if is_core:
                    ai_files.append(f)
                else:
                    fallback_files.append(f)

        # 未在 metadata 中声明的 obfuscation 文件，归为 obf_files
        # （避免遗漏辅助代码）
        for f in fallback_files[:]:
            try:
                rel = str(f.relative_to(code_path)).replace("\\", "/")
            except ValueError:
                rel = f.name
            if rel in obfuscation_set:
                obf_files.append(f)
                fallback_files.remove(f)

        # 使用项目级固定种子，保证同项目重复导出时顺序可复现（便于审计追踪）。
        seed = int(hashlib.md5(f"{self.project_name}:{self.version}".encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)
        rng.shuffle(ai_files)
        rng.shuffle(obf_files)
        rng.shuffle(fallback_files)

        logger.info(
            f"文件分组: AI重写={len(ai_files)}个, 仅混淆={len(obf_files)}个, 兜底={len(fallback_files)}个"
        )

        # 读取文件内容
        def read_file_lines(file_path: Path) -> List[str]:
            """读取单个文件并返回处理后的行"""
            lines = []
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_lines = f.readlines()

                # 计算相对路径
                if self.html_dir and file_path.parent == Path(self.html_dir):
                    relative_path = file_path.name
                else:
                    try:
                        relative_path = file_path.relative_to(code_path)
                    except ValueError:
                        relative_path = file_path.name

                # 获取语言类型
                file_ext = file_path.suffix.lower()
                language = self.CODE_EXT_MAP.get(file_ext, 'Code')

                # 文件头
                # 文件分隔头用于 PDF 审阅时快速定位来源，也能提升材料可读性。
                lines.append(f"\n# ========== File: {relative_path} | Type: {language} ==========\n")

                # 清洗并添加代码行
                for line in raw_lines:
                    cleaned = self._clean_code_line(line)
                    if cleaned.strip():
                        wrapped_lines = self._wrap_long_line(cleaned)
                        lines.extend([l + '\n' for l in wrapped_lines])

            except Exception as e:
                logger.warning(f"无法读取 {file_path}: {e}")

            return lines

        # 读取 AI 重写文件
        ai_lines = []
        for f in ai_files:
            ai_lines.extend(read_file_lines(f))

        # 读取仅混淆文件
        obf_lines = []
        for f in obf_files:
            obf_lines.extend(read_file_lines(f))

        # 读取兜底文件
        fallback_lines = []
        for f in fallback_files:
            fallback_lines.extend(read_file_lines(f))

        # 软著取“前1500+后1500”时，为提高 AI 改写命中率，
        # 将 AI 行按行数一分为二，分别放到最前和最后。
        ai_front_cut = len(ai_lines) // 2
        ai_front_lines = ai_lines[:ai_front_cut]
        ai_tail_lines = ai_lines[ai_front_cut:]
        # 排布顺序是核心策略：AI前段 -> 其他代码 -> AI后段。
        # 这样截取首尾时，AI 改写内容在两端都能被覆盖。
        all_lines = ai_front_lines + obf_lines + fallback_lines + ai_tail_lines

        logger.info(
            f"代码行排布: AI前段={len(ai_front_lines)}行, 仅混淆={len(obf_lines)}行, "
            f"兜底={len(fallback_lines)}行, AI后段={len(ai_tail_lines)}行"
        )
        logger.info(f"总计 {len(all_lines)} 行代码")

        return all_lines
    
    def _truncate_lines(self, lines: List[str]) -> Tuple[List[str], bool]:
        """
        截取代码行（最多3000行）

        当前策略：
        - 文件顺序已在 _collect_code_lines 中处理为 AI前段 -> 混淆/兜底 -> AI后段
        - 当超过3000行时，按软著常用规则取“前1500行 + 后1500行”

        Args:
            lines: 所有代码行（已按首尾优化排布）

        Returns:
            (截取后的代码行, 是否进行了截取)

        合规策略说明：
        - >3000 行：严格前1500 + 后1500。
        - <3000 行：允许重复补齐，优先保证页数满足提交要求。
        """
        total = len(lines)

        if total < self.MAX_TOTAL_LINES:
            # 如果代码不足3000行，循环复用全部代码，避免只重复开头片段
            logger.warning(f"代码行数不足 ({total} < {self.MAX_TOTAL_LINES})，将循环重复代码以满足60页要求")
            original_lines = lines.copy()
            idx = 0
            while len(lines) < self.MAX_TOTAL_LINES and original_lines:
                lines.append(original_lines[idx % total])
                idx += 1
            logger.info(f"填充完成: {total} 行 -> {len(lines)} 行")
            return lines[:self.MAX_TOTAL_LINES], False

        if total == self.MAX_TOTAL_LINES:
            return lines, False

        head_count = min(self.HEAD_TAIL_SLICE_LINES, self.MAX_TOTAL_LINES // 2)
        tail_count = self.MAX_TOTAL_LINES - head_count
        head = lines[:head_count]
        tail = lines[-tail_count:]
        truncated = head + tail
        logger.info(
            f"代码截取: {total} 行 -> 前 {head_count} 行 + 后 {tail_count} 行（首尾策略）"
        )

        return truncated, True
    
    def _draw_header_footer(self, c: canvas.Canvas, page_num: int, total_pages: int):
        """
        绘制页眉页脚
        
        Args:
            c: Canvas 对象
            page_num: 当前页码
            total_pages: 总页数
        """
        try:
            c.setFont('ChineseFont', 10)
        except:
            c.setFont('Helvetica', 10)
        
        # 页眉左侧：项目名称+版本
        header_left = f"{self.project_name} {self.version}"
        c.drawString(self.MARGIN_LEFT * mm, self.page_height - 15 * mm, header_left)
        
        # 页眉右侧：页码
        header_right = f"第 {page_num} 页 / 共 {total_pages} 页"
        c.drawRightString(
            self.page_width - self.MARGIN_RIGHT * mm,
            self.page_height - 15 * mm,
            header_right
        )
    
    def _truncate_long_line(self, line: str, max_chars: int = 100) -> str:
        """截断过长的行"""
        if len(line) > max_chars:
            return line[:max_chars-3] + '...'
        return line
    
    def generate(self, code_dir: str, output_path: str) -> bool:
        """
        生成源代码 PDF
        
        Args:
            code_dir: 代码目录路径
            output_path: 输出PDF路径
            
        Returns:
            是否成功生成
        """
        try:
            logger.info(f"开始生成源代码PDF: {output_path}")

            # 1. 收集代码行
            all_lines = self._collect_code_lines(code_dir)

            # 代码目录为空时，先尝试 HTML 兜底；仍为空再失败。
            if not all_lines and not self.include_html:
                logger.info("主代码目录无可用代码，尝试仅使用 HTML 页面兜底...")
                all_lines = self._collect_code_lines(code_dir, force_include_html=True)

            if not all_lines:
                logger.error("未找到任何代码或可补位的 HTML 文件")
                return False
            
            # 2. 行数兜底：
            #    先纯代码；不足 3000 时纳入 HTML；仍不足再重复补齐。
            # 这么做是为了最大化“真实代码占比”，HTML 仅作为行数不足时的次选补充。
            if len(all_lines) < self.MAX_TOTAL_LINES and not self.include_html:
                logger.info("代码行数不足3000，尝试纳入 HTML 页面补充行数...")
                all_lines_with_html = self._collect_code_lines(code_dir, force_include_html=True)
                if len(all_lines_with_html) > len(all_lines):
                    logger.info(
                        f"HTML 补充生效: {len(all_lines)} 行 -> {len(all_lines_with_html)} 行"
                    )
                    all_lines = all_lines_with_html
                else:
                    logger.info("未获取到额外 HTML 行，继续使用现有代码行")

            # 3. 截取代码（超过3000时首尾截取，不足时在 _truncate_lines 中重复补齐）
            lines, was_truncated = self._truncate_lines(all_lines)

            # 4. 计算总页数
            total_pages = (len(lines) + self.LINES_PER_PAGE - 1) // self.LINES_PER_PAGE
            logger.info(f"总行数: {len(lines)}, 总页数: {total_pages}")

            # 5. 创建 PDF
            c = canvas.Canvas(output_path, pagesize=A4)

            # 设置随机元数据 (Phase 3: Deep Camouflage)
            try:
                author = random.choice(self.AUTHORS)
                creator = random.choice(self.CREATORS)
                producer = random.choice(self.PRODUCERS)

                # 生成随机创建时间 (过去 30-90 天)
                days_ago = random.randint(30, 90)
                creation_date = datetime.now() - timedelta(days=days_ago)
                mod_date = creation_date + timedelta(days=random.randint(1, 10))

                # PDF 格式日期
                pdf_creation_date = self._get_pdf_date_format(creation_date)
                pdf_mod_date = self._get_pdf_date_format(mod_date)

                c.setAuthor(author)
                c.setCreator(creator)
                c.setTitle(f"{self.project_name} Source Code")
                c.setSubject(f"{self.project_name} v{self.version} 源代码鉴别材料")

                # 尝试修改 PDF 元数据字典
                if hasattr(c, '_doc'):
                    # Producer
                    c._doc.info.producer = producer
                    # Dates
                    c._doc.info.creationDate = pdf_creation_date
                    c._doc.info.modDate = pdf_mod_date

            except Exception as e:
                logger.warning(f"设置 PDF 元数据失败: {e}")

            # 6. 逐页渲染
            for page_num in range(1, total_pages + 1):
                # 绘制页眉页脚
                self._draw_header_footer(c, page_num, total_pages)
                
                # 设置代码字体（优先使用中文字体）
                try:
                    c.setFont('ChineseFont', self.FONT_SIZE)
                except:
                    c.setFont('Courier', self.FONT_SIZE)
                
                # 计算当前页的起始和结束行
                start_line = (page_num - 1) * self.LINES_PER_PAGE
                end_line = min(start_line + self.LINES_PER_PAGE, len(lines))
                
                # 渲染代码行
                # 这里按固定行高渲染，确保每页行数稳定，便于送审材料核对。
                y_position = self.page_height - (self.MARGIN_TOP + 10) * mm
                
                for i in range(start_line, end_line):
                    line_text = lines[i].rstrip('\n')
                    
                    # 截断过长的行
                    line_text = self._truncate_long_line(line_text, max_chars=95)
                    
                    try:
                        c.drawString(self.MARGIN_LEFT * mm, y_position, line_text)
                    except:
                        # 如果包含无法编码的字符，跳过
                        c.drawString(self.MARGIN_LEFT * mm, y_position, "# [编码错误的行]")
                    
                    y_position -= self.line_height
                
                # 换页
                c.showPage()
                
                if page_num % 10 == 0:
                    logger.info(f"已渲染 {page_num}/{total_pages} 页")
            
            # 7. 保存 PDF
            c.save()
            
            file_size = Path(output_path).stat().st_size / 1024 / 1024
            logger.info(f"✓ PDF生成成功: {output_path} ({file_size:.2f} MB)")
            
            if was_truncated:
                logger.warning(
                    f"⚠ 代码已按首尾策略截取（前{self.HEAD_TAIL_SLICE_LINES}+后{self.HEAD_TAIL_SLICE_LINES}）"
                )
            
            return True
            
        except Exception as e:
            logger.error(f"✗ PDF生成失败: {e}")
            import traceback
            traceback.print_exc()
            return False


def generate_code_pdf(
    project_name: str,
    code_dir: str,
    output_path: str,
    version: str = "V1.0",
    html_dir: str = None,
    include_html: bool = False
) -> bool:
    """
    便捷函数：生成源代码 PDF
    
    Args:
        project_name: 项目名称
        code_dir: 代码目录路径
        output_path: 输出PDF路径
        version: 版本号
        html_dir: HTML 文件目录（可选）
        include_html: 是否将 HTML 纳入源码 PDF（默认否）
        
    Returns:
        是否成功生成
    """
    generator = CodePDFGenerator(project_name, version, html_dir, include_html=include_html)
    return generator.generate(code_dir, output_path)
