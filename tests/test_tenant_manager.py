"""租户管理器：轮询任务失效处理测试。"""

import asyncio

from telegram.error import InvalidToken, NetworkError

from core.tenant_manager import TenantManager


def _manager(db):
    tm = TenantManager({})
    tm.db = db
    return tm


async def test_invalid_token_deactivates_tenant(db):
    db.add_tenant("123:abc", owner_user_id=10, bot_id=1,
                  bot_username="x_bot", bot_name="X")
    tid = db.get_active_tenants()[0]["id"]
    tm = _manager(db)
    stopped = []
    tm.stop_tenant = lambda t: stopped.append(t) or _noop()
    await tm._on_polling_failure(tid, InvalidToken())
    assert db.get_tenant(tid)["is_active"] == 0
    assert stopped == [tid]


async def test_other_error_keeps_tenant_active(db):
    db.add_tenant("123:abc", owner_user_id=10, bot_id=1,
                  bot_username="x_bot", bot_name="X")
    tid = db.get_active_tenants()[0]["id"]
    tm = _manager(db)
    called = []
    tm.stop_tenant = lambda t: called.append(t) or _noop()
    await tm._on_polling_failure(tid, NetworkError("boom"))
    assert db.get_tenant(tid)["is_active"] == 1
    assert called == []


def test_supervise_polling_missing_task_is_safe(db):
    tm = _manager(db)
    # 无对应 app/updater 时静默跳过，不抛异常。
    tm._supervise_polling(999)


async def _noop():
    await asyncio.sleep(0)
