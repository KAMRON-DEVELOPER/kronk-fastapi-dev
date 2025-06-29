from enum import Enum, auto
from typing import TypedDict


class AutoName(Enum):
    @staticmethod
    def _generate_next_value_(name, start, count, last_values):
        return name


class UserRole(AutoName):
    admin = auto()
    regular = auto()


class UserStatus(AutoName):
    active = auto()
    inactive = auto()


class EngagementType(AutoName):
    reposts = auto()
    quotes = auto()
    likes = auto()
    views = auto()
    bookmarks = auto()


class EngagementStatus(TypedDict):
    is_reposted: bool
    is_quoted: bool
    is_liked: bool
    is_viewed: bool
    is_bookmarked: bool


class FeedVisibility(AutoName):
    public = auto()
    followers = auto()
    private = auto()
    archived = auto()


class FollowPolicy(Enum):
    @staticmethod
    def _generate_next_value_(name, start, count, last_values):
        # Converts snake_case to camelCase
        parts = name.split("_")
        return parts[0] + parts[1].capitalize()

    auto_accept = auto()
    manual_approval = auto()


class FollowStatus(AutoName):
    pending = auto()
    accepted = auto()
    declined = auto()


class ReportReason(AutoName):
    copyright_infringement = auto()
    spam = auto()
    nudity_or_sexual_content = auto()
    misinformation = auto()
    harassment_or_bullying = auto()
    hate_speech = auto()
    violence_or_threats = auto()
    self_harm_or_suicide = auto()
    impersonation = auto()
    other = auto()


class ProcessStatus(AutoName):
    pending = auto()
    processed = auto()
    failed = auto()


class CommentPolicy(AutoName):
    everyone = auto()
    followers = auto()


class PubSubTopics(AutoName):
    HOME_TIMELINE = "users:{follower_id}:home_timeline"
    SETTINGS_STATS = "settings:stats"


class GroupType(AutoName):
    public = auto()
    private = auto()


class MemberType(AutoName):
    owner = auto()
    administrator = auto()
    moderator = auto()
    regular = auto()


class RoomType(AutoName):
    in_home = auto()
    in_room = auto()


class ChatEvent(AutoName):
    typing_start = auto()
    typing_stop = auto()
    goes_online = auto()
    goes_offline = auto()
    enter_chat = auto()
    exit_chat = auto()
    created_chat = auto()
    sent_message = auto()
