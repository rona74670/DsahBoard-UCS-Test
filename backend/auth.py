"""
Authentication -- local users + Active Directory (allegronet.co.il).
JWT (HS256) via python-jose. Password hashing via bcrypt.
Run setup_password.ps1 to configure the local fallback user.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

JWT_SECRET   = os.getenv("JWT_SECRET", "")
JWT_ALGO     = "HS256"
JWT_EXPIRE_H = int(os.getenv("JWT_EXPIRE_HOURS", "8"))

AD_SERVER       = os.getenv("AD_SERVER", "")
AD_DOMAIN       = os.getenv("AD_DOMAIN", "allegronet.co.il")
AD_BASE_DN      = os.getenv("AD_BASE_DN", "DC=allegronet,DC=co,DC=il")
AD_ADMINS_GROUP = os.getenv("AD_ADMINS_GROUP", "Tatayas Admins")
AD_USERS_GROUP  = os.getenv("AD_USERS_GROUP", "Tatayas Users")

if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET is not set. Add JWT_SECRET=<random-hex> to backend/.env "
        "and restart the service. Run: python -c \"import secrets; print(secrets.token_hex(32))\""
    )


# ── Password verification (bcrypt direct) ───────────────────────────────────
def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── Local user store ─────────────────────────────────────────────────────────
def _load_local_users() -> dict:
    users: dict = {}
    for key, val in os.environ.items():
        if key.startswith("LOCAL_USER_") and not key.endswith("_HASH"):
            username = val.strip().lower()
            hashed   = os.getenv(key + "_HASH", "").strip()
            if username and hashed:
                users[username] = hashed
    return users


LOCAL_USERS: dict = _load_local_users()


def authenticate_local(username: str, password: str) -> Optional[dict]:
    """Local fallback users are always admins."""
    plain = username.strip().lower()
    hashed = LOCAL_USERS.get(plain)
    if hashed and verify_password(password, hashed):
        return {"username": plain, "role": "admin"}
    return None


# ── Active Directory authentication ─────────────────────────────────────────
def _parse_username(username: str) -> str:
    """Extract plain SAMAccountName from domain\\user or user@domain."""
    u = username.strip()
    if "\\" in u:
        u = u.split("\\", 1)[1]
    elif "@" in u:
        u = u.split("@", 1)[0]
    return u.strip()


def authenticate_ad(username: str, password: str) -> Optional[dict]:
    """Bind to AD as the user, check group membership, return role."""
    if not AD_SERVER or not password:
        return None

    plain = _parse_username(username)
    if not plain:
        return None

    upn = f"{plain}@{AD_DOMAIN}"

    try:
        from ldap3 import Server as _LServer, Connection, SIMPLE, SUBTREE
        from ldap3.utils.conv import escape_filter_chars
        from ldap3.core.exceptions import LDAPException

        ldap_srv = _LServer(AD_SERVER, connect_timeout=5, get_info=None)
        conn = Connection(
            ldap_srv, user=upn, password=password,
            authentication=SIMPLE, auto_bind=True, read_only=True,
        )
    except Exception:
        return None

    try:
        conn.search(
            AD_BASE_DN,
            f"(sAMAccountName={escape_filter_chars(plain)})",
            search_scope=SUBTREE,
            attributes=["memberOf"],
        )
        if not conn.entries:
            return None

        member_of = []
        try:
            member_of = [str(g) for g in conn.entries[0]["memberOf"].values]
        except Exception as _me:
            print(f"[auth] {plain}: could not read memberOf from AD — {_me}")

        role = None
        for group_dn in member_of:
            # Extract CN= value from the DN
            cn_part = group_dn.split(",")[0]
            cn = cn_part[3:] if cn_part.upper().startswith("CN=") else cn_part
            if cn.lower() == AD_ADMINS_GROUP.lower():
                role = "admin"
                break
            elif cn.lower() == AD_USERS_GROUP.lower():
                role = "user"

        if not role:
            return None

        return {"username": plain.lower(), "role": role}

    except Exception:
        return None
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


# ── JWT helpers ──────────────────────────────────────────────────────────────
def create_access_token(username: str, role: str = "admin") -> str:
    expire  = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_H)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])


# ── FastAPI Bearer dependency ────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = request.cookies.get("auth_token", "")
    if not token and creds:
        token = creds.credentials
    if not token:
        raise exc
    try:
        payload  = decode_token(token)
        username = payload.get("sub")
        if not username:
            raise exc
        return {
            "username": username,
            "role": payload.get("role", "user"),
            "payload": payload,
        }
    except JWTError:
        raise exc


def require_admin(user: dict = Depends(get_current_user)) -> str:
    role = str(user.get("role", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return str(user.get("username", ""))
