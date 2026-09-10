"""
Skill-gap plan behaviour.

The one property worth guarding hardest here: the prompt must never be given the
candidate's resume content, only the JD and the gap keywords — this feature must not
become a second path for the fabrication bug the optimizer already guards against.
"""

import json

from engine.skill_gap import generate_skill_gap_plan


class FakeLLM:
    """Stands in for a live provider. `response` is returned verbatim from call_chat."""

    def __init__(self, response="", api_key="test-key", raises=None):
        self.response = response
        self.api_key = api_key
        self.model = "fake-model"
        self.raises = raises
        self.calls = 0
        self.last_user_prompt = None

    def call_chat(self, system_prompt, user_prompt, temperature=0.2):
        self.calls += 1
        self.last_user_prompt = user_prompt
        if self.raises:
            raise self.raises
        return self.response


VALID_PLAN = json.dumps({
    "plan": [
        {
            "skill": "kubernetes",
            "why_it_matters": "The role runs containerised services at scale.",
            "how_to_close_it": ["Complete the official Kubernetes basics tutorial.", "Deploy a small app to a local cluster with kind."],
            "estimated_time": "2-3 weeks of focused practice",
        },
        {
            "skill": "cross-functional collaboration",
            "why_it_matters": "The role coordinates across engineering and product.",
            "how_to_close_it": ["Volunteer to lead a small cross-team initiative."],
            "estimated_time": "ongoing",
        },
    ]
})


class TestGenerateSkillGapPlan:
    def test_returns_empty_plan_with_no_gaps(self):
        result = generate_skill_gap_plan([], "some jd", FakeLLM())
        assert result["plan"] == []

    def test_returns_empty_plan_without_an_api_key(self):
        llm = FakeLLM(api_key="")
        result = generate_skill_gap_plan(["kubernetes"], "some jd", llm)
        assert result["plan"] == []
        assert llm.calls == 0, "must not call a provider with no key"

    def test_parses_a_valid_plan(self):
        llm = FakeLLM(response=VALID_PLAN)
        result = generate_skill_gap_plan(["kubernetes", "cross-functional collaboration"], "some jd", llm)
        assert len(result["plan"]) == 2
        assert result["plan"][0]["skill"] == "kubernetes"
        assert result["plan"][0]["how_to_close_it"]
        assert result["engine_used"].startswith("llm:")

    def test_falls_back_to_empty_plan_on_unparseable_response(self):
        llm = FakeLLM(response="not json at all")
        result = generate_skill_gap_plan(["kubernetes"], "some jd", llm)
        assert result["plan"] == []
        assert "unavailable" in result["engine_used"]

    def test_falls_back_to_empty_plan_when_the_provider_fails(self):
        llm = FakeLLM(raises=RuntimeError("provider exploded"))
        result = generate_skill_gap_plan(["kubernetes"], "some jd", llm)
        assert result["plan"] == []
        assert "unavailable" in result["engine_used"]

    def test_caps_at_the_configured_max_gap_skills(self):
        llm = FakeLLM(response=VALID_PLAN)
        many_skills = [f"skill-{i}" for i in range(20)]
        generate_skill_gap_plan(many_skills, "some jd", llm)
        # The prompt sent to the model must not list more than the configured cap.
        assert llm.last_user_prompt.count("skill-") <= 8

    def test_never_sends_resume_content_to_the_model(self):
        """
        Regression guard: this prompt has no resume_text parameter at all — it must
        stay that way. Sending resume content here would let this feature become a
        second path for the fabrication bug the optimizer explicitly guards against.
        """
        import inspect

        sig = inspect.signature(generate_skill_gap_plan)
        assert "resume_text" not in sig.parameters
        assert "resume" not in sig.parameters
