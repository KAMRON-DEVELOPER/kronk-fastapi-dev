from datetime import datetime
from typing import Optional

from sqlalchemy import ARRAY, TIMESTAMP, UUID, Enum, ForeignKey, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from apps.users_app.models import BaseModel, UserModel
from utility.my_enums import CommentMode, EngagementType, FeedVisibility, ReportReason


class CategoryModel(BaseModel):
    __tablename__ = "category_table"
    name: Mapped[str] = mapped_column(String(length=50), nullable=False, unique=True)
    categories: Mapped[list["FeedModel"]] = relationship(argument="FeedModel", back_populates="category")

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
    feed_id: Mapped[UUID] = mapped_column(ForeignKey(column="feed_table.id"), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey(column="tag_table.id"), primary_key=True)
    feed: Mapped["FeedModel"] = relationship(back_populates="tag_links", overlaps="feeds, tags")
    tag: Mapped["TagModel"] = relationship(back_populates="feed_links", overlaps="feeds")


class FeedModel(BaseModel):
    __tablename__ = "feed_table"
    author_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"), nullable=False)
    body: Mapped[str] = mapped_column(String(200))
    image_urls: Mapped[Optional[list]] = mapped_column(ARRAY(item_type=String, dimensions=4), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scheduled_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    comment_mode: Mapped[CommentMode] = mapped_column(Enum(CommentMode, name="comment_model"), default=CommentMode.everyone)
    feed_visibility: Mapped[FeedVisibility] = mapped_column(Enum(FeedVisibility, name="feed_visibility"), default=FeedVisibility.public)
    category_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("category_table.id"))
    quoted_feed_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("feed_table.id"))
    author_username: Mapped[str] = column_property(select(func.count(UserModel.id)).where(UserModel.id == author_id).correlate_except(UserModel).scalar_subquery())
    author: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feeds")
    category: Mapped[Optional["CategoryModel"]] = relationship(argument="CategoryModel", back_populates="categories")
    feed_comments: Mapped[list["FeedCommentModel"]] = relationship(argument="FeedCommentModel", back_populates="feed")
    feed_engagements: Mapped[list["FeedEngagementModel"]] = relationship(argument="FeedEngagementModel", back_populates="feed")
    feed_views: Mapped[list["FeedViewModel"]] = relationship(argument="FeedViewModel", back_populates="feed")
    feed_bookmarks: Mapped[list["FeedBookmarkModel"]] = relationship(back_populates="feed")
    feed_reports: Mapped[list["FeedReportModel"]] = relationship(back_populates="feed")
    reposts: Mapped[list["RepostModel"]] = relationship(argument="RepostModel", back_populates="feed")
    quoted_feed: Mapped[Optional["FeedModel"]] = relationship(remote_side="FeedModel.id", back_populates="quotes")
    quotes: Mapped[list["FeedModel"]] = relationship(back_populates="quoted_feed", cascade="all, delete-orphan")
    tag_links: Mapped[list["FeedTagLink"]] = relationship(back_populates="feed", overlaps="feeds, tags", cascade="all, delete-orphan")
    tags: Mapped[list["TagModel"]] = relationship(secondary="feed_tag_link_table", back_populates="feeds", overlaps="feed_links,feed,tag")

    def __repr__(self):
        return "FeedModel"


class RepostModel(BaseModel):
    __tablename__ = "repost_table"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"))
    feed_id: Mapped[UUID] = mapped_column(ForeignKey("feed_table.id"))
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="reposts")
    feed: Mapped["FeedModel"] = relationship(argument="FeedModel", back_populates="reposts")


