from enum import Enum
from typing import TypedDict


class UserRole(str, Enum):
    ADMIN = "admin"
    REGULAR = "regular"


class UserStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class EngagementType(str, Enum):
    like = "likes"
    dislike = "dislikes"
    view = "views"


class EngagementStatus(TypedDict):
    is_liked: bool
    is_disliked: bool
    is_viewed: bool


class FeedVisibility(str, Enum):
    public = "public"
    followers = "followers"
    private = "private"
    archived = "archived"


class FollowPolicy(str, Enum):
    auto_accept = "autoAccept"
    manual_approval = "manualApproval"


class FollowStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"


class ReportReason(str, Enum):
    intellectual_property = "intellectual_property"
    spam = "spam"
    inappropriate = "inappropriate"
    misinformation = "misinformation"
    harassment = "harassment"
    hate_speech = "hateSpeech"
    violence = "violence"
    other = "other"


class ProcessStatus(str, Enum):
    pending = "pending"
    processed = "processed"
    failed = "failed"


class CommentMode(str, Enum):
    everyone = "everyone"
    followers = "followers"
    mentioned = "mentioned"
    none = "none"


class PubSubTopics(str, Enum):
    HOME_TIMELINE = "users:{follower_id}:home_timeline"
    SETTINGS_STATS = "settings:stats"


class ScreenState(str, Enum):
    home = "home"
    room = "room"


class GroupType(str, Enum):
    public = "public"
    private = "private"


class MemberType(str, Enum):
    owner = "owner"
    administrator = "administrator"
    moderator = "moderator"
    regular = "regular"
