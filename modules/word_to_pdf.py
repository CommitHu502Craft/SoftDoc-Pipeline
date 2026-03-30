"""
Word文档转PDF模块
支持多种转换方式，适配不同操作系统
"""
import os
import sys
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class WordToPDFConverter:
    """Word转PDF转换器"""

    def __init__(self):
        self.platform = sys.platform

    def convert(self, docx_path: Path, pdf_path: Optional[Path] = None) -> bool:
        """
        将Word文档转换为PDF
        :param docx_path: Word文档路径
        :param pdf_path: PDF输出路径，如果为None则替换扩展名
        :return: 是否成功
        """
        if not docx_path.exists():
            logger.error(f"Word文档不存在: {docx_path}")
            return False

        if pdf_path is None:
            pdf_path = docx_path.with_suffix('.pdf')

        logger.info(f"开始转换: {docx_path.name} -> {pdf_path.name}")

        # 根据平台选择转换方法
        if self.platform == 'win32':
            return self._convert_windows(docx_path, pdf_path)
        elif self.platform in ['linux', 'linux2', 'darwin']:
            return self._convert_linux(docx_path, pdf_path)
        else:
            logger.warning(f"未知平台: {self.platform}，尝试使用docx2pdf")
            return self._convert_docx2pdf(docx_path, pdf_path)

    def _convert_windows(self, docx_path: Path, pdf_path: Path) -> bool:
        """Windows平台转换（使用COM自动化）"""
        try:
            # 方法1: 使用comtypes（推荐）
            try:
                return self._convert_with_comtypes(docx_path, pdf_path)
            except ImportError:
                logger.warning("comtypes未安装，尝试使用win32com")

            # 方法2: 使用win32com
            try:
                return self._convert_with_win32com(docx_path, pdf_path)
            except ImportError:
                logger.warning("win32com未安装，尝试使用docx2pdf")

            # 方法3: 使用docx2pdf
            return self._convert_docx2pdf(docx_path, pdf_path)

        except Exception as e:
            logger.error(f"Windows转换失败: {e}")
            return False

    def _convert_with_comtypes(self, docx_path: Path, pdf_path: Path) -> bool:
        """使用comtypes转换"""
        import time
        word = None
        doc = None

        try:
            import comtypes.client

            logger.info("使用comtypes转换...")

            # 转换为绝对路径
            docx_abs = str(docx_path.absolute())
            pdf_abs = str(pdf_path.absolute())

            # 创建Word应用
            word = comtypes.client.CreateObject('Word.Application')
            word.Visible = False
            word.DisplayAlerts = 0

            # 打开文档（非只读模式，以便更新目录）
            doc = word.Documents.Open(docx_abs, ReadOnly=False)

            # 更新所有域（包括目录）
            try:
                logger.info("更新文档目录...")
                # 更新目录
                for toc in doc.TablesOfContents:
                    toc.Update()
                # 更新所有域
                doc.Fields.Update()
                logger.info("✓ 目录更新完成")
            except Exception as e:
                logger.warning(f"更新目录时出错（可能没有目录）: {e}")

            # 导出为PDF (格式17是PDF)
            doc.SaveAs(pdf_abs, FileFormat=17)

            logger.info(f"✓ 转换成功: {pdf_path.name}")
            return True

        except Exception as e:
            logger.error(f"comtypes转换失败: {e}")
            raise ImportError("comtypes不可用")

        finally:
            # 确保正确释放资源
            try:
                if doc:
                    doc.Close(SaveChanges=0)
            except:
                pass

            try:
                if word:
                    word.Quit()
            except:
                pass

            # 等待 Word 进程完全退出
            time.sleep(0.5)

    def _convert_with_win32com(self, docx_path: Path, pdf_path: Path) -> bool:
        """使用win32com转换"""
        import time
        word = None
        doc = None

        try:
            import win32com.client
            import pythoncom

            # 初始化 COM 线程
            pythoncom.CoInitialize()

            logger.info("使用win32com转换...")

            # 转换为绝对路径
            docx_abs = str(docx_path.absolute())
            pdf_abs = str(pdf_path.absolute())

            # 创建Word应用（使用DispatchEx创建新实例，避免复用卡死的进程）
            word = win32com.client.DispatchEx('Word.Application')
            word.Visible = False
            word.DisplayAlerts = 0  # 禁止弹窗

            # 打开文档（非只读模式，以便更新目录）
            doc = word.Documents.Open(docx_abs, ReadOnly=False)

            # 更新所有域（包括目录）
            try:
                logger.info("更新文档目录...")
                # 更新目录
                for toc in doc.TablesOfContents:
                    toc.Update()
                # 更新所有域
                doc.Fields.Update()
                logger.info("✓ 目录更新完成")
            except Exception as e:
                logger.warning(f"更新目录时出错（可能没有目录）: {e}")

            # 导出为PDF (wdFormatPDF = 17)
            doc.SaveAs2(pdf_abs, FileFormat=17)

            logger.info(f"✓ 转换成功: {pdf_path.name}")
            return True

        except Exception as e:
            logger.error(f"win32com转换失败: {e}")
            raise ImportError("win32com不可用")

        finally:
            # 确保正确释放资源
            try:
                if doc:
                    doc.Close(SaveChanges=0)
            except:
                pass

            try:
                if word:
                    word.Quit()
            except:
                pass

            # 释放 COM 对象
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except:
                pass

            # 等待 Word 进程完全退出
            time.sleep(0.5)

    def _convert_docx2pdf(self, docx_path: Path, pdf_path: Path) -> bool:
        """使用docx2pdf库转换（跨平台）"""
        try:
            from docx2pdf import convert

            logger.info("使用docx2pdf转换...")

            # 转换
            convert(str(docx_path), str(pdf_path))

            if pdf_path.exists():
                logger.info(f"✓ 转换成功: {pdf_path.name}")
                return True
            else:
                logger.error("转换失败：PDF文件未生成")
                return False

        except ImportError:
            logger.error("docx2pdf未安装，请运行: pip install docx2pdf")
            return False
        except Exception as e:
            logger.error(f"docx2pdf转换失败: {e}")
            return False

    def _convert_linux(self, docx_path: Path, pdf_path: Path) -> bool:
        """Linux/Mac平台转换"""
        try:
            # 方法1: 使用libreoffice（最常用）
            try:
                return self._convert_with_libreoffice(docx_path, pdf_path)
            except:
                logger.warning("LibreOffice不可用，尝试使用docx2pdf")

            # 方法2: 使用docx2pdf
            return self._convert_docx2pdf(docx_path, pdf_path)

        except Exception as e:
            logger.error(f"Linux转换失败: {e}")
            return False

    def _convert_with_libreoffice(self, docx_path: Path, pdf_path: Path) -> bool:
        """使用LibreOffice转换"""
        import subprocess

        logger.info("使用LibreOffice转换...")

        try:
            # 查找libreoffice命令
            lo_cmd = None
            for cmd in ['libreoffice', 'soffice']:
                try:
                    subprocess.run([cmd, '--version'],
                                 capture_output=True, check=True)
                    lo_cmd = cmd
                    break
                except:
                    continue

            if not lo_cmd:
                raise FileNotFoundError("未找到LibreOffice")

            # 执行转换
            # --headless: 无GUI模式
            # --convert-to pdf: 转换为PDF
            # --outdir: 输出目录
            result = subprocess.run([
                lo_cmd,
                '--headless',
                '--convert-to', 'pdf',
                '--outdir', str(pdf_path.parent),
                str(docx_path)
            ], capture_output=True, text=True, timeout=60)

            if result.returncode == 0 and pdf_path.exists():
                logger.info(f"✓ 转换成功: {pdf_path.name}")
                return True
            else:
                logger.error(f"LibreOffice转换失败: {result.stderr}")
                return False

        except FileNotFoundError:
            logger.error("LibreOffice未安装")
            raise
        except subprocess.TimeoutExpired:
            logger.error("转换超时")
            return False
        except Exception as e:
            logger.error(f"LibreOffice转换失败: {e}")
            raise


