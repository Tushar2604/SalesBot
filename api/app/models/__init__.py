"""SQLAlchemy models.

Every model module must be imported here so Alembic autogenerate and
`Base.metadata` see the full schema.
"""

from app.models.assistant import AssistantProfile, KnowledgeItem
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
from app.models.integrations import ApiKey, DeliveryStatus, WebhookDelivery, WebhookEndpoint
from app.models.lead_search import LeadSearch
from app.models.leads import (
    BlocklistEntry,
    BlocklistKind,
    ContactedLead,
    ImportStatus,
    Lead,
    LeadList,
    LeadSource,
)
from app.models.linkedin import (
    AccountRiskEvent,
    LinkedInAccount,
    LinkedInAccountStatus,
    Proxy,
    ProxyStatus,
)
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
    "AccountRiskEvent",
    "ActionTask",
    "ApiKey",
    "AssistantProfile",
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
    "DeliveryStatus",
    "EnrollmentState",
    "ImportStatus",
    "InviteStatus",
    "KnowledgeItem",
    "LabelSource",
    "Lead",
    "LeadList",
    "LeadSearch",
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
    "WebhookDelivery",
    "WebhookEndpoint",
    "Workspace",
    "WorkspaceInvite",
    "WorkspaceMember",
    "WorkspaceRole",
]
