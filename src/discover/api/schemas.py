from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class SourceStats(BaseModel):
    source_type: str
    raw_count: int
    canonical_count: int
    relevant_count: int
    extracted_count: int


class SourceStatsResponse(BaseModel):
    sources: list[SourceStats]
    total_raw: int
    total_canonical: int
    total_relevant: int
    total_extracted: int


class StageMetric(BaseModel):
    stage: str
    last_status: Optional[str] = None
    last_updated_at: Optional[str] = None
    dry_run: bool = False
    error_message: Optional[str] = None


class PipelineStatsResponse(BaseModel):
    pipeline_runs_count: int
    active_analysis_run_ids: list[str]
    stage_metrics: list[StageMetric]


class ResearchThemeDTO(BaseModel):
    id: str
    title: str
    definition: str
    mvp_fit: str
    mvp_fit_label: str
    is_core_opportunity: bool = False
    record_count_primary: int
    unique_threads: int
    validated_for_interviews: bool = True
    exemplars: list[dict[str, Any]] = Field(default_factory=list)


class ThemeListResponse(BaseModel):
    analysis_run_id: str
    total_relevant_records: int
    total_themes: int
    themes: list[ResearchThemeDTO]
    note: str = "Validated research themes identified within the 190-record corpus."


class RecordSummary(BaseModel):
    id: str
    source_type: str
    title: Optional[str] = None
    body: str
    author_handle: Optional[str] = None
    posted_at: Optional[str] = None
    permalink: Optional[str] = None
    is_relevant: Optional[bool] = None
    relevance_confidence: Optional[float] = None
    cluster_id: Optional[str] = None
    cluster_label: Optional[str] = None
    theme_ids: list[str] = Field(default_factory=list)
    theme_titles: list[str] = Field(default_factory=list)


class RecordListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    records: list[RecordSummary]


class RelevanceDetail(BaseModel):
    id: str
    analysis_run_id: str
    is_relevant: Optional[bool] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    model_id: Optional[str] = None
    created_at: str


class UXExtractionDetail(BaseModel):
    id: str
    analysis_run_id: str
    structured_fields: Optional[dict[str, Any]] = None
    evidence_spans: Optional[dict[str, Any]] = None
    model_id: Optional[str] = None
    created_at: str


class RecordClusterMembership(BaseModel):
    cluster_id: str
    cluster_label: Optional[str] = None
    cluster_summary: Optional[str] = None
    score: Optional[float] = None


class RecordDetailResponse(BaseModel):
    id: str
    raw_record_id: str
    source_type: str
    title: Optional[str] = None
    body: str
    author_handle: Optional[str] = None
    posted_at: Optional[str] = None
    permalink: Optional[str] = None
    content_hash: str
    metadata: Optional[dict[str, Any]] = None
    created_at: str
    raw_payload: Optional[dict[str, Any]] = None
    relevance: Optional[RelevanceDetail] = None
    extraction: Optional[UXExtractionDetail] = None
    clusters: list[RecordClusterMembership] = Field(default_factory=list)
    themes: list[ResearchThemeDTO] = Field(default_factory=list)


class ClusterDTO(BaseModel):
    id: str
    analysis_run_id: str
    label: Optional[str] = None
    summary: Optional[str] = None
    member_count: int
    metadata: Optional[dict[str, Any]] = None
    exemplars: list[str] = Field(default_factory=list)
    created_at: str
    cluster_type: str = "exploratory_machine_cluster"


class ClusterListResponse(BaseModel):
    total: int
    clusters: list[ClusterDTO]


class ClusterMemberItem(BaseModel):
    record_id: str
    title: Optional[str] = None
    body: str
    permalink: Optional[str] = None
    score: Optional[float] = None


class ClusterMembersResponse(BaseModel):
    cluster_id: str
    total_members: int
    limit: int
    offset: int
    members: list[ClusterMemberItem]


class OpportunityScoreDTO(BaseModel):
    cluster_id: str
    cluster_label: Optional[str] = None
    cluster_summary: Optional[str] = None
    member_count: int = 0
    frequency_score: Optional[float] = None
    severity_score: Optional[float] = None
    consistency_score: Optional[float] = None
    evidence_score: Optional[float] = None
    composite_rank: Optional[float] = None
    exemplars: list[str] = Field(default_factory=list)
    mvp_fit_label: Optional[str] = None
    is_core_opportunity: bool = False
    unique_threads: Optional[int] = None
    record_count: Optional[int] = None


class OpportunityListResponse(BaseModel):
    total: int
    opportunities: list[OpportunityScoreDTO]
    themes: list[ResearchThemeDTO] = Field(default_factory=list)
