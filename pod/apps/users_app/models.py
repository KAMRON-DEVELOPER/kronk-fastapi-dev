from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func, select, text
from sqlalchemy import TIMESTAMP
from sqlalchemy import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column, relationship

from utility.my_enums import FollowPolicy, FollowStatus, UserRole, UserStatus

if TYPE_CHECKING:
    from ..chats_app.models import ChatMessageModel, ChatModel, ChatParticipantModel, GroupMessageModel, GroupModel, GroupParticipantModel
    from ..feeds_app.models import EngagementModel, FeedModel, ReportModel


class Base(DeclarativeBase):
    pass


class BaseModel(Base):
    __abstract__ = True
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    created_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), default=func.now())
    updated_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())


class FollowModel(BaseModel):
    __tablename__ = "follow_table"
    __table_args__ = (UniqueConstraint("follower_id", "following_id", name="uq_follower_following"),)
    follower_id: Mapped[UUID] = mapped_column(ForeignKey(column="user_table.id", ondelete="CASCADE"))
    following_id: Mapped[UUID] = mapped_column(ForeignKey(column="user_table.id", ondelete="CASCADE"))
    follow_status: Mapped[FollowStatus] = mapped_column(Enum(FollowStatus, name="follow_status"), default=FollowStatus.accepted)
    follower: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="followings", foreign_keys=[follower_id])
    following: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="followers", foreign_keys=[following_id])

    def __repr__(self):
        return "FollowModel"


class UserModel(BaseModel):
    __tablename__ = "user_table"

    name: Mapped[str] = mapped_column(String(length=50), nullable=True)
    username: Mapped[str] = mapped_column(String(length=50), index=True)
    email: Mapped[str] = mapped_column(String(length=50), index=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(length=50), nullable=True)
    password: Mapped[str] = mapped_column(String(length=120))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(length=50), nullable=True)
    banner_url: Mapped[Optional[str]] = mapped_column(String(length=50), nullable=True)
    banner_color: Mapped[Optional[str]] = mapped_column(String(length=50), nullable=True)
    birthdate: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String(length=50), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(length=50), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(length=50), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.regular)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus, name="user_status"), default=UserStatus.active)
    follow_policy: Mapped[FollowPolicy] = mapped_column(Enum(FollowPolicy, name="follow_policy"), default=FollowPolicy.auto_accept)

    followers_count: Mapped[int] = column_property(select(func.count(FollowModel.id)).where(text("following_id = id")).correlate_except(FollowModel).scalar_subquery())
    followings_count: Mapped[int] = column_property(select(func.count(FollowModel.id)).where(text("follower_id = id")).correlate_except(FollowModel).scalar_subquery())

    followers: Mapped[list["FollowModel"]] = relationship(
        argument="FollowModel", back_populates="following", foreign_keys="[FollowModel.following_id]", cascade="all, delete-orphan"
    )
    followings: Mapped[list["FollowModel"]] = relationship(
        argument="FollowModel", back_populates="follower", foreign_keys="[FollowModel.follower_id]", cascade="all, delete-orphan"
    )
    feeds: Mapped[list["FeedModel"]] = relationship(argument="FeedModel", back_populates="author")
    engagements: Mapped[list["EngagementModel"]] = relationship(argument="EngagementModel", back_populates="user", passive_deletes=True)
    reports: Mapped[list["ReportModel"]] = relationship(argument="ReportModel", back_populates="user")

    group_participants: Mapped[list["GroupParticipantModel"]] = relationship(argument="GroupParticipantModel", back_populates="user")
    groups: Mapped[list["GroupModel"]] = relationship(secondary="group_participant_table", back_populates="users", viewonly=True)
    group_messages: Mapped[list["GroupMessageModel"]] = relationship(argument="GroupMessageModel", back_populates="sender")
    chat_participants: Mapped[list["ChatParticipantModel"]] = relationship(argument="ChatParticipantModel", back_populates="user")
    chats: Mapped[list["ChatModel"]] = relationship(secondary="chat_participant_table", back_populates="users", viewonly=True)
    chat_messages: Mapped[list["ChatMessageModel"]] = relationship(argument="ChatMessageModel", back_populates="sender")

    def __repr__(self):
        return f"UserModel of {self.username}"
