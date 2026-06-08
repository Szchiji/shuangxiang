from enum import IntEnum
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes


class Role(IntEnum):
    USER        = 0
    MODERATOR   = 1
    ADMIN       = 2
    SUPER_ADMIN = 3

    @property
    def label(self) -> str:
        return {
            Role.USER:        "👤 普通用户",
            Role.MODERATOR:   "🟡 群管员",
            Role.ADMIN:       "🟠 管理员",
            Role.SUPER_ADMIN: "🔴 超级管理员",
        }[self]


def require_role(min_role: Role) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            from core.database import Database
            uid         = update.effective_user.id
            super_admin = self.config["bot"]["admin_id"]
            db          = Database()
            if uid == super_admin:
                return await func(self, update, ctx)
            user_role = Role(db.get_admin_role(uid))
            if user_role < min_role:
                await update.effective_message.reply_text(
                    f"⛔ *权限不足*\n\n所需权限：{min_role.label}\n您的权限：{user_role.label}",
                    parse_mode="Markdown"
                )
                return
            return await func(self, update, ctx)
        return wrapper
    return decorator


def get_role_from_config_or_db(uid: int, super_admin_id: int) -> Role:
    from core.database import Database
    if uid == super_admin_id:
        return Role.SUPER_ADMIN
    return Role(Database().get_admin_role(uid))
