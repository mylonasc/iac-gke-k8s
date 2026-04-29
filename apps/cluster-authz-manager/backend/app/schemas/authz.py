from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime


class PermissionBase(BaseModel):
    name: str
    description: Optional[str] = None


class PermissionCreate(PermissionBase):
    pass


class PermissionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class Permission(PermissionBase):
    id: str
    app_profile_id: str
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None


class RoleCreate(RoleBase):
    permission_ids: List[str] = []


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[List[str]] = None


class Role(RoleBase):
    id: str
    app_profile_id: str
    permissions: List[Permission] = []
    model_config = ConfigDict(from_attributes=True)


class AppProfileBase(BaseModel):
    slug: str
    name: str
    description: Optional[str] = None
    config_rules: dict = {}


class AppProfileCreate(AppProfileBase):
    pass


class AppProfile(AppProfileBase):
    id: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class GroupBindingBase(BaseModel):
    group_name: str
    role_id: str


class GroupBindingCreate(GroupBindingBase):
    pass


class GroupBinding(GroupBindingBase):
    id: str
    app_profile_id: str
    model_config = ConfigDict(from_attributes=True)


class UserBindingBase(BaseModel):
    user_identifier: str
    identifier_type: str  # "sub" or "email"
    role_id: str


class UserBindingCreate(UserBindingBase):
    pass


class UserBinding(UserBindingBase):
    id: str
    app_profile_id: str
    model_config = ConfigDict(from_attributes=True)


class KnownUserBase(BaseModel):
    subject: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None


class KnownUserCreate(KnownUserBase):
    pass


class KnownUserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class KnownUser(KnownUserBase):
    id: str
    created_at: datetime
    last_seen_at: datetime
    model_config = ConfigDict(from_attributes=True)
