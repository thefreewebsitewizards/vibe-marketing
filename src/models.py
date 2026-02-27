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


class TranscriptResult(BaseModel):
    text: str
    language: str = "en"
    duration: float = 0.0


class AnalysisResult(BaseModel):
    category: str
    summary: str
    key_insights: list[str]
    swipe_phrases: list[str] = []
    relevance_score: float = Field(ge=0.0, le=1.0)
    raw_response: str = ""


class PlanTask(BaseModel):
    title: str
    description: str
    priority: str = "medium"
    estimated_hours: float = 1.0
    deliverables: list[str] = []
    dependencies: list[str] = []
    tools: list[str] = []


class ImplementationPlan(BaseModel):
    title: str
    summary: str
    tasks: list[PlanTask]
    total_estimated_hours: float = 0.0


class PipelineResult(BaseModel):
    reel_id: str
    status: PlanStatus = PlanStatus.REVIEW
    metadata: ReelMetadata
    transcript: TranscriptResult
    analysis: AnalysisResult
    plan: ImplementationPlan
    plan_dir: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class PlanIndexEntry(BaseModel):
    reel_id: str
    title: str
    status: PlanStatus = PlanStatus.REVIEW
    plan_dir: str
    created_at: str
    source_url: str
