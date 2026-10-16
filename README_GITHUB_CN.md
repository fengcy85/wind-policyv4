> **历史版本文档提示：本文件说明早期121/138来源的V6流程。当前完整139来源、31省、北极星及真实抓取验收步骤请以 [README_V7_31PROVINCES_CN.md](README_V7_31PROVINCES_CN.md) 为准。网站前端保持原版不变。**

# 风电政策法规与行业动态自动监测网站 · GitHub Pages 部署指南

> 本项目是从你现有的 GitHub 静态网站修改升级的完整项目包。继续使用 **GitHub Actions 自动采集 + GitHub Pages 发布**，不需要单独租用服务器。网站公开可见，采集不绕过登录、验证码、robots 或网站访问限制。

## 1. 网站现在能做什么

打开主页后，顶部有两个明显的页面按钮：

- **政策法规**：按发布日期展示风电法规文件，逐条显示法规名称、国家/地区、官方原文节选、法规维度标签、产品设计影响分析、来源机构和“查看原文”链接。可按“最新发布”和“设计关联优先”排序；支持搜索、时间、国内/国际、法规维度、效力标注筛选，支持 CSV 导出。
- **行业动态**：保留并使用原有新闻监测库与本周重点动态，支持搜索、标签、国家、来源、时间和战略价值排序，提供来源原文链接。

**来源配置原样保留：** `policy_sources.json` 中有国内 **100** 个、海外与国际 **21** 个法规来源，共 **121** 个；`regulatory_dimensions.json` 中有 **18** 个法规维度；`sources.json` 中有原来的 **16** 个行业资讯渠道。法规来源继续按仓库 `adapters/sites/` 中的独立站点规则抓取。

**重要：** 已配置来源数 ≠ 成功采集来源数。政府法规检索门户、PDF 扫描件、robots 限制、403/429、动态 JS 页面等可能需要后续适配，不能保证每个网站都能完整抓取。来源状态区会记录失败原因。

## 2. 用现有 GitHub 仓库部署（推荐）

1. **先备份原 GitHub 仓库。** 解压此文件包，找到内部的 `wind-monitor-main` 文件夹。
2. 在 GitHub Desktop 中克隆已有仓库 `fengcy85/wind-policy-monitor`，或者使用你的本地 git 仓库。**不要删除仓库历史。**
3. 将解压后的 `wind-monitor-main` **内部所有文件和文件夹**复制到现有仓库根目录，同名文件选择覆盖。不能额外多套一层 `wind-monitor-main`。注意复制隐藏目录 `.github`。
4. 用 GitHub Desktop 执行 **Commit to main → Push origin**，或者用 git 提交并推送。GitHub Actions 现配置为 `push main`、每日定时及手动运行，推送代码后会触发一次任务。
5. 到仓库的 `Settings → Pages → Build and deployment → Source`，选择 **GitHub Actions**。
6. 打开 GitHub 的 `Actions` 页面，查看 **Wind policy & industry monitor — collect and deploy**。也可点 **Run workflow** 手动运行。
7. 等待抓取/生成/发布步骤结束，然后访问网站：<https://fengcy85.github.io/wind-policy-monitor/> 。首次抓取 121 个站点可能较慢，请等待实际运行结果。

GitHub Actions 的定时表达式是 `13 0 * * *`（UTC），即**北京时间每天约 08:13**，具体启动时间可能因 GitHub 调度延迟。费用与使用限制以 GitHub 账户方案和官方政策为准。

## 3. AI 影响分析：可选，不配置也能正常运行

**零配置模式：** 如果没有 API 密钥，系统仍从用户配置的公开网站抓取资料，用规则初筛法规维度和产品设计影响；网页明确标注“规则辅助初筛”，不会冒充已经执行 AI 模型判断。

**启用 AI 辅助：** 在 GitHub 仓库 `Settings → Secrets and variables → Actions → New repository secret` 添加：

- Secret 名称：`OPENAI_API_KEY`
- Secret 值：你自行获得的 API 密钥（**仅放入 Secret，严禁写在 GitHub 源文件中**）。

