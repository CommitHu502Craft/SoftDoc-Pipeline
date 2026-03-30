from modules.project_charter import (
    draft_project_charter_with_ai,
    validate_project_charter,
)


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, prompt: str, max_retries: int = 2):
        return self.payload


class _FailClient:
    def generate_json(self, prompt: str, max_retries: int = 2):
        raise RuntimeError("mock failure")


def test_draft_project_charter_with_ai_hydrates_missing_fields():
    client = _FakeClient(
        {
            "project_name": "样例系统",
            "business_scope": "",
            "user_roles": [{"name": "管理员"}],  # 不足2个角色
            "core_flows": [{"name": "流程A", "steps": ["录入"]}],  # 步骤不足2个
            "non_functional_constraints": [],
            "acceptance_criteria": [],
        }
    )

    charter = draft_project_charter_with_ai("样例系统", client=client)
    errors = validate_project_charter(charter)
    assert errors == []


def test_draft_project_charter_with_ai_fallback_on_client_error():
    charter = draft_project_charter_with_ai("回退系统", client=_FailClient())
    errors = validate_project_charter(charter)
    assert errors == []
