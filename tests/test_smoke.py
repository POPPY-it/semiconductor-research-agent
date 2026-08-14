"""冒烟测试：验证核心依赖与包结构可导入。"""

import importlib


def test_smolagents_importable():
    mod = importlib.import_module("smolagents")
    assert mod.__version__


def test_project_packages_importable():
    importlib.import_module("data")
    importlib.import_module("data.collectors")
    importlib.import_module("agent")


def test_collector_modules_importable():
    importlib.import_module("data.collectors.sec_edgar")
    importlib.import_module("data.collectors.news_rss")
