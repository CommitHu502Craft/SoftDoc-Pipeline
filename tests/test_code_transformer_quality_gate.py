from modules.code_transformer import CodeTransformer


def _build_transformer_stub() -> CodeTransformer:
    """
    使用 __new__ 构造轻量实例，避免触发真实 API 客户端初始化。
    只填充质量报告计算所需字段。
    """
    transformer = CodeTransformer.__new__(CodeTransformer)
    transformer.file_novelty_budget = 0.46
    transformer.project_novelty_threshold = 0.42
    transformer.max_risky_files = 2
    transformer.max_syntax_fail_files = 0
    transformer.min_ai_line_ratio = 0.20
    transformer.max_failed_files = 0
    return transformer


def test_quality_report_passes_when_all_gates_met():
    transformer = _build_transformer_stub()
    metadata = [
        {
            "file_path": "services/a.py",
            "process_mode": "ai_rewrite",
            "line_count": 220,
            "novelty_score": 0.62,
            "forbidden_risk": 0.12,
            "syntax_ok": True,
        },
        {
            "file_path": "routers/b.py",
            "process_mode": "ai_rewrite",
            "line_count": 160,
            "novelty_score": 0.57,
            "forbidden_risk": 0.15,
            "syntax_ok": True,
        },
        {
            "file_path": "utils/c.py",
            "process_mode": "obfuscation",
            "line_count": 180,
            "novelty_score": 0.54,
            "forbidden_risk": 0.10,
            "syntax_ok": True,
        },
    ]

    report = transformer._build_quality_report(metadata)

    assert report["passed"] is True
    assert report["syntax_fail_count"] == 0
    assert report["ai_line_ratio"] >= transformer.min_ai_line_ratio


def test_quality_report_fails_on_syntax_and_ai_ratio():
    transformer = _build_transformer_stub()
    metadata = [
        {
            "file_path": "services/a.py",
            "process_mode": "ai_rewrite",
            "line_count": 40,
            "novelty_score": 0.61,
            "forbidden_risk": 0.12,
            "syntax_ok": False,
        },
        {
            "file_path": "utils/b.py",
            "process_mode": "obfuscation",
            "line_count": 260,
            "novelty_score": 0.58,
            "forbidden_risk": 0.10,
            "syntax_ok": True,
        },
    ]

    report = transformer._build_quality_report(metadata)

    assert report["passed"] is False
    assert report["syntax_fail_count"] == 1
    assert report["ai_line_ratio"] < transformer.min_ai_line_ratio


def test_quality_report_scope_prefers_ai_rewrite_and_ignores_local_risky_for_gate():
    transformer = _build_transformer_stub()
    metadata = [
        {
            "file_path": "services/a.py",
            "process_mode": "ai_rewrite",
            "line_count": 220,
            "novelty_score": 0.64,
            "forbidden_risk": 0.10,
            "syntax_ok": True,
        },
        {
            "file_path": "utils/local_1.py",
            "process_mode": "obfuscation",
            "line_count": 180,
            "novelty_score": 0.55,
            "forbidden_risk": 1.00,
            "syntax_ok": True,
        },
        {
            "file_path": "utils/local_2.py",
            "process_mode": "obfuscation",
            "line_count": 160,
            "novelty_score": 0.52,
            "forbidden_risk": 0.84,
            "syntax_ok": True,
        },
    ]

    report = transformer._build_quality_report(metadata)

    assert report["quality_scope"] == "ai_rewrite"
    assert report["scope_files"] == 1
    assert report["risky_file_count"] == 0
    assert report["local_risky_file_count"] == 2
    assert report["passed"] is True


def test_should_enforce_file_gate_scope():
    transformer = CodeTransformer.__new__(CodeTransformer)
    transformer.enforce_file_gate = True
    transformer.enforce_file_gate_on_obfuscation = False

    assert transformer._should_enforce_file_gate(use_llm=True) is True
    assert transformer._should_enforce_file_gate(use_llm=False) is False

    transformer.enforce_file_gate_on_obfuscation = True
    assert transformer._should_enforce_file_gate(use_llm=False) is True


def test_process_single_file_returns_fallback_artifact_on_exception():
    class _SpecStub:
        @staticmethod
        def get_project_spec():
            return {"version": "spec-v1", "architecture_family": "Layered"}

    transformer = CodeTransformer.__new__(CodeTransformer)
    transformer.target_language = "Python"
    transformer.primary_entity = "Record"
    transformer.spec_builder = _SpecStub()
    transformer.enforce_file_gate = True
    transformer.enforce_file_gate_on_obfuscation = False
    transformer.file_novelty_budget = 0.46

    transformer._rename_file = lambda relative_path, primary_entity: relative_path
    transformer._validate_syntax = lambda code, language: True
    transformer._extract_metadata = lambda code, file_path: {"class_name": "Fallback"}
    transformer._simple_entity_replace = lambda code, file_path="": (_ for _ in ()).throw(RuntimeError("boom"))

    result = transformer._process_single_file(
        relative_path="routes/userRoutes.js",
        content="module.exports = {};",
        use_llm=False,
        processing_mode="obfuscation",
        file_profile=None,
    )

    assert result is not None
    out_path, out_code, metadata = result
    assert out_path == "routes/userRoutes.js"
    assert out_code == "module.exports = {};"
    assert metadata["process_mode"] == "fallback_error"
    assert metadata["quality_scope"] == "fallback_error"


def test_quality_report_counts_fallback_artifact_as_failed_file():
    transformer = _build_transformer_stub()
    metadata = [
        {
            "file_path": "services/a.py",
            "process_mode": "ai_rewrite",
            "line_count": 220,
            "novelty_score": 0.62,
            "forbidden_risk": 0.10,
            "syntax_ok": True,
        },
        {
            "file_path": "routes/fallback.py",
            "process_mode": "fallback_error",
            "line_count": 180,
            "novelty_score": 0.0,
            "forbidden_risk": 1.0,
            "syntax_ok": True,
        },
    ]

    report = transformer._build_quality_report(metadata, failed_files_count=0)

    assert report["raw_failed_files_count"] == 0
    assert report["fallback_file_count"] == 1
    assert report["failed_files_count"] == 1
    assert report["passed"] is False


def test_quality_report_uses_density_signal_for_risky_detection():
    transformer = _build_transformer_stub()
    transformer.max_risky_files = 0
    metadata = [
        {
            "file_path": "services/a.py",
            "process_mode": "ai_rewrite",
            "line_count": 220,
            "novelty_score": 0.62,
            "forbidden_risk": 0.10,
            "forbidden_window_density": 0.12,
            "forbidden_line_hits": 0,
            "syntax_ok": True,
        }
    ]

    report = transformer._build_quality_report(metadata, failed_files_count=0)

    assert report["risky_file_count"] == 1
    assert report["passed"] is False
