"""DB 테이블 정의 (SQLAlchemy 2.x).

개발·테스트는 SQLite 파일, docker compose에서는 PostgreSQL 컨테이너를 쓴다 (DATABASE_URL로 전환).

| 테이블        | 내용                                               |
|---------------|----------------------------------------------------|
| app_settings  | 내 과목 목록, 이름 규칙, 이미지 분석 허용 여부        |
| plans         | 폴더를 한 번 살펴본 결과(정리 계획)                  |
| plan_items    | 계획 속 파일 1개: 원래 이름 → 새 이름·폴더, AI 분석 결과 |
| batches       | '정리하기'를 한 번 실행한 기록 (되돌리기 단위)        |
| moves         | 실제로 옮긴 파일 1개의 기록                          |
| file_records  | 검색용 색인: 지금 위치, 제목, 요약, 키워드            |
| analysis_cache| Gemini 분석 결과 저장 (같은 내용 파일은 다시 묻지 않음) |
| watcher_status| 폴더 감시 데몬의 현재 상태 (대시보드 표시용, 1행)      |
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import settings

DEFAULT_COURSES = ["오픈소스프로그래밍", "기계학습", "자료구조", "알고리즘", "확률과통계"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    courses: Mapped[list] = mapped_column(JSON, default=list)
    name_pattern: Mapped[str] = mapped_column(String(32), default="date_course_title")
    analyze_images: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_sensitive_keywords: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | applied | undone | cancelled
    llm_source: Mapped[str] = mapped_column(String(16), default="mock")
    total: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[list[PlanItem]] = relationship(back_populates="plan", cascade="all, delete-orphan",
                                                 order_by="PlanItem.id")


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    src_rel: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0.0)
    sha256: Mapped[str] = mapped_column(String(80), default="")
    ext: Mapped[str] = mapped_column(String(16), default="")
    kind: Mapped[str] = mapped_column(String(16), default="other")
    category: Mapped[str] = mapped_column(String(32), default="기타")
    course: Mapped[str] = mapped_column(String(100), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    date: Mapped[str] = mapped_column(String(10), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    new_name: Mapped[str] = mapped_column(String(255), default="")
    dest_dir: Mapped[str] = mapped_column(String(255), default="")
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    sensitive_reason: Mapped[str] = mapped_column(String(200), default="")
    flags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(16), default="mock")  # gemini | mock | fallback | rule
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview: Mapped[str] = mapped_column(Text, default="")

    plan: Mapped[Plan] = relationship(back_populates="items")


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    moved: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    moves: Mapped[list[Move]] = relationship(back_populates="batch", cascade="all, delete-orphan",
                                             order_by="Move.id")


class Move(Base):
    __tablename__ = "moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    src_rel: Mapped[str] = mapped_column(String(1024))
    dst_rel: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16), default="moved")  # moved | skipped | undone | undo_failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped[Batch] = relationship(back_populates="moves")


class FileRecord(Base):
    __tablename__ = "file_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path_rel: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    original_name: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(32), default="기타")
    course: Mapped[str] = mapped_column(String(100), default="")
    date: Mapped[str] = mapped_column(String(10), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    sha256: Mapped[str] = mapped_column(String(80), default="", index=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    ext: Mapped[str] = mapped_column(String(16), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AnalysisCache(Base):
    """Gemini가 한 번 분석한 파일 내용(SHA-256)의 결과. 같은 파일을 다시 살펴보면 호출 없이 바로 쓴다.
    key = 파일 SHA-256 + 과목 목록·이미지 허용 여부·모델 설정을 합친 해시 (설정이 바뀌면 다시 분석)."""
    __tablename__ = "analysis_cache"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    insight: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchCache(Base):
    """'말로 검색'에서 Gemini가 한 번 답한 결과. 같은 질문을 다시 하면 호출 없이 바로 쓴다.
    key = 질문(공백·대소문자 정리) + 검색 대상 파일들의 제목·요약·키워드 해시 (파일 내용이 바뀌면 다시 검색).
    Gemini가 성공한 답만 저장한다 (실패하거나 규칙 기반으로 대체된 결과는 저장하지 않음)."""
    __tablename__ = "search_cache"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)   # {"answer": str, "picks": [{"id": int, "reason": str}]}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatcherStatus(Base):
    """폴더 감시 데몬(app/watcher.py)이 주기적으로 갱신하는 상태 1행."""
    __tablename__ = "watcher_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="idle")  # idle | analyzing | off
    loose: Mapped[int] = mapped_column(Integer, default=0)          # 정리 폴더 맨 위의 파일 수
    ready: Mapped[int] = mapped_column(Integer, default=0)          # 미리 분석이 끝났거나 AI가 필요 없는 파일 수
    failed: Mapped[int] = mapped_column(Integer, default=0)         # AI 분석이 실패해 나중에 다시 할 파일 수
    message: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------
# 연결
# ---------------------------------------------------------------------------
def make_engine(url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def get_app_settings(session: Session) -> AppSettings:
    row = session.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1, courses=list(DEFAULT_COURSES), name_pattern="date_course_title",
                          analyze_images=True, extra_sensitive_keywords=[])
        session.add(row)
        session.commit()
    return row
