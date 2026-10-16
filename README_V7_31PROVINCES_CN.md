# V7｜风电法规政策监测——按省份重构，网站前端保持原样

> **先看事实**：此包是完整 GitHub 项目，不是增量补丁。139 个来源、118 个国内来源（含省级和中央部门、媒体），21 个海外/国际来源；31 个省级行政区均配置官方渠道。**这不等于139个来源全部真实抓取成功，也不等于任何省份全部法规已获完整覆盖。** 本环境实际外网访问存在 DNS 失败，所有逐站 CSS、API、翻页、境内外网络通畅情况必须以你部署后的 GitHub Actions 与合规执行端的真实结果为准。

## 这次实际改了哪些

- 彻底保持 `site/index.html`、`site/news.html`、`site/static/` 下原有六个网页、JS、CSS 文件字节级不变，原网站页面、新闻栏目、筛选、排序等功能保留。只编辑后台爬虫、来源表、专站适配器、自动工作流、后端产出 JSON、诊断工具和测试。
- 按31个省级行政区建立**主监测机关+官方备用来源+北极星媒体补漏**的监测契约，优先运行能源主管部门、发改委和北极星政策目录。各省并非只监测一个网站。配置级名单见 `diagnostics/province_source_contracts.json`；每站处置计划见 `diagnostics/provincial_source_recovery.csv`。
- 北极星真实目录为 `https://fd.bjx.com.cn/zc/`，**正文域名是 `news.bjx.com.cn`**；解析目录中与标题相邻的发布日期、真实“下一页”链接、新闻全文和显示的政府官网原文链接。媒体条目保留“待官方原文核验”提示；媒体片段绝不冒充官方法规条文。
- 来源修正：江苏省发展改革委改为官方法规页面并保留检索页，江苏省政府改为可见日期条目的省政府文件目录；天津政府改为可访问的官方市政府文件目录；上海发改委优先监测直接能源政策列表；内蒙古能源局优先实际政策举措栏目；吉林工信厅改为其自己的网站政策文件栏目；新增吉林能源局官方通知公告和政策法规。上一V6.2已改的云南、国际法规数据库等保留。具体旧新 URL 和公开证据：`diagnostics/reconstructed_entry_changes.json` 及 `diagnostics/verified_entry_changes.json`。
- 增加重复列表行+独立日期自动识别，兼容 `li`、表格、嵌套 `div/h3 + 文号/发布日期`；对站点自己的 next selector 和正常公开 JS 翻页分开处理；无法证明排序和窗口覆盖时**不推进游标**。
- 允许广义影响风电的“新能源/机制电价/绿电/电力市场”政策在确认正文含风电内容时收录；补充“风、光”“海风”等常见标题写法；不能仅靠标题出现年份就认定发布日期。
- HTTP 403、404、412、429、超时、DNS、TLS 和 5xx 分类，官方备用目录择一采集、同域并发与间隔，保持 HTTPS 证书校验，不突破访问限制；目录已经核验但详情失败则入独立持久重试队列。
- 每日优先省级政策来源；周日和手动选择 `all` 时仍可执行所有国际来源，**不删除之前的国际法规和新闻栏目**。

## 上传至新的 wind-policy-monitor-v3 仓库

1. 先备份现在 GitHub 仓库的 `site/data/`，包含已有法规、新闻和核验检查点。数据属于已有成果，不建议覆盖丢失。
2. 解压此包，**只把 `wind-policy-monitor-v7/` 这个文件夹内部的全部文件和隐藏文件夹（尤其 `.github/`）**复制到 GitHub Desktop 已 Clone 的 `wind-policy-monitor-v3` 本地仓库根目录。不要再多套一层文件夹，不要动 Git 自己的 `.git` 文件夹。
3. 在 GitHub Desktop 中 Commit to main 并 Push origin；到 GitHub → Settings → Pages → Source 选择 **GitHub Actions**，仓库 Actions 允许部署所需权限。
4. 进入 Actions → `Wind policy & industry monitor — collect and deploy` → Run workflow。选择 `provincial`（建议第一次先跑国内），如希望测试全部来源选 `all`。自动计划默认每日北京时间约08:13执行省级采集，周日另外执行一次含海外全部来源（GitHub定时作业可能延迟）。
5. 运行完成后查看 Actions 运行 Summary、附件 `wind-policy-backend-diagnostics`。其中本轮成功与失败不能依赖旧站快照。重点查看：
   - `diagnostics/last_run_quality.md`——本轮是否真的生成新结果，目录、正文、网络故障数；
   - `diagnostics/provincial_source_recovery.csv`——每个国内网站的优先级、入口、备用、失败原因对应处置；
   - `diagnostics/province_coverage.csv`——按31省划分的**已核验某栏目**、官方发现、仅媒体线索、未覆盖；
   - `diagnostics/network_github_actions.json`——同一个GitHub运行器抽检31省官方主入口及北极星（仅证明该运行环境的状态）；
   - `site/data/policy_source_status.json`——逐站 HTTP/DOM/日期/分页及正文失败证据；
   - `site/data/policy_detail_retry_queue.json`——下轮优先补抓的详情 URL。

