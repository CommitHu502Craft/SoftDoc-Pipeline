"""
项目扫描管理器
扫描output目录，识别每个项目的状态
"""
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from modules.artifact_naming import first_existing_artifact_path

class ProjectScanner:
    """项目状态扫描器"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
    
    def scan_all_projects(self) -> List[Dict[str, Any]]:
        """扫描所有项目"""
        projects = []
        
        if not self.output_dir.exists():
            return projects
        
        for project_dir in self.output_dir.iterdir():
            if not project_dir.is_dir():
                continue
            
            # 跳过临时目录
            if project_dir.name.startswith('.') or project_dir.name == 'temp':
                continue
            
            project_info = self._scan_project(project_dir)
            if project_info:
                projects.append(project_info)
        
        # 按创建时间倒序
        projects.sort(key=lambda x: x['created_time'], reverse=True)
        return projects
    
    def _scan_project(self, project_dir: Path) -> Dict[str, Any]:
        """扫描单个项目"""
        project_name = project_dir.name
        
        # 检查各阶段文件
        plan_file = project_dir / "project_plan.json"
        
        # HTML在temp_build目录下
        temp_build_base = project_dir.parent.parent / "temp_build"
        html_dir = temp_build_base / project_name / "html"
        
        # 截图在项目目录下
        screenshot_dir = project_dir / "screenshots"

        # 代码目录（aligned_code）
        code_dir = project_dir / "aligned_code"

        # Word文档（支持新旧命名）
        doc_file = first_existing_artifact_path(project_dir, project_name=project_name, artifact_key="manual_docx")

        # PDF文件（支持新旧命名）
        pdf_file = first_existing_artifact_path(project_dir, project_name=project_name, artifact_key="code_pdf")

        # 状态判定
        status = {
            'plan': plan_file.exists(),
            'html': html_dir.exists() and any(html_dir.glob('*.html')),
            'screenshot': screenshot_dir.exists() and any(screenshot_dir.glob('*.png')),
            'code': code_dir.exists() and any(code_dir.rglob('*.*')),
            'document': bool(doc_file),
            'pdf': bool(pdf_file)
        }
        
        # 获取创建时间
        created_time = project_dir.stat().st_ctime
        
        # 读取项目简介（如果plan文件存在）
        description = ""
        if plan_file.exists():
            try:
                with open(plan_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    description = data.get('project_intro', {}).get('description', '')
            except:
                pass
        
        return {
            'name': project_name,
            'path': str(project_dir),
            'status': status,
            'created_time': created_time,
            'created_time_str': datetime.fromtimestamp(created_time).strftime('%Y-%m-%d %H:%M'),
            'description': description,
            'files': {
                'plan': str(plan_file) if plan_file.exists() else None,
                'html_dir': str(html_dir) if html_dir.exists() else None,
                'doc': str(doc_file) if doc_file else None,
                'pdf': str(pdf_file) if pdf_file else None
            }
        }
    
    def get_project_by_name(self, project_name: str) -> Dict[str, Any]:
        """根据名称获取项目信息"""
        project_dir = self.output_dir / project_name
        if project_dir.exists():
            return self._scan_project(project_dir)
        return None
