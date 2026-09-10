"""
Skill-gap coaching.

The optimizer never invents a skill the candidate doesn't have — genuine gaps stay
gaps, by design (see engine/optimizer.py). This module is the other half of that
promise: instead of a dead-end list of missing keywords, turn it into a concrete plan
for actually closing them, so a candidate can honestly earn a higher score next time
rather than fake one this time.

One LLM call, not a conversation — see the cost discussion that led here. The prompt
only ever asks "how would someone learn X", never anything about the candidate's
resume content, so this carries none of the fabrication risk the optimizer guards
against — it can't misrepresent the candidate because it never speaks about them.
"""

from typing import Any, Dict, List

from engine.optimizer import robust_json_decode
from engine.llm_client import UnifiedLLMClient

# Keep the plan focused and the prompt/response bounded — a JD with a long tail of
# minor keyword gaps doesn't need a 20-item study plan, and every extra skill is
# another slice of the same LLM call budget the optimizer draws from.
_MAX_GAP_SKILLS = 8

SYSTEM_SKILL_GAP_PROMPT = """You are a pragmatic career coach helping a job seeker close real skill gaps
between their resume and a target job description.

You will be given a list of skills/keywords the job description asks for that the
candidate's resume currently gives no evidence of. For each one, produce a short,
concrete, honest coaching entry. Do not discuss or reference the candidate's resume
content, name, or any personal detail — you have none, and must invent none.

RULES:
1. Be concrete. "Learn Python" is useless; "Build a small FastAPI service that reads
   from PostgreSQL and deploy it on Render's free tier" is useful.
2. Prefer free or low-cost resources (official docs, freeCodeCamp, official vendor
   free-tier tutorials, a scoped personal project) over paid courses unless a paid
   resource is genuinely the standard path (e.g. a specific required certification).
3. Be honest about effort. A rough time estimate should reflect real learning time
   for someone starting from little to no experience with that specific skill, not
   an optimistic minimum.
4. If a "skill" is actually a soft skill or process term (e.g. "cross-functional
   collaboration") rather than a learnable technology, give practical ways to build
   and demonstrate that experience instead of a course.
5. Never claim the person already has partial experience — you don't know that.

Return ONLY strict JSON in this schema, no prose outside the object:

{
  "plan": [
    {
      "skill": <string — the skill/keyword as given>,
      "why_it_matters": <string, 1 sentence, why this role likely wants it>,
      "how_to_close_it": [<string>, <string>, ...],
      "estimated_time": <string, e.g. "1-2 weeks of focused practice">
    }
  ]
}
"""


def generate_skill_gap_plan(
    gap_keywords: List[str],
    jd_text: str,
    llm_client: UnifiedLLMClient,
) -> Dict[str, Any]:
    """
    Produce a coaching plan for the top skill gaps between a resume and a JD.

    Returns {"plan": [...], "engine_used": str}. On any failure (no API key, provider
    error, unparseable response) returns an honest empty plan rather than guessing —
    there is no safe structural fallback for content this open-ended.
    """
    skills = [k.strip() for k in gap_keywords if k.strip()][:_MAX_GAP_SKILLS]
    if not skills:
        return {"plan": [], "engine_used": "n/a (no gaps to plan for)"}

    if not getattr(llm_client, "api_key", ""):
        return {"plan": [], "engine_used": "unavailable (no API key configured)"}

    user_prompt = f"""Target job description (for context on why these skills matter):
\"\"\"{jd_text}\"\"\"

Skills/keywords the candidate's resume shows no evidence of:
{", ".join(skills)}

Return the JSON plan for exactly these skills, in the order given."""

    try:
        raw = llm_client.call_chat(SYSTEM_SKILL_GAP_PROMPT, user_prompt, temperature=0.3)
        data = robust_json_decode(raw)
        plan = data.get("plan") if isinstance(data, dict) else None
        if not isinstance(plan, list) or not plan:
            return {"plan": [], "engine_used": "unavailable (LLM response was unusable)"}

        # Defensive normalisation: keep only well-formed entries rather than letting one
        # malformed item break the whole response.
        cleaned = []
        for entry in plan:
            if not isinstance(entry, dict) or not entry.get("skill"):
                continue
            steps = entry.get("how_to_close_it")
            cleaned.append({
                "skill": str(entry["skill"]).strip(),
                "why_it_matters": str(entry.get("why_it_matters", "")).strip(),
                "how_to_close_it": [str(s).strip() for s in steps] if isinstance(steps, list) else [],
                "estimated_time": str(entry.get("estimated_time", "")).strip(),
            })

        provider_summary = getattr(llm_client, "provider_summary", None)
        engine_used = f"llm:{provider_summary}" if provider_summary else f"llm:{llm_client.model}"
        return {"plan": cleaned, "engine_used": engine_used}
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not raised
        return {"plan": [], "engine_used": f"unavailable (LLM call failed: {type(exc).__name__})"}
