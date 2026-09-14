"""跨用例隔离 P2-M2 L2 接线：lifespan 布线的真实 facade 绝不渗漏到其他测试（离线纪律）。"""

import pytest
from backend import data_source


@pytest.fixture(autouse=True)
def _isolate_l2_facade():
    data_source.set_facade(None)
    yield
    data_source.set_facade(None)
