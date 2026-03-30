import json
from pathlib import Path

from modules.document_generator import DocumentGenerator


def _stub_generator(tmp_path: Path) -> DocumentGenerator:
    generator = DocumentGenerator.__new__(DocumentGenerator)
    generator.output_path = tmp_path / "manual.docx"
    generator.plan = {"project_name": "一致性项目", "pages": {"page_1": {"page_title": "业务页"}}}
    generator.project_spec = {}
    return generator


def test_consistency_report_requires_baseline(tmp_path: Path):
    generator = _stub_generator(tmp_path)
    generator.plan["code_blueprint"] = {"controllers": [], "entities": []}
    context = {"api_list": [], "db_tables": [], "pages": [{"title": "业务页"}]}
    generator._save_consistency_report(context)

    report_path = tmp_path / "doc_code_consistency_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["baseline_ready"] is False
    assert report["passed"] is False


def test_get_page_apis_fallback_to_executable_spec(tmp_path: Path):
    generator = _stub_generator(tmp_path)
    generator.plan["code_blueprint"] = {"controllers": []}
    generator.project_spec = {
        "api_contracts": [
            {
                "id": "api_order_query",
                "method_name": "query_order",
                "description": "查询订单",
                "http_method": "GET",
                "path": "/api/order/query",
            }
        ],
        "page_api_mapping": [{"page_id": "page_1", "api_ids": ["api_order_query"]}],
    }

    apis = generator._get_page_apis("page_1")
    assert len(apis) == 1
    assert apis[0]["name"] == "query_order"
    assert apis[0]["http"] == "GET /api/order/query"
