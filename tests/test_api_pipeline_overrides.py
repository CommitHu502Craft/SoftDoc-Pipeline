from api.models import PipelineStep, RunPipelineRequest


def test_run_pipeline_request_accepts_code_overrides():
    req = RunPipelineRequest(
        steps=[PipelineStep.PLAN, PipelineStep.CODE],
        code_generation_overrides={
            "novelty_threshold": 0.51,
            "max_syntax_fail_files": 0,
        },
    )
    assert req.code_generation_overrides is not None
    assert req.code_generation_overrides["novelty_threshold"] == 0.51


def test_task_manager_run_plan_passes_overrides(tmp_path, monkeypatch):
    import modules
    import api.task_manager as task_manager_module

    captured = {}

    def fake_generate_project_plan(
        project_name,
        api_key=None,
        genome_overrides=None,
        code_generation_overrides=None,
        project_charter=None,
    ):
        captured["project_name"] = project_name
        captured["code_generation_overrides"] = code_generation_overrides or {}
        captured["project_charter"] = project_charter or {}
        return {
            "project_name": project_name,
            "menu_list": [],
            "pages": {},
            "code_generation_config": code_generation_overrides or {},
        }

    monkeypatch.setattr(task_manager_module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(modules, "generate_project_plan", fake_generate_project_plan)

    manager = task_manager_module.TaskManager()
    code_cfg = {"novelty_threshold": 0.49, "min_ai_line_ratio": 0.22}
    charter = {
        "project_name": "api-test-project",
        "business_scope": "测试业务边界",
        "user_roles": [{"name": "管理员", "responsibility": ""}, {"name": "操作员", "responsibility": ""}],
        "core_flows": [{"name": "测试流程", "steps": ["录入", "提交"], "success_criteria": ""}],
        "non_functional_constraints": ["可用性约束"],
        "acceptance_criteria": ["可完成主流程"],
    }
    task_id = manager.create_task(
        "pid-1",
        "api-test-project",
        code_generation_overrides=code_cfg,
        project_charter=charter,
    )

    ok = manager._run_plan("api-test-project", task_id, code_cfg, charter)
    assert ok is True
    assert captured["project_name"] == "api-test-project"
    assert captured["code_generation_overrides"] == code_cfg
    assert captured["project_charter"]["business_scope"] == "测试业务边界"
    assert (tmp_path / "api-test-project" / "project_plan.json").exists()
