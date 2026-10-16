> **历史版本文档提示：本文件说明早期121/138来源的V6流程。当前完整139来源、31省、北极星及真实抓取验收步骤请以 [README_V7_31PROVINCES_CN.md](README_V7_31PROVINCES_CN.md) 为准。网站前端保持原版不变。**

# 风电政策监测项目｜只改数据源和抓取层（V6.2）

## 交付边界

本补丁以用户提供的 `wind-policy-monitor-v2-main (2).zip` 为基础，**没有编辑** `site/index.html`、`site/news.html`、`site/static/` 的任何页面、样式和交互脚本；旧站页面布局、筛选、排序、图表、栏目和下载功能原样保留。原有历史法规数据和新闻数据也不清空。

改动主要集中于 `policy_scrape.py`、`policy_transport.py`、`policy_public_ui.py`、`policy_network_probe.py`、`policy_quality_summary.py`、`policy_sources.json`、`adapters/sites/` 的少数网站配置、GitHub Actions 工作流，以及对应的离线回归测试。

**说明：** 离线测试通过仅能证明代码在模拟场景下的行为。平台中 138 个来源的 CSS 列表、发布日期和分页仍须在 GitHub Actions 或具备合法访问能力的真实执行环境中分别验证。本次运行环境的直接对外 DNS 解析失败，不能冒称 138 站线上抓取成功。

## 本次真实修复点

| 部分 | 修改方式 | 对外承诺边界 |
| --- | --- | --- |
| 403/404/412 | 首次 HTTP 状态码独立留痕；403/412 不用浏览器模拟绕过；404 只尝试人工配置的官方备用入口 | 不能消除服务端本身的访问限制 |
| 连接/TLS/DNS/超时 | 显式区分失败种类；超时及 5xx 有限重试；证书校验保持开启 | 需在不同网络出口测量 |
| 同域并发 | `DomainThrottle` 默认每个 hostname 最多 1 个并发、请求启动间隔不短于 0.6 秒 | 浏览器渲染也占用同一域名配额 |
| 下一页 | 实际解析 `next_selectors`、分页 href、JS 下一页；公共浏览器可尝试真实点击 | 无法完整浏览的页面保持待核验 |
| 日期 | 先核对**全部目录条目**的发布日期和降序，再筛选与风电有关的候选；不再将文章标题内日期当发布日期 | 年份、栏目提示不能替代实际发布日期 |
| 覆盖游标 | 要求匹配列表选择器、日期齐全、日期顺序、实际时间边界及分页证据；旧版游标没有 V6.2 证明则重新验证 | 不因看到首页或任意旧文章就视为覆盖成功 |
| 详情下载 | 目录已验证后，详情失败或超出下载预算的 URL 存入 `site/data/policy_detail_retry_queue.json`，下轮优先补查 | 目录覆盖与全文成功分开呈现 |
| 多入口 | 官方备用入口各自独立统计日期与分页，不跨栏目拼凑虚假覆盖证明 | 不随意猜测未公开的检索接口 |
| GitHub | 在工作流中记录抽样的服务器网络探测与质量报告；前端照旧部署 | GitHub 不等于境内访问结果 |

### URL 已明确更换的 6 处

逐站比对原项目、运行状态和公开官方入口后，只替换了可确认存在明显入口层级问题的配置。其余 132 项没有凭空编造新的栏目地址。详见 `diagnostics/verified_entry_changes.json`：

1. **沙特**：由采购登录门户改为沙特电力监管机构 SERA 的法律法规栏目。
2. **全国标准信息公共服务平台**：由门户首页改为国家标准目录；同时把公开“风力发电机组”搜索设置为优先入口。
3. **云南省人民政府**：旧 `zxwj/` 报 404，修正为 `zxwj/index.html`，并配置已检索到日期表格的 `yzf/` 官方栏目作为备用。
4. **云南省工信厅**：旧政策栏目报 404，改用公开的政策文件栏目及其官方备用栏目。
5. **乌兹别克斯坦 Lex.uz**：由数据库主页改为公开 `en/search/all?lang=3` 检索列表。
6. **欧盟 EUR-Lex**：由介绍主页改为官方高级检索表单（完整查询与翻页仍须浏览器端实测）。

对 **江苏省发改委**，保留原本官方政策检索入口，另外配置两个官方法规栏目作为备用；原入口虽然路径含 `zcjd`，不能仅据路径字符串判定其为“政策解读”栏目。对 IEA、KEGOC 和欧盟委员会风电专题页，明确标为**政策线索**而非法律原文库；印度 NIWE 归为**法规标准**类；这些都是后端数据源分类，不涉及修改前端显示逻辑。

