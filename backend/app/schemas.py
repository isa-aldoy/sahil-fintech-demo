"""Request and response shapes. Unknown fields are rejected, lengths are bounded."""
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .money import parse_bhd

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _clean(text: str) -> str:
    if _CONTROL.search(text):
        raise ValueError("Remove unusual characters and try again.")
    return text


class RegisterIn(Strict):
    email: str = Field(max_length=254)
    full_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if not _EMAIL.match(v):
            raise ValueError("Enter a valid e-mail address.")
        return v.lower()

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _clean(v)


class LoginIn(Strict):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.lower()


class RefreshIn(Strict):
    refresh_token: str = Field(min_length=20, max_length=200)


class ChangePasswordIn(Strict):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    handle: str
    full_name: str


class AuthOut(TokensOut):
    user: UserOut


class AccountOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    number: str
    balance_fils: int
    balance: str
    currency: str = "BHD"


class AmountIn(Strict):
    amount: str = Field(max_length=12, description="Decimal BHD as text, e.g. \"12.500\"")

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: str) -> str:
        parse_bhd(v)
        return v

    @property
    def fils(self) -> int:
        return parse_bhd(self.amount)


class TransferIn(AmountIn):
    from_account_id: uuid.UUID
    to: str = Field(min_length=2, max_length=40, description="Recipient @handle, account number, or your own account id")
    note: str = Field(default="", max_length=140)

    @field_validator("note", "to")
    @classmethod
    def _text(cls, v: str) -> str:
        return _clean(v)


class TransferOut(BaseModel):
    id: uuid.UUID
    amount_fils: int
    amount: str
    kind: str
    note: str
    to_name: str
    from_balance_fils: int
    from_balance: str
    created_at: datetime


class TransactionOut(BaseModel):
    id: int
    transfer_id: uuid.UUID
    account_id: uuid.UUID
    amount_fils: int
    amount: str
    direction: str
    title: str
    category: str
    note: str
    kind: str
    created_at: datetime


class RecipientOut(BaseModel):
    handle: str
    display_name: str


class CardOut(BaseModel):
    id: uuid.UUID
    last4: str
    expiry: str
    holder: str
    frozen: bool
    online_payments: bool


class CardPatch(Strict):
    frozen: bool | None = None
    online_payments: bool | None = None


class SessionOut(BaseModel):
    id: uuid.UUID
    device: str
    created_at: datetime
    last_seen_at: datetime
    current: bool


class ChatIn(Strict):
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def _msg(cls, v: str) -> str:
        return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v)
