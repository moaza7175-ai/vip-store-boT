"""
models.py - نماذج البيانات لنظام VIP STORE LINK BRIDGE
Data Models & Schemas for Transactions, Messages, Telegram Accounts & Callbacks
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    WAITING_FOR_REPLY = "WAITING_FOR_REPLY"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class MessageDirection(str, Enum):
    OUTBOUND = "OUTBOUND"  # من حساب المستخدم إلى البوت المستقبِل
    INBOUND = "INBOUND"    # رد البوت المستقبِل إلى حساب المستخدم


class MessageType(str, Enum):
    TEXT = "text"
    PHOTO = "photo"
    DOCUMENT = "document"
    VIDEO = "video"
    VOICE = "voice"
    AUDIO = "audio"
    BUTTONS = "buttons"


class InlineButtonInfo(BaseModel):
    label: str
    data: Optional[str] = None
    url: Optional[str] = None
    row: int = 0
    col: int = 0


class BridgeMessage(BaseModel):
    id: Optional[int] = None
    transaction_id: str
    direction: MessageDirection
    message_type: MessageType
    text_content: Optional[str] = None
    media_path: Optional[str] = None
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    telegram_message_id: Optional[int] = None
    reply_to_message_id: Optional[int] = None
    has_buttons: bool = False
    buttons: Optional[List[List[InlineButtonInfo]]] = None
    created_at: Optional[str] = None


class BridgeTransaction(BaseModel):
    id: Optional[int] = None
    transaction_id: str
    user_id: int
    chat_id: int
    original_link: str
    raw_message_text: Optional[str] = None
    destination_bot: str = "MidasbuyHelp_bot"
    sent_out_message_id: Optional[int] = None
    status: TransactionStatus = TransactionStatus.PENDING
    replies_count: int = 0
    has_buttons: bool = False
    error_message: Optional[str] = None
    sent_at: Optional[str] = None
    last_reply_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    messages: List[BridgeMessage] = Field(default_factory=list)


class TelegramAccountInfo(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    phone_masked: Optional[str] = None
    is_active: bool = False
    session_status: str = "DISCONNECTED"  # CONNECTED, DISCONNECTED, EXPIRED
    last_connected_at: Optional[str] = None
    last_seen_at: Optional[str] = None


class AccountConnectRequest(BaseModel):
    api_id: int
    api_hash: str
    phone: str


class VerificationCodeSubmitRequest(BaseModel):
    phone: str
    phone_code_hash: str
    code: str


class TwoFactorSubmitRequest(BaseModel):
    password: str


class SystemSettings(BaseModel):
    forwarding_enabled: bool = True
    default_destination: str = "MidasbuyHelp_bot"
    reply_timeout_seconds: int = 60
    queue_settle_seconds: float = 3.0
    send_full_text_with_link: bool = False
