from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from core.database import Database
from web.auth import (
    verify_password, create_access_token, decode_token,
    oauth2_scheme, get_secret_key,
)


def create_app(config: dict) -> FastAPI:
    app        = FastAPI(title="双享Bot 管理面板", version="1.0.0")
    db         = Database()
    secret_key = get_secret_key(config)
    WEB_USER   = config.get("web", {}).get("username", "admin")
    WEB_PASS   = config.get("web", {}).get("password", "admin")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
        payload = decode_token(token, secret_key)
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="无效令牌")
        return username

    # ── 认证 ─────────────────────────────────────────────────

    @app.post("/api/auth/login")
    async def login(form_data: OAuth2PasswordRequestForm = Depends()):
        if form_data.username != WEB_USER or form_data.password != WEB_PASS:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = create_access_token({"sub": form_data.username}, secret_key)
        return {"access_token": token, "token_type": "bearer"}

    # ── 仪表盘 ────────────────────────────────────────────────

    @app.get("/api/dashboard")
    async def dashboard(user=Depends(get_current_user)):
        counts  = db.get_user_count()
        tenants = db.get_all_tenants()
        return {
            "users":   counts,
            "tenants": len(tenants),
            "admins":  len(db.get_all_admins()),
        }

    # ── 用户管理 ──────────────────────────────────────────────

    @app.get("/api/users")
    async def list_users(user=Depends(get_current_user)):
        return [{**dict(u)} for u in db.get_all_users(include_banned=True)]

    @app.post("/api/users/{uid}/ban")
    async def ban_user(uid: int, user=Depends(get_current_user)):
        db.ban_user(uid)
        return {"ok": True}

    @app.post("/api/users/{uid}/unban")
    async def unban_user(uid: int, user=Depends(get_current_user)):
        db.unban_user(uid)
        return {"ok": True}

    # ── 租户管理 ──────────────────────────────────────────────

    @app.get("/api/tenants")
    async def list_tenants(user=Depends(get_current_user)):
        rows = db.get_all_tenants()
        return [{k: v for k, v in dict(r).items() if k != "token"} for r in rows]

    @app.post("/api/tenants/{tid}/deactivate")
    async def deactivate_tenant(tid: int, user=Depends(get_current_user)):
        db.deactivate_tenant(tid)
        return {"ok": True}

    @app.post("/api/tenants/{tid}/activate")
    async def activate_tenant(tid: int, user=Depends(get_current_user)):
        db.activate_tenant(tid)
        return {"ok": True}

    # ── 商店管理 ──────────────────────────────────────────────

    class CategoryIn(BaseModel):
        name:      str
        emoji:     str = "📦"
        tenant_id: Optional[int] = None

    class ProductIn(BaseModel):
        category_id: int
        name:        str
        description: str = ""
        price:       float
        stock:       int  = -1
        image_url:   str  = ""
        tenant_id:   Optional[int] = None

    @app.get("/api/store/categories")
    async def list_categories(tenant_id: Optional[int] = None, user=Depends(get_current_user)):
        return [dict(c) for c in db.get_categories(tenant_id)]

    @app.post("/api/store/categories")
    async def add_category(data: CategoryIn, user=Depends(get_current_user)):
        cid = db.add_category(data.tenant_id, data.name, data.emoji)
        return {"id": cid}

    @app.get("/api/store/products")
    async def list_products(tenant_id: Optional[int] = None, user=Depends(get_current_user)):
        return [dict(p) for p in db.get_all_products(tenant_id)]

    @app.post("/api/store/products")
    async def add_product(data: ProductIn, user=Depends(get_current_user)):
        pid = db.add_product(
            data.tenant_id, data.category_id, data.name,
            data.description, data.price, data.stock, data.image_url)
        return {"id": pid}

    @app.delete("/api/store/products/{pid}")
    async def delete_product(pid: int, user=Depends(get_current_user)):
        db.delete_product(pid)
        return {"ok": True}

    # ── 订单管理 ──────────────────────────────────────────────

    @app.get("/api/orders")
    async def list_orders(tenant_id: Optional[int] = None, user=Depends(get_current_user)):
        return [dict(o) for o in db.get_orders(tenant_id=tenant_id)]

    @app.post("/api/orders/{oid}/status")
    async def update_order_status(oid: int, status: str, user=Depends(get_current_user)):
        db.update_order_status(oid, status)
        return {"ok": True}

    # ── 表单管理 ──────────────────────────────────────────────

    @app.get("/api/forms")
    async def list_forms(tenant_id: Optional[int] = None, user=Depends(get_current_user)):
        return [dict(f) for f in db.get_forms(tenant_id)]

    @app.get("/api/forms/{fid}/responses")
    async def list_responses(fid: int, user=Depends(get_current_user)):
        return [dict(r) for r in db.get_form_responses(fid)]

    # ── 健康检查 ──────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
