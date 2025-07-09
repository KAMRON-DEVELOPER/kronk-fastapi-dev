from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import ARRAY, TIMESTAMP, Enum, ForeignKey, String, Text, UniqueConstraint, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from apps.users_app.models import BaseModel, UserModel
from utility.my_enums import GroupType, MemberType


class MessageBaseModel(BaseModel):
    __abstract__ = True
    sender_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="user_table.id", ondelete="CASCADE"))
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_urls: Mapped[Optional[list[str]]] = mapped_column(ARRAY(item_type=String), nullable=True)
    video_urls: Mapped[Optional[list[str]]] = mapped_column(ARRAY(item_type=String), nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), default=None, nullable=True)


class GroupParticipantModel(BaseModel):
    __tablename__ = "group_participant_table"
    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_user_group"),)
    member_type: Mapped["MemberType"] = mapped_column(Enum(MemberType, name="member_type"), default=MemberType.regular)
    background_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="user_table.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="group_table.id", ondelete="CASCADE"), primary_key=True)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="group_participants")
    group: Mapped["GroupModel"] = relationship(argument="GroupModel", back_populates="group_participants")


class GroupModel(BaseModel):
    __tablename__ = "group_table"
    __table_args__ = (UniqueConstraint("name", name="uq_group_name"),)
    name: Mapped[Optional[str]] = mapped_column(String(length=20), nullable=True)
    owner_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="user_table.id", ondelete="CASCADE"), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    background_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(length=200), nullable=True)
    group_type: Mapped["GroupType"] = mapped_column(Enum(GroupType, name="group_type"), default=GroupType.public)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    group_messages: Mapped[list["GroupMessageModel"]] = relationship(back_populates="group", passive_deletes=True)
    group_participants: Mapped[list["GroupParticipantModel"]] = relationship(argument="GroupParticipantModel", back_populates="group", cascade="all, delete-orphan")
    users: Mapped[list["UserModel"]] = relationship(secondary="group_participant_table", back_populates="groups", viewonly=True)
    members_count: Mapped[int] = column_property(select(func.count(GroupParticipantModel.id)).where(text("group_id = id")).scalar_subquery())
    administrators_count: Mapped[int] = column_property(
        select(func.count(GroupParticipantModel.id)).where(text("group_id = id")).where(GroupParticipantModel.member_type == MemberType.administrator).scalar_subquery()
    )
    moderators_count: Mapped[int] = column_property(
        select(func.count(GroupParticipantModel.id)).where(text("group_id = id")).where(GroupParticipantModel.member_type == MemberType.moderator).scalar_subquery()
    )


class GroupMessageModel(MessageBaseModel):
    __tablename__ = "group_message_table"
    group_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="group_table.id", ondelete="CASCADE"))
    group: Mapped["GroupModel"] = relationship(back_populates="group_messages", passive_deletes=True)
    sender: Mapped["UserModel"] = relationship(back_populates="group_messages", passive_deletes=True)


class ChatParticipantModel(BaseModel):
    __tablename__ = "chat_participant_table"
    __table_args__ = (UniqueConstraint("user_id", "chat_id", name="uq_user_chat"),)
    background_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="user_table.id", ondelete="CASCADE"), primary_key=True)
    chat_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="chat_table.id", ondelete="CASCADE"), primary_key=True)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="chat_participants")
    chat: Mapped["ChatModel"] = relationship(argument="ChatModel", back_populates="chat_participants")


class ChatModel(BaseModel):
    __tablename__ = "chat_table"
    last_message_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    chat_participants: Mapped[list["ChatParticipantModel"]] = relationship(argument="ChatParticipantModel", back_populates="chat", cascade="all, delete-orphan")
    chat_messages: Mapped[list["ChatMessageModel"]] = relationship(argument="ChatMessageModel", back_populates="chat", cascade="all, delete-orphan")
    users: Mapped[list["UserModel"]] = relationship(secondary="chat_participant_table", back_populates="chats", viewonly=True)


class ChatMessageModel(MessageBaseModel):
    __tablename__ = "chat_message_table"
    chat_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="chat_table.id", ondelete="CASCADE"))
    chat: Mapped["ChatModel"] = relationship(argument="ChatModel", back_populates="chat_messages", passive_deletes=True)
    sender: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="chat_messages", passive_deletes=True)