class FeedCommentModel(BaseModel):
    __tablename__ = "feed_comment_table"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"))
    feed_id: Mapped[UUID] = mapped_column(ForeignKey("feed_table.id"))
    parent_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("feed_comment_table.id"), nullable=True)
    body: Mapped[str] = mapped_column(String(200))
    image_urls: Mapped[Optional[list]] = mapped_column(ARRAY(item_type=String, dimensions=4), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feed_comments")
    feed: Mapped["FeedModel"] = relationship(argument="FeedModel", back_populates="feed_comments")
    parent: Mapped[Optional["FeedCommentModel"]] = relationship(argument="FeedCommentModel", remote_side="FeedCommentModel.id", back_populates="replies")
    replies: Mapped[list["FeedCommentModel"]] = relationship(back_populates="parent")
    feed_comment_engagements: Mapped[list["FeedCommentEngagementModel"]] = relationship(argument="FeedCommentEngagementModel", back_populates="feed_comment")
    feed_comment_views: Mapped[list["FeedCommentViewModel"]] = relationship(argument="FeedCommentViewModel", back_populates="feed_comment")

    def __repr__(self):
        return "FeedCommentModel"


class FeedEngagementModel(BaseModel):
    __tablename__ = "feed_engagement_table"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", name="uq_feed_engagement"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"))
    feed_id: Mapped[UUID] = mapped_column(ForeignKey("feed_table.id"))
    engagement_type: Mapped[EngagementType] = mapped_column(Enum(EngagementType, name="engagement_type"), nullable=False)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feed_engagements")
    feed: Mapped["FeedModel"] = relationship(argument="FeedModel", back_populates="feed_engagements")

    def __repr__(self):
        return "FeedEngagementModel"


class FeedCommentEngagementModel(BaseModel):
    __tablename__ = "feed_comment_engagement_table"
    __table_args__ = (UniqueConstraint("user_id", "feed_comment_id", name="uq_feed_comment_engagement"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"))
    feed_comment_id: Mapped[UUID] = mapped_column(ForeignKey("feed_comment_table.id"))
    engagement_type: Mapped[EngagementType] = mapped_column(Enum(EngagementType, name="engagement_type"), nullable=False)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feed_comment_engagements")
    feed_comment: Mapped["FeedCommentModel"] = relationship(argument="FeedCommentModel", back_populates="feed_comment_engagements")

    def __repr__(self):
        return "FeedCommentEngagementModel"


class FeedViewModel(BaseModel):
    __tablename__ = "feed_view_table"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", name="uq_feed_view"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"))
    feed_id: Mapped[UUID] = mapped_column(ForeignKey("feed_table.id"))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feed_views")
    feed: Mapped["FeedModel"] = relationship(argument="FeedModel", back_populates="feed_views")

    def __repr__(self):
        return "FeedViewModel"


class FeedCommentViewModel(BaseModel):
    __tablename__ = "feed_comment_view_table"
    __table_args__ = (UniqueConstraint("user_id", "feed_comment_id", name="uq_feed_comment_view"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"))
    feed_comment_id: Mapped[UUID] = mapped_column(ForeignKey("feed_comment_table.id"))
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feed_comment_views")
    feed_comment: Mapped["FeedCommentModel"] = relationship(argument="FeedCommentModel", back_populates="feed_comment_views")


class FeedBookmarkModel(BaseModel):
    __tablename__ = "feed_bookmark_table"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", name="uq_feed_bookmark"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"))
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feed_bookmarks")
    feed_id: Mapped[UUID] = mapped_column(ForeignKey("feed_table.id"))
    feed: Mapped["FeedModel"] = relationship(argument="FeedModel", back_populates="feed_bookmarks")


class FeedReportModel(BaseModel):
    __tablename__ = "feed_report_table"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", name="uq_feed_report"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id"))
    feed_id: Mapped[UUID] = mapped_column(ForeignKey("feed_table.id"))
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="feed_reports")
    feed: Mapped["FeedModel"] = relationship(argument="FeedModel", back_populates="feed_reports")
    report_reason: Mapped[ReportReason] = mapped_column(Enum(ReportReason, name="report_reason"), nullable=False)
