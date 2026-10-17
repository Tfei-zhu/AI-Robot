"""取消请求时等待正在操作文件/数据库的线程退出，再释放资源。"""
import asyncio
from anyio import CancelScope


async def finish_cleanup(awaitable):
    """Finish resource/persistence cleanup before propagating repeated cancellation.

    ASGI disconnect uses level cancellation; a native asyncio caller can also
    cancel repeatedly. Shield both forms without losing the cancellation signal.
    The operation itself owns its bounded resource-cleanup policy.
    """
    interrupted = False
    with CancelScope(shield=True):
        task = asyncio.ensure_future(awaitable)
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                interrupted = True
    if interrupted:
        raise asyncio.CancelledError
    return result


async def run_blocking(fn, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise
