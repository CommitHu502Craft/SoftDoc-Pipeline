import json
from pathlib import Path

from modules.semantic_homogeneity_gate import apply_semantic_homogeneity_gate


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sample_spec() -> dict:
    return {
        "project_name": "同质化项目",
        "entities": [{"name": "Order", "fields": [{"name": "id", "type": "string"}]}],
        "state_machines": [
            {
                "name": "订单流程",
                "states": [{"id": "draft", "label": "草稿"}, {"id": "done", "label": "完成"}],
                "transitions": [{"from": "draft", "to": "done"}],
            }
        ],
        "permission_matrix": [{"role": "管理员", "permissions": ["order.read"]}],
        "api_contracts": [
            {
                "id": "api_order_list",
                "http_method": "GET",
                "path": "/api/orders",
                "description": "查询订单",
                "method_name": "listOrders",
            }
        ],
        "page_api_mapping": [{"page_id": "page_1", "api_ids": ["api_order_list"]}],
    }


def test_semantic_homogeneity_gate_rewrites_spec_and_plan(tmp_path: Path):
    output_root = tmp_path / "output"

    current_name = "当前项目"
    current_dir = output_root / current_name
    current_spec = _sample_spec()
    _write_json(current_dir / "project_executable_spec.json", current_spec)
    _write_json(
        current_dir / "project_plan.json",
        {
            "project_name": current_name,
            "executable_spec": current_spec,
            "code_blueprint": {"entities": ["Order"]},
        },
    )

    # 造一个高度相似的历史项目，触发重写
    other_name = "历史项目"
    _write_json(output_root / other_name / "project_executable_spec.json", _sample_spec())

    report = apply_semantic_homogeneity_gate(
        project_name=current_name,
        project_dir=current_dir,
        output_root=output_root,
        threshold=0.0,
        auto_rewrite=True,
    )
    assert report["should_rewrite"] is True
    assert report["rewritten"] is True

    rewritten_spec = json.loads((current_dir / "project_executable_spec.json").read_text(encoding="utf-8"))
    signature = rewritten_spec.get("semantic_signature")
    assert signature
    assert rewritten_spec["entities"][0]["name"].startswith(f"{signature}_")
    assert rewritten_spec["api_contracts"][0]["path"].startswith(f"/api/{signature}/")
    assert rewritten_spec["api_contracts"][0]["id"].endswith(f"_{signature}")
    assert rewritten_spec["page_api_mapping"][0]["api_ids"][0].endswith(f"_{signature}")

    synced_plan = json.loads((current_dir / "project_plan.json").read_text(encoding="utf-8"))
    assert synced_plan["executable_spec"]["semantic_signature"] == signature
    assert synced_plan["code_blueprint"]["entities"][0].startswith(f"{signature}_")