def convert_word_to_pdf(docx_path: Path, pdf_path: Optional[Path] = None) -> bool:
    """
    便捷函数：将Word文档转换为PDF
    :param docx_path: Word文档路径
    :param pdf_path: PDF输出路径（可选）
    :return: 是否成功
    """
    converter = WordToPDFConverter()
    return converter.convert(docx_path, pdf_path)


def batch_convert_word_to_pdf(docx_dir: Path, pdf_dir: Optional[Path] = None) -> dict:
    """
    批量转换Word文档为PDF
    :param docx_dir: Word文档目录
    :param pdf_dir: PDF输出目录（可选，默认同目录）
    :return: {文件名: 是否成功}
    """
    if pdf_dir is None:
        pdf_dir = docx_dir
    else:
        pdf_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    converter = WordToPDFConverter()

    # 查找所有docx文件
    docx_files = list(docx_dir.glob('*.docx'))
    logger.info(f"找到 {len(docx_files)} 个Word文档")

    for docx_file in docx_files:
        # 跳过临时文件
        if docx_file.name.startswith('~$'):
            continue

        pdf_file = pdf_dir / docx_file.with_suffix('.pdf').name
        success = converter.convert(docx_file, pdf_file)
        results[docx_file.name] = success

    # 统计
    success_count = sum(1 for v in results.values() if v)
    logger.info(f"转换完成: {success_count}/{len(results)} 成功")

    return results


# 命令行使用示例
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        docx_path = Path(sys.argv[1])
        pdf_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

        logging.basicConfig(level=logging.INFO)

        success = convert_word_to_pdf(docx_path, pdf_path)

        if success:
            print("✓ 转换成功")
            sys.exit(0)
        else:
            print("✗ 转换失败")
            sys.exit(1)
    else:
        print(__doc__)
        print("\n使用方法:")
        print("  python word_to_pdf.py input.docx [output.pdf]")
        print("\n自动检测:")
        print("  - Windows: 使用Microsoft Word COM自动化")
        print("  - Linux/Mac: 使用LibreOffice或docx2pdf")
        print("\n依赖安装:")
        print("  pip install docx2pdf  # 跨平台方案（推荐）")
        print("  pip install pywin32   # Windows方案")
        print("  apt install libreoffice  # Linux方案")
