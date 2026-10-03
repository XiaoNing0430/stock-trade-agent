"""跨用例隔离 P2-M2 L2 接线：lifespan 布线的真实 facade 绝不渗漏到其他测试（离线纪律）。"""

import os

import pytest
from backend import data_source


def _ensure_readable_pytest_temproot() -> None:
    """pytest 临时根自愈：提权运行遗留的 pytest-of-<user> 目录可能 DACL 全拒（WinError 5），
    tmp_path 工厂 scandir 即炸。检测到不可读时改指仓库内 .pytest_tmp/；健康环境零行为变化。"""
    import getpass
    import tempfile
    from pathlib import Path

    if os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return
    rootdir = Path(tempfile.gettempdir()) / f"pytest-of-{getpass.getuser()}"
    try:
        os.scandir(rootdir)
    except FileNotFoundError:
        return
    except PermissionError:
        fallback = Path(__file__).resolve().parent / ".pytest_tmp"
        fallback.mkdir(parents=True, exist_ok=True)
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(fallback)


_ensure_readable_pytest_temproot()


@pytest.fixture(autouse=True)
def _isolate_l2_facade():
    data_source.set_facade(None)
    yield
    data_source.set_facade(None)
