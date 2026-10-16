# WIND POLICY WATCH | 风电政策法规与行业动态监测（V7）

**本仓库包含完整的网站、后台爬虫、GitHub Actions 工作流、数据和测试，并非单独补丁。原始网页 HTML / CSS / JS 均未修改。**

> **[📘 最新完整部署和验收说明：README_V7_31PROVINCES_CN.md](README_V7_31PROVINCES_CN.md)**

## 监测范围

- **139 个配置来源**：中国 118 个（省级官方机关、中央部门、专业媒体等），海外/国际 21 个。
- **31 个省级行政区**：每省至少配置两条官方发布渠道；优先省级能源主管部门、发改委和省政府公文栏目。
- **北极星风力发电网的政策目录**：`https://fd.bjx.com.cn/zc/`，作为风电政策发现和补漏渠道；媒体内容不能冒充具有法律效力的官方法规。
- **行业新闻页面和 18 个政策影响维度**：沿用原先的网站功能和原始前端代码。

## 运行方法

1. `pip install -r requirements.txt`
2. `python -m unittest discover -s tests -p 'test_policy_*.py' -v`
3. `python policy_scrape.py --prepare`
4. `python policy_site_probe.py --province-first --output diagnostics/site_probe_github.json` （当前网络允许时探测首个目录）
5. `python policy_scrape.py --mode auto --scope provincial`（省级 + 中央 + 北极星）；定期 `--scope all`（另含海外来源）
6. `python build_site_data.py`；GitHub Actions 还会自动刷新原有新闻数据、输出报告并发布 GitHub Pages。

**可选的风电政策 AI 分析**：未设置 `OPENAI_API_KEY` 仍可运行规则辅助的初筛；AI 不替代法律效力核验。

## 验收原则

程序测试通过 ≠ 139 个站点全部抓取成功。首次发布前会将旧版站点失败状态归档，V7 起始状态均是“未完成真实抓取”。请通过 Actions 工件 `wind-policy-backend-diagnostics` 检查真实 HTTP、DOM、日期、分页及详情失败原因，必要时使用有权运行的中国境内节点对照测试访问限制。
