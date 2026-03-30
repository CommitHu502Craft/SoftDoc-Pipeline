"""
简易项目数据库 (基于 JSON 文件持久化)
"""
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from threading import Lock

from config import BASE_DIR, OUTPUT_DIR
from modules.artifact_naming import candidate_artifact_paths
from modules.project_charter import (
    normalize_project_charter,
    summarize_project_charter,
    validate_project_charter,
)

logger = logging.getLogger(__name__)


class ProjectDatabase:
    """项目数据管理器"""

    def __init__(self):
        self.db_path = BASE_DIR / "data" / "projects.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._load()

    def _load(self):
        """加载数据库"""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {"projects": {}}
        else:
            self._data = {"projects": {}}

    def _save(self):
        """保存数据库"""
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def create_project(self, name: str, charter: Optional[Dict] = None) -> Dict:
        """创建新项目"""
        with self._lock:
            # 检查是否已存在同名项目
            for p in self._data["projects"].values():
                if p["name"] == name:
                    return p  # 返回已存在的项目

            normalized_charter = normalize_project_charter(charter or {}, project_name=name)
            charter_errors = validate_project_charter(normalized_charter)
            charter_completed = len(charter_errors) == 0
            project_id = str(uuid.uuid4())[:8]
            project = {
                "id": project_id,
                "name": name,
                "progress": 0,
                "status": "idle",
                "created_at": datetime.now().strftime("%Y-%m-%d"),
                "current_step": None,
                "project_charter": normalized_charter,
                "charter_completed": charter_completed,
                "charter_summary": summarize_project_charter(normalized_charter),
                "files": {
                    "plan": False,
                    "spec": False,
                    "html": False,
                    "screenshots": False,
                    "code": False,
                    "verify": False,
                    "document": False,
                    "pdf": False,
                    "freeze": False,
                }
            }
            self._data["projects"][project_id] = project
            self._save()
            return project

    def create_projects_batch(self, names: List[str]) -> List[Dict]:
        """批量创建项目"""
        created = []
        for name in names:
            name = name.strip()
            if name:
                project = self.create_project(name)
                created.append(project)
        return created

    def get_project(self, project_id: str) -> Optional[Dict]:
        """获取单个项目"""
        return self._data["projects"].get(project_id)

    def get_all_projects(self) -> List[Dict]:
        """获取所有项目（过滤掉已提交的）"""
        active_projects = []
        to_remove = []

        # 先复制一份数据，避免在遍历时被其他线程修改
        with self._lock:
            projects_copy = list(self._data["projects"].items())

        for project_id, project in projects_copy:
            name = project["name"]
            project_dir = OUTPUT_DIR / name
            submitted_dir = OUTPUT_DIR / "已提交" / name

            try:
                # 如果项目在"已提交"文件夹，不显示
                if submitted_dir.exists():
                    continue

                # 如果项目目录存在，同步文件状态
                if project_dir.exists():
                    # 优化：只有非运行状态才同步文件（避免频繁I/O）
                    # 运行中的项目状态由 task_manager 更新，无需扫描文件系统
                    current_status = project.get("status", "idle")
                    if current_status not in ["running"]:
                        self._sync_file_status(project)
                    active_projects.append(project)
                else:
                    # 项目目录不存在
                    status = project.get("status", "idle")

                    # 以下情况仍然显示项目：
                    # 1. 新项目（还没开始执行）
                    # 2. 正在运行中（目录可能还在创建）
                    # 3. 出错状态（让用户看到错误）
                    if status in ["idle", "running", "error"]:
                        active_projects.append(project)
                    else:
                        # 已完成但目录被删了，从数据库移除
                        to_remove.append(project_id)
            except Exception as e:
                # 文件系统操作失败时，仍然显示项目
                logger.warning(f"检查项目 {name} 时出错: {e}")
                active_projects.append(project)

        # 清理已删除的项目记录（单独获取锁，避免长时间持有）
        if to_remove:
            with self._lock:
                for pid in to_remove:
                    if pid in self._data["projects"]:
                        del self._data["projects"][pid]
                self._save()

        return active_projects

    def update_project(self, project_id: str, updates: Dict) -> Optional[Dict]:
        """更新项目"""
        with self._lock:
            if project_id not in self._data["projects"]:
                return None
            if "project_charter" in updates:
                name = self._data["projects"][project_id].get("name", "")
                normalized_charter = normalize_project_charter(updates.get("project_charter") or {}, project_name=name)
                updates["project_charter"] = normalized_charter
                updates["charter_summary"] = summarize_project_charter(normalized_charter)
                updates["charter_completed"] = len(validate_project_charter(normalized_charter)) == 0
            self._data["projects"][project_id].update(updates)
            self._save()
            return self._data["projects"][project_id]

    def delete_project(self, project_id: str) -> bool:
        """删除项目"""
        with self._lock:
            if project_id in self._data["projects"]:
                del self._data["projects"][project_id]
                self._save()
                return True
            return False

    def _sync_file_status(self, project: Dict):
        """同步检查项目文件是否存在"""
        name = project["name"]
        project_dir = OUTPUT_DIR / name
        submitted_dir = OUTPUT_DIR / "已提交" / name

        # 确保 files 字典存在
        if "files" not in project:
            project["files"] = {
                "plan": False,
                "spec": False,
                "html": False,
                "screenshots": False,
                "code": False,
                "verify": False,
                "document": False,
                "pdf": False,
                "freeze": False,
            }

        # 检查是否已移动到"已提交"文件夹
        if submitted_dir.exists() and not project_dir.exists():
            project["status"] = "submitted"
            project["progress"] = 100
            project["files"] = {
                "plan": True,
                "spec": True,
                "html": True,
                "screenshots": True,
                "code": True,
                "verify": True,
                "document": True,
                "pdf": True,
                "freeze": True,
            }
            return

        # 如果项目目录不存在，保持当前状态（running/error 不变）
        if not project_dir.exists():
            current_status = project.get("status", "idle")
            # 只有非运行状态才重置为 idle
            if current_status not in ["running", "error"]:
                project["status"] = "idle"
                project["progress"] = 0
                project["files"] = {
                    "plan": False,
                    "spec": False,
                    "html": False,
                    "screenshots": False,
                    "code": False,
                    "verify": False,
                    "document": False,
                    "pdf": False,
                    "freeze": False,
                }
            return

        # 检查各类文件 - 只检查项目专属目录内的文件
        # plan: 检查项目目录下的 project_plan.json
        project["files"]["plan"] = (project_dir / "project_plan.json").exists()
        project["files"]["spec"] = (project_dir / "project_executable_spec.json").exists()

        # html: 检查临时构建目录
        html_dir = BASE_DIR / "temp_build" / name / "html"
        project["files"]["html"] = html_dir.exists() and any(html_dir.glob("*.html"))

        # screenshots: 检查截图目录
        screenshot_dir = project_dir / "screenshots"
        project["files"]["screenshots"] = screenshot_dir.exists() and any(screenshot_dir.glob("*.png"))

        # code: 检查代码目录
        code_dir = project_dir / "aligned_code"
        project["files"]["code"] = code_dir.exists() and any(code_dir.rglob("*.*"))

        # verify: 检查运行验证报告（以存在为准）
        project["files"]["verify"] = (project_dir / "runtime_verification_report.json").exists()

        # document: 检查 Word 文档（支持新旧命名）
        project["files"]["document"] = any(
            p.exists()
            for p in candidate_artifact_paths(project_dir, project_name=name, artifact_key="manual_docx")
        )

        # pdf: 检查源码 PDF（支持新旧命名）
        project["files"]["pdf"] = any(
            p.exists()
            for p in candidate_artifact_paths(project_dir, project_name=name, artifact_key="code_pdf")
        )

        # freeze: 检查冻结包（支持新旧命名）
        project["files"]["freeze"] = any(
            p.exists()
            for p in candidate_artifact_paths(project_dir, project_name=name, artifact_key="freeze_zip")
        )

        # 根据文件状态更新项目整体状态
        all_files = project["files"]
        if all(all_files.values()):
            # 所有文件都存在才是已完成
            if project.get("status") != "running":
                project["status"] = "completed"
                project["progress"] = 100
        elif any(all_files.values()):
            # 部分文件存在是进行中
            if project.get("status") not in ["running", "error"]:
                project["status"] = "idle"
                # 计算进度
                completed_count = sum(1 for v in all_files.values() if v)
                project["progress"] = int(completed_count / len(all_files) * 100)
        else:
            # 没有文件是待处理
            if project.get("status") not in ["running", "error"]:
                project["status"] = "idle"
                project["progress"] = 0


