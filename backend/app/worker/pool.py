"""
进程池单例：承载文章生成的后台任务。

使用 ProcessPoolExecutor（而非线程池），因为 CrewAI 多 Agent 编排吃模型 IO/CPU，
进程隔离可避免 GIL 与客户端状态互相干扰，且子进程崩溃不影响主进程。

Windows 下多进程需保证 worker 函数在独立模块中可被 pickle，故 _worker 放在 tasks.py。
"""
import multiprocessing as mp
import signal
from concurrent.futures import ProcessPoolExecutor

# demo 阶段进程数设小；CrewAI 主要吃模型 IO，过大无意义
MAX_WORKERS = 2

_executor: ProcessPoolExecutor | None = None


def _ignore_sigint():
    """子进程初始化时忽略 SIGINT。

    crewai.telemetry 在 import 时会给 SIGINT 注册自定义 handler，导致主进程 Ctrl+C 时
    子进程也被唤醒并打印一段无意义的 KeyboardInterrupt traceback。这里在子进程里把
    SIGINT 重置为「忽略」，使只有主进程响应 Ctrl+C，子进程乖乖被 terminate 收掉。
    """
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass


def get_executor() -> ProcessPoolExecutor:
    """懒初始化进程池单例（应用生命周期内复用）。"""
    global _executor
    if _executor is None:
        # 使用独立的 spawn 上下文，并为每个 worker 注册 SIGINT 忽略，避免退出时噪音
        ctx = mp.get_context("spawn")
        _executor = ProcessPoolExecutor(
            max_workers=MAX_WORKERS,
            mp_context=ctx,
            initializer=_ignore_sigint,
        )
    return _executor


def shutdown_executor():
    """应用关闭时回收进程池。

    显式终止子进程：确保主进程退出时仍在跑 CrewAI 的子进程被强制收掉，不打印 traceback。
    先 cancel 未开始的任务，再强行 terminate 已 spawn 的子进程，最后 shutdown。
    """
    global _executor
    if _executor is None:
        return
    # 先收集当前存活的子进程（shutdown 之后内部 _processes 可能被清空，须在之前取）
    procs = list(getattr(_executor, "_processes", {}).values())
    try:
        # 不再派发新任务
        _executor.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        # 旧版本 ProcessPoolExecutor 不支持 cancel_futures
        _executor.shutdown(wait=False)
    # 强行终止仍在运行的子进程，避免退出时的信号噪音
    for proc in procs:
        try:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=3)
        except Exception:
            pass
    _executor = None
