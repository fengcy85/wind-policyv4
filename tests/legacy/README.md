# 历史测试（不参与当前 CI）

这两份历史测试针对已被 V6.1 替换的旧版 `policy_scrape.py` 接口，测试引用的 `create_policy`、`get_page`、`DIMENSIONS` 等入口已不存在，因此不能作为当前流水线验收条件。为保留用户原始项目的研发痕迹，原样归档至此，不通过伪造兼容函数让旧测试假通过。

当前实际运行的爬虫使用 `tests/test_policy_v6.py`、`tests/test_policy_v61.py`、`tests/test_policy_v62_display.py` 及对应的 JavaScript 前端测试。执行：

```bash
python -m unittest discover -s tests -p 'test_policy_v6*.py' -v
node tests/test_frontend_policy_v6.cjs
node tests/test_frontend_news.cjs
```
