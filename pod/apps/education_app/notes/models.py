# from typing import Optional
#
# from apps.users_app.models import BaseModel, UserModel
# from sqlalchemy import ForeignKey, UUID, String, Text, Boolean, Enum, JSON
# from sqlalchemy.orm import Mapped, mapped_column, relationship
#
# from utility.my_enums import ProcessStatus
#
#
# class TabModel(BaseModel):
#     __tablename__ = "tab_table"
#
#     title: Mapped[str] = mapped_column(String(length=30))
#     owner_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id", ondelete="CASCADE"))
#     owner: Mapped["UserModel"] = relationship(back_populates="tabs")
#
#     def __repr__(self):
#         return f"TabModel: {self.title}"
#
#
# class NoteModel(BaseModel):
#     __tablename__ = "note_table"
#
#     title: Mapped[str] = mapped_column(String(length=50))
#     body: Mapped[str] = mapped_column(Text)
#     is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
#     color: Mapped[Optional[str]] = mapped_column(String(length=6), nullable=True)
#
#     tab_id: Mapped[UUID] = mapped_column(ForeignKey("tab_table.id", ondelete="CASCADE"))
#     tab: Mapped["TabModel"] = relationship(back_populates="notes")
#
#     def __repr__(self):
#         return f"NoteModel: {self.title}"
#
#
# class ImageModel(BaseModel):
#     __tablename__ = "image_table"
#
#     user_id: Mapped[UUID] = mapped_column(ForeignKey("user_table.id", ondelete="CASCADE"))
#     user: Mapped["UserModel"] = relationship(back_populates="images")
#
#     file_path: Mapped[str] = mapped_column(String(length=50))
#     language_from: Mapped[str] = mapped_column(String(length=50), default="en")
#     language_to: Mapped[str] = mapped_column(String(length=50), default="uz")
#     extracted_text: Mapped[str] = mapped_column(Text)
#     is_incomplete_sentence: Mapped[bool] = mapped_column(Boolean, default=False)
#     process_status: Mapped[ProcessStatus] = mapped_column(Enum(ProcessStatus), default=ProcessStatus.PENDING)
#
#     def __repr__(self):
#         return "ImageModel"
#
#
# class VocabularyModel(BaseModel):
#     __tablename__ = "vocabulary_table"
#
#     image_id: Mapped[UUID] = mapped_column(ForeignKey(column="image_table.id", ondelete="CASCADE"))
#     image: Mapped["ImageModel"] = relationship(back_populates="vocabularies")
#
#     word: Mapped[str] = mapped_column(String(length=255))
#     translation: Mapped[str] = mapped_column(String(length=255))
#     definition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
#     part_of_speech: Mapped[str] = mapped_column(String(length=50))
#     examples: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
#     synonyms: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
#     transcription: Mapped[Optional[str]] = mapped_column(String(length=255), nullable=True)
#     audio_pronunciation_url: Mapped[str] = mapped_column(String(length=255))
#
#     tab_id: Mapped[UUID] = mapped_column(ForeignKey(column="tab_table.id", ondelete="CASCADE"))
#     tab: Mapped["TabModel"] = relationship(back_populates="vocabularies")
#
#     def __repr__(self):
#         return "VocabularyModel"
#
#
# class SentenceModel(BaseModel):
#     __tablename__ = "sentence_model"
#
#     image_id: Mapped[UUID] = mapped_column(ForeignKey("image.id", ondelete="CASCADE"))
#     image: Mapped["ImageModel"] = relationship(back_populates="sentences")
#
#     body: Mapped[str] = mapped_column(Text)
#     translation: Mapped[str] = mapped_column(Text)
#
#     tab_id: Mapped[UUID] = mapped_column(ForeignKey("tab_model.id", ondelete="CASCADE"))
#     tab: Mapped["TabModel"] = relationship(back_populates="sentences")
#
#     def __repr__(self):
#         return "SentenceModel"