## 首次交付状态与真实逐站验收（非常重要）

本交付包将旧版抓取产生的失败快照转移到 `diagnostics/pre_v7_status_archive.json`，将旧版游标备份到 `diagnostics/pre_v7_checkpoint_archive.json`；网站发布目录中的 `policy_source_status.json` 初始为139项**未测试**，而不是138条旧版失败。历史法规记录 `site/data/policies.json` 与原新闻数据保留，不会因清理旧状态而删除。只有你在新版GitHub Actions运行后才产生本版实测的成功/失败结果。

工作流每次执行一个轻量级**31省主来源 + 北极星**真实HTML目录探针：

```bash
python policy_site_probe.py --province-first --workers 3 --output diagnostics/site_probe_github.json
```

输出包含每个入口的HTTP故障、日期目录行数、疑似分页、实际样本DOM，但**探针只查第一页，不代表全部时间区间完成**。所有139个来源的完整分页和详情则由 `policy_scrape.py` 按手动 `all` 或日常 `provincial` 范围执行。若仅想单独定位贵州：

```bash
python policy_site_probe.py --province 贵州 --output diagnostics/site_probe_guizhou.json
```

请勿在已有生产数据的仓库手动运行 `policy_release_bootstrap.py --apply-new-install`；这条指令**仅限制作新安装包**，会清除实时游标并归档旧状态。迁移到V3前先备份最新 `site/data/`。

**真实验收等级**：公共网页确认正确栏目 ≠ GitHub运行端HTML可读 ≠ 完整发布日期和翻页核验 ≠ 省级发布机关全部覆盖。未完成的等级必须明示。

## 403/404/412/连接异常的专门处理

| 故障 | 程序处理 | 必须人工/网络环境核实之处 |
|---|---|---|
| 404 | 记录原始404，并逐一尝试已经核对的官方备用栏目 | 核对网站改版后的真实目录，禁止猜URL |
| 403 | 停止对同一拒绝URL的模拟浏览器升级；保存状态 | 检查官网公开访问规则和获准境内出口；可用官方其他栏目或者北极星找政策线索 |
| 412 | 不通过伪造认证/绕开安全检查强行重试 | 核对网站合法公开访问流程，必要时改用省政府公报 |
| 429 | 控制并发，有限重试、尊重 Retry-After | 必要时联系网站，降低频率 |
| 超时/DNS/TLS | 有限网络重试、诊断区分、记录跳转和错误 | 在GitHub与有权使用的境内机器分别测试；不关闭TLS证书验证 |
| HTTP200但候选/日期/翻页不全 | 特殊行和日期解析 + 浏览器公开目录交互尝试；覆盖不完整仍显示待核验 | 用真实页面DOM/网络请求逐站补适配；**不能称为站点完全成功** |

## 境内外网络对照（不是自动取得国内服务器）

GitHub运行器会跑一次31省抽样：

```bash
python policy_network_probe.py --region github-actions --provinces-first --limit 32 --timeout 7 --output diagnostics/network_github_actions.json
```

在有访问授权的国内机器**单独**运行：

```bash
python policy_network_probe.py --region authorized-cn-runner --provinces-first --limit 32 --timeout 7 --output diagnostics/network_cn.json
python policy_network_probe.py --compare diagnostics/network_github_actions.json diagnostics/network_cn.json --output diagnostics/network_comparison.json
```

只有两端相同主机测过后，才能判断地域/出口可达性差异。若GitHub连不上、获准境内服务器可稳定访问，可把**抓取任务**迁至该服务器，再将 `site/data/` 同步到GitHub继续发布；整个前端无需修改。

## 测试结论与未完成的事实

- 后端78项模拟/单元/边界测试通过；前端政策与新闻两套原有Node测试通过；原6个前端文件逐字节一致。
- 这些是**代码正确性检查，不是139个实站都已完成抓取的证明**。
- 已通过公开网页核对北极星（实际第二页 `/zc/2/`）、上海能源政策、江苏法规目录及省政府文件、天津市政府文件、内蒙古能源、吉林能源局、吉林工信厅、贵州省能源局（含2026年风电项目建设通知）、北京发改委、福建发改委、辽宁发改委等目录存在或有日期条目。没有将其真实CSS选择器声称已经在GitHub运行器逐一测试。
- 当前容器外网DNS不可用，不能代替你新建V3仓库的GitHub Actions开展真实HTTP/DOM验收，也不能谎称合法国内服务器已开通。需要实际运行的 `wind-policy-backend-diagnostics` 才能锁定剩余站点并继续修。
- 数据最初按政策源首次加入时间向前回溯30天；日期先于回溯起点的历史政策不会自动算作30天新增。对需要历史补抓的来源可以在允许的网络环境中安排一次专项回填。

**原则：** 不增加虚构成功数；媒体报道只记待核验线索；任一省的一个部门完成日期扫描不代表该省所有发文部门都已覆盖。
