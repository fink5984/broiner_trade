from fastapi import Header, HTTPException

from .config import settings as cfg_settings


def require_admin(x_admin_token: str | None = Header(default=None)) -> str:
    if not cfg_settings.admin_token or x_admin_token != cfg_settings.admin_token:
        raise HTTPException(401, "נדרש טוקן מנהל תקין")
    return "admin"
