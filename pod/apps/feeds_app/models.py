from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, UUID, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.users_app.models import BaseModel, UserModel
from utility.my_enums import EngagementType, FeedVisibility, ReportReason, CommentPolicy


class CategoryModel(BaseModel):
    __tablename__ = "category_table"
    name: Mapped[str] = mapped_column(String(length=50), nullable=False, unique=True)
    feeds: Mapped[list["FeedModel"]] = relationship(argument="FeedModel", back_populates="category")

    def __repr__(self):
        return "CategoryModel"


class TagModel(BaseModel):
    __tablename__ = "tag_table"
    name: Mapped[str] = mapped_column(String(length=50), nullable=False, unique=True)
    feed_links: Mapped[list["FeedTagLink"]] = relationship(back_populates="tag", cascade="all, delete-orphan")
    feeds: Mapped[list["FeedModel"]] = relationship(secondary="feed_tag_link_table", back_populates="tags", overlaps="feed_links, tag")

    def __repr__(self):
        return "TagModel"


class FeedTagLink(BaseModel):
    __tablename__ = "feed_tag_link_table"
    feed_id: Mapped[UUID] = mapped_column(ForeignKey(column="feed_table.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey(column="tag_table.id", ondelete="CASCADE"), primary_key=True)
    feed: Mapped["FeedModel"] = relationship(back_populates="tag_links", overlaps="feeds, tags")
    tag: Mapped["TagModel"] = relationship(back_populates="feed_links", overlaps="feeds")


class FeedModel(BaseModel):
    __tablename__ = "feed_table"
    body: Mapped[str] = mapped_column(String(200))
    author_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id", ondelete="CASCADE"), nullable=False)
    author: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feeds")
    # author_username: Mapped[str] = column_property(select(UserModel.username).where(UserModel.id == author_id).correlate_except(UserModel).scalar_subquery())
    video_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    feed_visibility: Mapped[FeedVisibility] = mapped_column(Enum(FeedVisibility, name="feed_visibility"), default=FeedVisibility.public)
    comment_policy: Mapped[CommentPolicy] = mapped_column(Enum(CommentPolicy, name="comment_policy"), default=CommentPolicy.everyone)
    quote_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("feed_table.id", ondelete="CASCADE"))
    quote: Mapped[Optional["FeedModel"]] = relationship(remote_side="FeedModel.id", back_populates="quotes", foreign_keys=[quote_id])
    quotes: Mapped[list["FeedModel"]] = relationship(back_populates="quote", foreign_keys=[quote_id], cascade="all, delete-orphan", passive_deletes=True)
    parent_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("feed_table.id", ondelete="CASCADE"))
    parent: Mapped[Optional["FeedModel"]] = relationship(remote_side="FeedModel.id", back_populates="comments", foreign_keys=[parent_id])
    comments: Mapped[list["FeedModel"]] = relationship(back_populates="parent", foreign_keys=[parent_id], cascade="all, delete-orphan", passive_deletes=True)
    category_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("category_table.id", ondelete="CASCADE"))
    category: Mapped[Optional["CategoryModel"]] = relationship(argument="CategoryModel", back_populates="feeds")
    tag_links: Mapped[list["FeedTagLink"]] = relationship(back_populates="feed", overlaps="feeds, tags", cascade="all, delete-orphan")
    tags: Mapped[list["TagModel"]] = relationship(secondary="feed_tag_link_table", back_populates="feeds", overlaps="feed_links,feed,tag")
    engagements: Mapped[list["EngagementModel"]] = relationship(argument="EngagementModel", back_populates="feed", cascade="all, delete-orphan")
    reports: Mapped[list["ReportModel"]] = relationship(argument="ReportModel", back_populates="feed", cascade="all, delete-orphan", passive_deletes=True)

    def __repr__(self):
        return "FeedModel"


class EngagementModel(BaseModel):
    __tablename__ = "engagement_table"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", "engagement_type", name="uq_feed_engagement"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id", ondelete="CASCADE"), nullable=False)
    feed_id: Mapped[UUID] = mapped_column(ForeignKey("feed_table.id", ondelete="CASCADE"), nullable=False)
    engagement_type: Mapped[EngagementType] = mapped_column(Enum(EngagementType, name="engagement_type"), nullable=False)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="engagements", passive_deletes=True)
    feed: Mapped["FeedModel"] = relationship(argument="FeedModel", back_populates="engagements", passive_deletes=True)

    def __repr__(self):
        return "FeedEngagementModel"


class ReportModel(BaseModel):
    __tablename__ = "report_table"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", "report_reason", name="uq_feed_report"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id", ondelete="CASCADE"), nullable=False)
    feed_id: Mapped[UUID] = mapped_column(ForeignKey("feed_table.id", ondelete="CASCADE"), nullable=False)
    report_reason: Mapped[ReportReason] = mapped_column(Enum(ReportReason, name="report_reason"), nullable=False)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="reports", passive_deletes=True)
    feed: Mapped["FeedModel"] = relationship(argument="FeedModel", back_populates="reports")
