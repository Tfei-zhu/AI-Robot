"""取消请求时等待正在操作文件/数据库的线程退出，再释放资源。"""
import asyncio


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
