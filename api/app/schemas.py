"""REST API 요청·응답 형식 (Pydantic). /docs 화면의 설명도 여기서 만들어진다."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NamePattern = Literal["date_title", "title_date", "title_only"]


class SettingsIn(BaseModel):
    courses: list[str] = Field(default_factory=list, max_length=50,
                               description="내 과목 목록. '기계학습: 머신러닝, ML'처럼 별칭을 쓸 수 있음")
    name_pattern: NamePattern = "date_title"
    analyze_images: bool = Field(True, description="이미지 내용을 AI로 분석할지 (끄면 이름·내 컴퓨터 OCR로만 분류)")
    extra_sensitive_keywords: list[str] = Field(default_factory=list, max_length=100)
    keep_good_names: bool = Field(True, description="원래 이름만 봐도 알 수 있는 파일은 이름을 바꾸지 않고 폴더만 옮김")


class SettingsOut(SettingsIn):
    target_dir: str
    llm_mode: str
    gemini_model: str
    ocr_enabled: bool
    demo_reset_available: bool


class PlanCreate(BaseModel):
    max_files: int | None = Field(None, ge=1, le=1000, description="한 번에 살펴볼 최대 파일 수")


class PlanItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_rel: str
    size: int
    ext: str
    kind: str
    category: str
    course: str
    title: str
    date: str
    summary: str
    keywords: list[str]
    new_name: str
    dest_dir: str
    include: bool
    sensitive: bool
    sensitive_reason: str
    flags: list[str]
    source: str
    error: str | None
    preview: str


class PlanItemUpdate(BaseModel):
    new_name: str | None = Field(None, max_length=200)
    dest_dir: str | None = Field(None, max_length=200)
    include: bool | None = None


class PlanSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    status: str
    llm_source: str
    total: int


class PlanOut(PlanSummary):
    items: list[PlanItemOut]


class MoveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_rel: str
    dst_rel: str
    status: str
    error: str | None


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    created_at: datetime
    undone_at: datetime | None
    moved: int
    skipped: int
    moves: list[MoveOut]


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path_rel: str
    original_name: str
    title: str
    category: str
    course: str
    date: str
    summary: str
    keywords: list[str]
    sensitive: bool
    size: int
    ext: str


class SearchHit(BaseModel):
    file: FileOut
    reason: str
    score: float


class SearchOut(BaseModel):
    query: str
    answer: str
    source: str
    results: list[SearchHit]


class TreeNode(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int = 0
    children: list[TreeNode] = Field(default_factory=list)


class WatcherOut(BaseModel):
    running: bool          # 감시 데몬이 최근에 상태를 갱신했는가
    state: str             # idle | analyzing | off
    loose: int
    ready: int
    failed: int
    message: str
    updated_at: datetime | None


class StatsOut(BaseModel):
    target_dir: str
    loose_files: int
    organized_files: int
    by_category: dict[str, int]
    last_batch_id: int | None
