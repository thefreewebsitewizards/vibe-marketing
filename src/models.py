from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class PlanStatus(str, Enum):
    REVIEW = "review"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ReelRequest(BaseModel):
    reel_url: str


class ReelMetadata(BaseModel):
    url: str
    shortcode: str
    creator: str = ""
    caption: str = ""
    duration: float = 0.0
    content_type: str = "reel"  # reel or carousel


class TranscriptResult(BaseModel):
    text: str
    language: str = "en"
    duration: float = 0.0


class VideoBreakdown(BaseModel):
    hook: str = ""  # How the video opens / grabs attention
    main_points: list[str] = []  # Ordered key points the creator makes
    key_quotes: list[str] = []  # Notable direct quotes from the transcript
    creator_context: str = ""  # Who this person is and why their take matters


class DetailedNotes(BaseModel):
    what_it_is: str = ""
    how_useful: str = ""
    how_not_useful: str = ""
    target_audience: str = ""


class BusinessApplication(BaseModel):
    area: str = ""
    recommendation: str = ""
    target_system: str = ""  # ghl, n8n, sales_script, website, meta_ads, telegram
    urgency: str = "medium"  # high, medium, low


class FactCheck(BaseModel):
    claim: str = ""
    verdict: str = "unverified"  # verified, outdated, better_alternative, unverified
    explanation: str = ""
    better_alternative: str = ""


class AnalysisResult(BaseModel):
    category: str
    summary: str
    key_insights: list[str]
    swipe_phrases: list[str] = []
    relevance_score: float = Field(ge=0.0, le=1.0)
    raw_response: str = ""
    # New enriched fields
    theme: str = ""
    video_breakdown: VideoBreakdown = Field(default_factory=VideoBreakdown)
    detailed_notes: DetailedNotes = Field(default_factory=DetailedNotes)
    business_applications: list[BusinessApplication] = []
    business_impact: str = ""
    fact_checks: list[FactCheck] = []
    routing_target: str = "tfww"


class SimilarPlan(BaseModel):
    title: str = ""
    reel_id: str = ""
    score: int = 0  # 0-100
    overlap_areas: list[str] = []


class SimilarityResult(BaseModel):
    similar_plans: list[SimilarPlan] = []
    recommendation: str = "generate"  # generate, skip, merge
    max_score: int = 0


class PlanTask(BaseModel):
    title: str
    description: str
    priority: str = "medium"
    estimated_hours: float = 1.0
    deliverables: list[str] = []
    dependencies: list[str] = []
    tools: list[str] = []
    requires_human: bool = False
    human_reason: str = ""


class ImplementationPlan(BaseModel):
    title: str
    summary: str
    tasks: list[PlanTask]
    total_estimated_hours: float = 0.0


class LLMCallCost(BaseModel):
    step: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class CostBreakdown(BaseModel):
    calls: list[LLMCallCost] = []
    total_cost_usd: float = 0.0

    def add(self, step: str, model: str, prompt_tokens: int, completion_tokens: int, cost_usd: float):
        self.calls.append(LLMCallCost(
            step=step, model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        ))
        self.total_cost_usd = sum(c.cost_usd for c in self.calls)


class PipelineResult(BaseModel):
    reel_id: str
    status: PlanStatus = PlanStatus.REVIEW
    metadata: ReelMetadata
    transcript: TranscriptResult
    analysis: AnalysisResult
    plan: ImplementationPlan
    repurposing_plan: ImplementationPlan | None = None
    personal_brand_plan: ImplementationPlan | None = None
    similarity: SimilarityResult | None = None
    cost_breakdown: CostBreakdown | None = None
    plan_dir: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class PlanIndexEntry(BaseModel):
    reel_id: str
    title: str
    status: PlanStatus = PlanStatus.REVIEW
    plan_dir: str
    created_at: str
    source_url: str
    theme: str = ""
    category: str = ""
    relevance_score: float = 0.0
    estimated_cost: float = 0.0
    routed_to: str = ""
    task_count: int = 0
    total_hours: float = 0.0