`diagnostics/source_audit_138.csv` / `.json` 是对原有 138 个来源的**逐站配置与日志核查记录**，包含旧新 URL、上一轮状态、首个 HTTP 异常与需进一步验证的事项。该审计表不等于已完成 138 个站点的现场访问验证。对于网络失败、403 或地址尚未核实的网站，不擅自更换网址。

## 使用和部署

建议先备份原仓库（包括 `site/data/` 的历史数据）。解压本交付压缩包，将压缩包内的 **`wind-policy-monitor-v2-main` 目录下所有内容**合并到 GitHub 仓库根目录；保留相同路径，提交到 `main`。不需要重新制作页面或重新建立 GitHub Pages。

GitHub Actions 会根据原有 `update.yml` 的触发条件自动运行，也可在 Actions 页中选择 `Wind policy & industry monitor — collect and deploy` 手动执行。第一次运行会撤销**未附新证明的旧版“初始化成功”游标**并重新核验，但保留既有法规记录；这可能使状态由旧版“成功”变为“目录待核验”，属于避免误报的设计，而非网站故障。

执行完成后，查看该次 Workflow 的 `Summary` 及 `wind-policy-backend-diagnostics` 工件，重点读取：

- `diagnostics/last_run_quality.md`：按站列出真实目录覆盖、详情积压和异常。
- `diagnostics/network_github_actions.json`：**只代表该次 GitHub Actions 出口**的样本探测，不能称之为境内结果。
- `site/data/policy_source_status.json`：每站抓取状态、页面数、日期行数、详情异常与访问尝试轨迹。
- `site/data/policy_source_checkpoints.json`：按站记载经新逻辑核验的目录游标。
- `site/data/policy_detail_retry_queue.json`：下载失败的详情补查任务。此文件经自动提交保存在仓库数据目录下。

### 在境内外各测一次（互不替代）

从 GitHub Actions 已自动生成 `diagnostics/network_github_actions.json`。如有**合法获准的境内执行机器**，安装项目依赖后，在该机器上运行：

```bash
python policy_network_probe.py --region authorized-cn-runner --all --timeout 8 --workers 3 --output diagnostics/network_cn.json
```

把 GitHub 下载的 `diagnostics/network_github_actions.json` 与境内产生的 `diagnostics/network_cn.json` 放在同一台机器的同一项目目录下，再运行：

```bash
python policy_network_probe.py --compare diagnostics/network_github_actions.json diagnostics/network_cn.json --output diagnostics/network_comparison.json
```

比对报告按相同主机判断“GitHub 可用 / 境内可用 / 两侧均失败 / 仅一侧测量”，但**地域标签只来自操作者，脚本不冒充独立 IP 地理鉴定**。如要严谨证明境内出口，可结合运行机器所在地域与 ISP/网络出口运维记录。测试只执行少量正常公开 GET 请求，不处理网站验证码、账号登录或限制绕过。

如果境内网络正常而 GitHub 长期失败，可以将**爬取作业**部署在获准环境，把生成的 `site/data/` 同步回现有 GitHub 仓库；**不要改 GitHub Pages 前端**。这一步需要实际运行环境与授权，项目不能替使用方直接开通境内服务。

## 回归测试

```bash
python -m unittest discover -s tests -p 'test_policy_v6*.py' -v
python -m unittest discover -s tests -p 'test_policy_transport_v62.py' -v
node tests/test_frontend_policy_v6.cjs
node tests/test_frontend_news.cjs
```

重点边界已覆盖：403、404、412、429、5xx、TLS/DNS/超时；拒绝后不模拟绕过；同域并发=1；真实 next CSS；第二页丢失；动态 JS 翻页；跨站备用入口证据隔离；标题日期不冒充发布日期；列表任意条目缺日期；未来发布日期；详情重试队列；旧游标无新证明时失效；两地域探测报告缺测标记。

## 尚未解决、不能伪造解决的情况

- 有些官方库仅显示 JavaScript 表格、动态查询和登录页面，需要下一次 GitHub 运行取得真实网页快照/结构之后，进一步添加专站选择器；未开放公开列表的源无法证明月度全覆盖。
- 403/412 可能由官方访问条件限制产生，程序会**停止模拟绕过**并如实保留状态；更改请求头或无界重试不是合规修复办法。
- 此环境无法访问真实 GitHub Actions、不能代替部署，无法拿到实际境内出口，因此本次没有“所有站点都已成功”的线上结论。
- 网站端展示已有的旧状态数据将在**下一次实际抓取和数据构建完成后**更新；本补丁没有篡改现有展示数据，避免将模拟结果伪装成网站的新法规。