# ==================== 账号数据库 ====================

class AccountDatabase:
    """账号数据管理器"""

    def __init__(self):
        self.db_path = BASE_DIR / "data" / "accounts.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._load()

    def _load(self):
        """加载数据库"""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {"accounts": {}}
        else:
            self._data = {"accounts": {}}

    def _save(self):
        """保存数据库"""
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def create_account(self, username: str, password: str = "", description: str = "") -> Dict:
        """创建新账号"""
        with self._lock:
            account_id = str(uuid.uuid4())[:8]
            account = {
                "id": account_id,
                "username": username,
                "password": password,
                "description": description,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._data["accounts"][account_id] = account
            self._save()
            return account

    def get_account(self, account_id: str) -> Optional[Dict]:
        """获取单个账号"""
        return self._data["accounts"].get(account_id)

    def get_all_accounts(self) -> List[Dict]:
        """获取所有账号"""
        return list(self._data["accounts"].values())

    def update_account(self, account_id: str, updates: Dict) -> Optional[Dict]:
        """更新账号"""
        with self._lock:
            if account_id not in self._data["accounts"]:
                return None
            self._data["accounts"][account_id].update(updates)
            self._save()
            return self._data["accounts"][account_id]

    def delete_account(self, account_id: str) -> bool:
        """删除账号"""
        with self._lock:
            if account_id in self._data["accounts"]:
                del self._data["accounts"][account_id]
                self._save()
                return True
            return False


# ==================== 提交队列数据库 ====================

class SubmitQueueDatabase:
    """提交队列数据管理器"""

    def __init__(self):
        self.db_path = BASE_DIR / "data" / "submit_queue.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._load()
        self.is_running = False

    def _load(self):
        """加载数据库"""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {"queue": []}
        else:
            self._data = {"queue": []}

    def _save(self):
        """保存数据库"""
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def add_to_queue(self, project_id: str, project_name: str) -> Dict:
        """添加到队列"""
        with self._lock:
            item_id = str(uuid.uuid4())[:8]
            item = {
                "id": item_id,
                "project_id": project_id,
                "project_name": project_name,
                "status": "pending",
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "started_at": None,
                "completed_at": None,
                "error": None,
            }
            self._data["queue"].append(item)
            self._save()
            return item

    def get_queue(self) -> List[Dict]:
        """获取队列"""
        return self._data["queue"]

    def get_item(self, item_id: str) -> Optional[Dict]:
        """获取队列项"""
        for item in self._data["queue"]:
            if item["id"] == item_id:
                return item
        return None

    def update_item(self, item_id: str, updates: Dict) -> Optional[Dict]:
        """更新队列项"""
        with self._lock:
            for i, item in enumerate(self._data["queue"]):
                if item["id"] == item_id:
                    self._data["queue"][i].update(updates)
                    self._save()
                    return self._data["queue"][i]
            return None

    def remove_item(self, item_id: str) -> bool:
        """移除队列项"""
        with self._lock:
            for i, item in enumerate(self._data["queue"]):
                if item["id"] == item_id:
                    del self._data["queue"][i]
                    self._save()
                    return True
            return False

    def clear_completed(self) -> int:
        """清除已完成的项"""
        with self._lock:
            original_len = len(self._data["queue"])
            self._data["queue"] = [
                item for item in self._data["queue"]
                if item["status"] not in ["completed", "failed"]
            ]
            self._save()
            return original_len - len(self._data["queue"])


# 全局单例
db = ProjectDatabase()
account_db = AccountDatabase()
submit_queue_db = SubmitQueueDatabase()
