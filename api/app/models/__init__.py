"""SQLAlchemy models.

Every model module must be imported here so Alembic autogenerate and
`Base.metadata` see the full schema.
"""

from app.models.assistant import KnowledgeItem
from app.models.base import Base
from app.models.campaigns import (
    ActionTask,
    Campaign,
    CampaignLead,
    CampaignLeadEvent,
    CampaignStatus,
    CampaignStep,
    ConditionFailAction,
    DailyQuotaLedger,
    EnrollmentState,
    StepCondition,
    StepType,
    TaskStatus,
)
from app.models.content import (
    LinkedInPost,
    LinkedInPostMedia,
    MediaAsset,
    MediaKind,
    PostQueue,
    PostStatus,
    PostTemplate,
    PostVisibility,
)
from app.models.inbox import (
    Conversation,
    ConversationLabel,
    LabelSource,
    Message,
    MessageDirection,
)
from app.models.leads import (
    BlocklistEntry,
    BlocklistKind,
    ContactedLead,
    ImportStatus,
    Lead,
    LeadList,
    LeadSource,
)
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus, Proxy, ProxyStatus
from app.models.tenancy import (
    AuditEvent,
    InviteStatus,
    RefreshSession,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceRole,
)

__all__ = [
    "KnowledgeItem",
    "ActionTask",
    "AuditEvent",
    "Base",
    "BlocklistEntry",
    "BlocklistKind",
    "Campaign",
    "CampaignLead",
    "CampaignLeadEvent",
    "CampaignStatus",
    "CampaignStep",
    "ConditionFailAction",
    "ContactedLead",
    "Conversation",
    "ConversationLabel",
    "DailyQuotaLedger",
    "EnrollmentState",
    "ImportStatus",
    "InviteStatus",
    "LabelSource",
    "Lead",
    "LeadList",
    "LeadSource",
    "LinkedInAccount",
    "LinkedInAccountStatus",
    "LinkedInPost",
    "LinkedInPostMedia",
    "MediaAsset",
    "MediaKind",
    "Message",
    "MessageDirection",
    "PostQueue",
    "PostStatus",
    "PostTemplate",
    "PostVisibility",
    "Proxy",
    "ProxyStatus",
    "RefreshSession",
    "StepCondition",
    "StepType",
    "TaskStatus",
    "User",
    "Workspace",
    "WorkspaceInvite",
    "WorkspaceMember",
    "WorkspaceRole",
]
