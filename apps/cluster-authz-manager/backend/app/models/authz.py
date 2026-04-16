import uuid
from datetime import datetime, UTC
from sqlalchemy import Column, String, DateTime, ForeignKey, Table, JSON, Boolean, Integer
from sqlalchemy.orm import relationship
from .base import Base

# Association table for Role-Permission mapping
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String, ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", String, ForeignKey("permissions.id"), primary_key=True),
)

class AppProfile(Base):
    __tablename__ = "app_profiles"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    slug = Column(String, unique=True, index=True, nullable=False) # e.g. "sandboxed-react-agent"
    name = Column(String, nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    
    # App-specific rule blocks (e.g. sandbox_rules for SRA)
    config_rules = Column(JSON, default=dict)
    
    roles = relationship("Role", back_populates="app_profile", cascade="all, delete-orphan")
    permissions = relationship("Permission", back_populates="app_profile", cascade="all, delete-orphan")
    group_bindings = relationship("GroupRoleBinding", back_populates="app_profile", cascade="all, delete-orphan")
    user_bindings = relationship("UserRoleBinding", back_populates="app_profile", cascade="all, delete-orphan")

class Role(Base):
    __tablename__ = "roles"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    app_profile_id = Column(String, ForeignKey("app_profiles.id"), nullable=False)
    name = Column(String, nullable=False) # e.g. "ops_admin"
    description = Column(String)
    
    app_profile = relationship("AppProfile", back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

class Permission(Base):
    __tablename__ = "permissions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    app_profile_id = Column(String, ForeignKey("app_profiles.id"), nullable=False)
    name = Column(String, nullable=False) # e.g. "sandbox.template.python-runtime-template-pydata"
    description = Column(String)
    
    app_profile = relationship("AppProfile", back_populates="permissions")
    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

class GroupRoleBinding(Base):
    __tablename__ = "group_role_bindings"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    app_profile_id = Column(String, ForeignKey("app_profiles.id"), nullable=False)
    group_name = Column(String, nullable=False, index=True)
    role_id = Column(String, ForeignKey("roles.id"), nullable=False)
    
    app_profile = relationship("AppProfile", back_populates="group_bindings")
    role = relationship("Role")

class UserRoleBinding(Base):
    __tablename__ = "user_role_bindings"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    app_profile_id = Column(String, ForeignKey("app_profiles.id"), nullable=False)
    user_identifier = Column(String, nullable=False, index=True) # can be sub or email
    identifier_type = Column(String, nullable=False) # "sub" or "email"
    role_id = Column(String, ForeignKey("roles.id"), nullable=False)
    
    app_profile = relationship("AppProfile", back_populates="user_bindings")
    role = relationship("Role")

class KnownUser(Base):
    __tablename__ = "known_users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    subject = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, index=True)
    display_name = Column(String)
    is_active = Column(Boolean, default=True)
    notes = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    last_seen_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC))
    actor_id = Column(String)
    action = Column(String) # e.g. "update_role"
    resource_type = Column(String)
    resource_id = Column(String)
    detail = Column(JSON)