工作流随后运行 `policy_ai_enrich.py`，只把已经抓到的**公开法规标题、原文节选、日期和来源网址**发给 API，辅助归类及生成“需要核实的产品设计影响”。默认模型 `gpt-4.1-mini`，每次最多分析 12 条新/变化记录，可在 `.github/workflows/update.yml` 中改 `OPENAI_MODEL`、`AI_MAX_ITEMS_PER_RUN`。API 调用可能产生费用；无密钥不调用模型。企业内部设计方案及机密参数不会自动上传，因为仓库不含相关数据，也不应放入公开仓库。

**法律准确性原则：** AI 只处理实际采集到的公开证据，**不能替代法律效力、发布时间、条款编号、企业适用性或强制合规判定**。源节选与官方链接始终保留，不让模型凭空改写。资料不足时显示待核实。

## 4. 数据怎么产生？

```
policy_sources.json （121 个原始来源网址）
    ↓ policy_scrape.py（公开 HTML / PDF / 可允许的浏览器回退；独立检查点）
site/data/policies.json + policy_source_status.json（抓取原始记录与逐站状态）
    ↓ policy_ai_enrich.py（可选模型；无密钥时自动降级）
    ↓ build_site_data.py（统一新旧版本字段、校验发布日期、去重、排除无证据记录）
site/data/policies_display.json + policies.csv（法规网页与导出使用）

sources.json （16 个行业渠道）
    ↓ scrape.py → strategic_filter.py → weekly_focus.py
site/data/news.json + weekly_focus.json（行业网页使用）
    ↓ GitHub Pages 部署 site/ 目录
```

系统中有一份 `legacy_policy_source_aliases.json`：把历史程序使用的来源 ID 与目前的独立站点 ID 对齐。能确认一一对应的**120 个历史状态**被保留，**1 个已更换机构的网址不强行映射**，将由新爬虫重新检查。避免出现历史状态不匹配而“全部来源未轮询”的假象。历史状态会明确标注“上一版检测”，不伪装成这一轮新采集。

**原有数据不会被新构建脚本清空：** `policies.json` 保留原始记录；`policies_display.json` 是展示投影；对于无法确认发布日期、未来日期、无法证明风电关联或原文节选不足的候选，不展示为带日期的法规，避免用户误判。存量旧记录不代表已经重新在线验证。

## 5. 常用自检命令

需要 Python 3.11 和 Node.js；先执行 `pip install -r requirements.txt`，然后运行：

```bash
python -m unittest discover -s tests -p 'test_policy_v6*.py' -v
node tests/test_frontend_policy_v6.cjs
node tests/test_frontend_news.cjs
python build_site_data.py
python -m http.server 8000 --directory site
```

在浏览器打开 <http://localhost:8000/index.html> 和 <http://localhost:8000/news.html>。不要直接双击 HTML 使用 `file://`，那会导致 JSON 文件的浏览器读取受阻。

若要手动执行真实采集，先确保当地网络允许并遵守目标网站规则：

```bash
python policy_scrape.py --prepare
python policy_scrape.py --mode auto
python scrape.py
python strategic_filter.py
python weekly_focus.py
python policy_ai_enrich.py
python build_site_data.py
```

抓取只在运行脚本/Actions 时发生。打开网页或点击网页按钮**不会触发服务器即时搜索**；静态网页显示最近一次 GitHub Actions 保存的监测结果。

## 6. 本次修复的问题

1. **原始日志报错**：`TypeError: select.replaceChildren is not a function`，发生在旧版前端模拟测试。已让页面和测试 DOM API 一致，修复并增加实际内容验收。
2. 原法规记录同时存在 V5 与 V6.1 字段（如 `evidence/source_excerpt`、`product_impact/impact_design`），网页曾因字段不匹配漏展示。现统一进入 `policies_display.json`。
3. 旧行业页 HTML 和旧脚本引用了两套不同的 DOM ID，造成行业页面无法正确加载。已统一重写展示逻辑。
4. 来源登记使用了两套 ID 及“国内/中国”两套地区值。现为网页统一地区、迁移可证明匹配的历史状态；新的爬虫继续使用现有独立适配器 ID。
5. 两个页面的顶部双入口、排序按钮、明确可见的法规节选与设计影响已整合，防止关键信息被藏在详情页内。

项目也保留了之前的诊断说明及 `tests/legacy/` 中针对废弃接口的历史测试，避免误将陈旧测试视为当前爬虫验收失败。
