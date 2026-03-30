import json
from pathlib import Path

from modules.spec_review import (
    approve_spec_review,
    get_spec_review_status,
    save_spec_review_artifacts,
)


def _sample_spec(project_name: str = "规格项目"):
    return {
        "project_name": project_name,
        "entities": [{"name": "Order"}],
        "api_contracts": [
            {
                "id": "api_order_query",
                "http_method": "GET",
                "path": "/api/order/query",
                "description": "查询订单",
            }
        ],
        "state_machines": [
            {
                "name": "订单流程",
                "states": [{"id": "s1", "label": "创建"}, {"id": "s2", "label": "完成"}],
                "transitions": [{"from": "s1", "to": "s2"}],
            }
        ],
        "permission_matrix": [{"role": "管理员", "grants": []}],
    }


def test_spec_review_pending_then_approved(tmp_path: Path):
    project_dir = tmp_path / "output" / "规格项目"
    project_dir.mkdir(parents=True, exist_ok=True)
    spec_path = project_dir / "project_executable_spec.json"
    spec_path.write_text(json.dumps(_sample_spec(), ensure_ascii=False), encoding="utf-8")

    result = save_spec_review_artifacts(project_dir, "规格项目")
    assert result["ok"] is True
    status = get_spec_review_status(project_dir, spec_path)
    assert status["approved"] is False
    assert status["review_status"] == "pending"

    approved = approve_spec_review(project_dir, reviewer="tester")
    assert approved["ok"] is True
    status2 = get_spec_review_status(project_dir, spec_path)
    assert status2["approved"] is True
    assert status2["review_status"] == "approved"


def test_spec_review_auto_reset_when_spec_changes(tmp_path: Path):
    project_dir = tmp_path / "output" / "规格变更项目"
    project_dir.mkdir(parents=True, exist_ok=True)
    spec_path = project_dir / "project_executable_spec.json"
    spec_data = _sample_spec("规格变更项目")
    spec_path.write_text(json.dumps(spec_data, ensure_ascii=False), encoding="utf-8")

    save_spec_review_artifacts(project_dir, "规格变更项目")
    approve_spec_review(project_dir, reviewer="tester")
    assert get_spec_review_status(project_dir, spec_path)["approved"] is True

    # 修改规格后，状态应自动变回 pending
    spec_data["entities"].append({"name": "Invoice"})
    spec_path.write_text(json.dumps(spec_data, ensure_ascii=False), encoding="utf-8")
    save_spec_review_artifacts(project_dir, "规格变更项目")
    assert get_spec_review_status(project_dir, spec_path)["approved"] is False
