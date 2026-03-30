from pathlib import Path

import pytest


class _DummyClient:
    def __init__(self, *args, **kwargs):
        pass


def _base_plan(extra_cfg=None):
    cfg = {
        "enable_project_novelty_gate": True,
        "max_failed_files": 0,
        "project_novelty_threshold": 0.0,
        "file_novelty_budget": 0.0,
        "max_risky_files": 999,
        "max_syntax_fail_files": 999,
        "min_ai_line_ratio": 0.0,
    }
    if extra_cfg:
        cfg.update(extra_cfg)
    return {
        "project_name": "quality-guard-test",
        "genome": {"target_language": "Python"},
        "code_blueprint": {"entities": ["RecordItem"]},
        "pages": {
            "page_1": {"title": "首页概览"},
            "page_2": {"title": "流程审批"},
        },
        "code_generation_config": cfg,
    }


def test_code_transformer_accepts_pages_dict(monkeypatch):
    from modules.code_transformer import CodeTransformer

    monkeypatch.setattr("modules.code_transformer.DeepSeekClient", _DummyClient)
    transformer = CodeTransformer(_base_plan())
    spec = transformer.spec_builder.get_project_spec()
    assert spec["workflow_steps"][:2] == ["首页概览", "流程审批"]


def test_second_pass_prefers_lower_forbidden_risk(monkeypatch):
    from modules.code_transformer import CodeTransformer

    monkeypatch.setattr("modules.code_transformer.DeepSeekClient", _DummyClient)
    transformer = CodeTransformer(_base_plan())
    transformer.low_novelty_local_retry = True

    monkeypatch.setattr(transformer, "_simple_entity_replace", lambda code, fp: "retry_code")
    monkeypatch.setattr(
        transformer,
        "_apply_step_with_guard",
        lambda current_code, transform_func, step_name, relative_path: current_code,
    )
    monkeypatch.setattr(
        transformer.structure_transformer,
        "apply_semantic_noise",
        lambda code, language, semantic_comments, insert_ratio=0.16: code,
    )
    monkeypatch.setattr(transformer, "_validate_syntax", lambda code, language: True)

    def fake_evaluate(code: str, source_code: str):
        if code == "retry_code":
            return (
                {"novelty_score": 0.72, "max_similarity": 0.28, "risk_level": "low"},
                {"risk_score": 0.92, "window_density": 0.2, "line_hits": 12},
            )
        return (
            {"novelty_score": 0.0, "max_similarity": 1.0, "risk_level": "high"},
            {"risk_score": 0.0, "window_density": 0.0, "line_hits": 0},
        )

    monkeypatch.setattr(transformer, "_evaluate_novelty", fake_evaluate)

    origin_novelty = {"novelty_score": 0.66}
    origin_forbidden = {"risk_score": 0.05, "window_density": 0.0, "line_hits": 0}
    out_code, out_novelty, out_forbidden = transformer._second_pass_local_rewrite(
        code="origin_code",
        source_code="seed_code",
        file_path="services/sample_service.py",
        novelty_report=origin_novelty,
        forbidden_report=origin_forbidden,
    )
    assert out_code == "origin_code"
    assert out_novelty == origin_novelty
    assert out_forbidden == origin_forbidden


def test_quality_report_blocks_failed_files(monkeypatch):
    from modules.code_transformer import CodeTransformer

    monkeypatch.setattr("modules.code_transformer.DeepSeekClient", _DummyClient)
    transformer = CodeTransformer(_base_plan({"max_failed_files": 0}))
    report = transformer._build_quality_report(
        metadata_list=[
            {
                "novelty_score": 0.91,
                "line_count": 120,
                "process_mode": "ai_rewrite",
                "forbidden_risk": 0.0,
                "syntax_ok": True,
            }
        ],
        failed_files_count=1,
    )
    assert report["failed_files_count"] == 1
    assert report["passed"] is False


def test_pdf_generate_falls_back_to_html_when_code_empty(tmp_path):
    from modules.code_pdf_generator import CodePDFGenerator

    code_dir = tmp_path / "aligned_code"
    code_dir.mkdir(parents=True, exist_ok=True)
    html_dir = tmp_path / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    (html_dir / "page_1.html").write_text(
        "<html>\n<body>\n<div>fallback line 1</div>\n<div>fallback line 2</div>\n</body>\n</html>\n",
        encoding="utf-8",
    )

    output_pdf = tmp_path / "source.pdf"
    gen = CodePDFGenerator("pdf-fallback-project", html_dir=str(html_dir), include_html=False)
    ok = gen.generate(str(code_dir), str(output_pdf))
    assert ok is True
    assert output_pdf.exists()

