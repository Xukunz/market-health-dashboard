# MARKETPULSE · 市场脉搏

每日更新的市场健康度 / 半导体压力 / 自选股行情 / 宏观 / 新闻 / 私人本地持仓仪表盘。

**重要：本项目采用每日收盘后更新的日线数据，而不是实时逐笔价格。** 网页会展示实际数据日期和生成时间，不使用用户过去的截图、假设价格或硬编码的健康度评分。

## 功能

- **市场健康度（0–100）**：SPY趋势、行业ETF与自选股样本广度、VIX、10年期美债/Brent、美国高收益债利差；展示每项具体得分和数据覆盖率。
- **半导体压力评分（0–100）**：SOXX趋势、SOXX相对SPY强弱、15只相关股票的广度及20日高点回撤。它是**样本评分**，不能视作半导体行业官方指数。
- **主要市场**：SPY、QQQ、SOXX、RSP、IWM、HYG、TLT，日变动及25交易日走势。
- **38只自选股**：筛选、排序、搜索，日/5日涨跌幅、量比、25日走势。按原始市场源记录交易日期。港股以HKD计价。
- **宏观数据**：FRED的DGS10、DGS30、VIXCLS、DCOILBRENTEU、BAMLH0A0HYM2。不同数据发布日可能不同。FRED 屏蔽部分数据中心/CI 出口 IP（GitHub Actions 上表现为读超时），此时自动回退到 Yahoo Finance 的同类标的（^TNX、^TYX、^VIX、BZ=F），页面如实标注实际来源；高收益债利差没有同类标的，仍留空。
- **异动**：当日涨跌超过5%、5交易日超过10%、量比达到2倍自动标记。量比对比前20个完整交易日，不能严格证明异常成交量。
- **新闻**：Google News RSS抓取原始标题、发布时间和跳转链接，仅以关键词标记潜在重大新闻，**不等同于真实性核验或事实确认**。
- **本机持仓**：可手动填写股数与成本，保存在浏览器 `localStorage`，不会写入 `data.json` 或公开GitHub仓库。
- **历史健康度**：每日累计记录最多120个更新日（周末也可能有重复值）。

## 直接预览

```bash
cd site
python -m http.server 8080
# 浏览器访问 http://localhost:8080
```

首次下载的 `site/data.json` 刻意是 **pending（无行情）**；只有成功执行抓取脚本才会出现真实数据。这是为了防止将演示假数据当作当前行情。

## 每日自动更新（推荐：免费 GitHub Pages）

1. 在 GitHub 创建一个**新的公开仓库**，将本项目**全部文件**上传到仓库根目录，包括隐藏的 `.github/workflows/daily-update.yml`。
2. 仓库 `Settings → Pages → Build and deployment → Source` 选择 **GitHub Actions**。
3. 仓库 `Settings → Actions → General → Workflow permissions` 将权限设为 **Read and write permissions**（用于保存评分历史）。
4. 到仓库 `Actions → Daily market refresh → Run workflow` **手动执行一次**，观察脚本运行日志。
5. 首次成功完成后，GitHub Pages 会给出 `https://<你的用户名>.github.io/<仓库名>/` 地址。之后每天 **23:15 UTC** 自动获取新数据并发布（夏令时为美东19:15，冬令时为美东18:15）。GitHub定时任务可能延迟，不保证严格整点运行。
6. 任务完成后，网页会自动从本项目 `data.json` 读取当天的快照；打开网页或点击右上刷新图标可读取新的静态文件。

**GitHub Pages本身不会在访问网页时抓行情。** 定时更新由GitHub Actions工作流承担，页面只读取已发布的JSON。若在交易日收盘前手动运行，采集脚本会排除尚未收完的日K线。除GitHub公开仓库和GitHub Actions配额规则外，不需要购买服务器。

## 本地手动抓取

```bash
python -m pip install -r requirements.txt
python scripts/update_data.py
cd site && python -m http.server 8080
```

脚本需要联网；运行环境无法访问外部行情网站时会失败，并且不会编造数据。Yahoo Finance/Stooq/Google News非正式或公共访问可能限流；失败或行情交易日超过7个自然日的股票直接缺失，其他来源继续尝试。若覆盖过低，更新任务会失败并保留上次已发布文件。**请遵守数据提供商条款；此项目不构成付费数据的转售许可。**

## 评分算法（透明、固定规则）

### 市场健康度（100分）

| 项目 | 满分 | 规则 |
|---|---:|---|
| 市场趋势 | 25 | SPY高于20/50/200日均线各加8/8/9分 |
| 上涨广度 | 20 | 11个美股行业ETF站上50日线比例×12分 + 自选美股样本比例×8分（至少7个ETF与15只美股） |
| 波动 | 20 | VIX ≤14: 20分；≤18:16；≤22:12；≤28:8；≤35:4；更高:0 |
| 宏观 | 20 | 10Y国债收益率（0–10分） + Brent最近5个观测日涨跌（0–10分），见代码阈值 |
| 信用 | 15 | 高收益债OAS ≤3%:15；≤4%:12；≤5%:8；≤6.5%:4；更高:0 |

仅获取部分分项时按 `已得分÷已覆盖满分×100` 计算，并公开覆盖率；覆盖低于60%不显示总分。分数是**自定义规则模型，不是官方市场指标**，也不能提供统计验证的收益预测。尤其样本广度不能取代NYSE/Nasdaq真实涨跌家数。

### 半导体健康度（100分）

- 40分：SOXX高于20/50/200日均线（12+13+15）。
- 20分：SOXX最近5交易日相对SPY的超额涨跌。
- 25分：已覆盖半导体样本中高于50日均线的比例。
- 15分：SOXX距离近20交易日高点的回撤幅度。

## 数据源与局限

| 数据 | 来源 | 备注 |
|---|---|---|
| 股票及ETF日线 | Yahoo Finance公开图表接口；失败时尝试Stooq | **非官方/非保证服务**；可能限流，非逐笔实时；复权方式可能不同 |
| 美债、油价、VIX、信用利差 | Federal Reserve FRED 公开CSV；不可用时回退 Yahoo Finance 同类标的（^TNX/^TYX/^VIX/BZ=F） | FRED观测时间不一致，可能滞后1–2个工作日或更久；回退标的是指数/期货，与FRED原序列不完全等同 |
| 新闻 | Google News RSS | 不等于 Reuters 等原始报道已经核实；标题可能被改写或重复 |
| 评分历史 | 仓库内 `site/history.json` | 记录工作流生成日，不一定对应交易日 |
| 个人持仓 | 当前浏览器 `localStorage` | 浏览器清空数据、无痕模式或换设备会丢失；不自动同步IBKR |

**交易决策前应去IBKR或交易所核实最新盘口、交易状态与关键新闻。** 本网站不提供投资建议、自动下单或实盘交易指令。

## 文件结构

```text
.github/workflows/daily-update.yml   每日获取并部署
scripts/update_data.py               数据采集、评分与历史
site/index.html                       页面结构
site/styles.css                       响应式视觉设计
site/app.js                           图表、表格、筛选与本机持仓
site/data.json                        每日快照，初始无数据
site/history.json                     评分历史，初始为空
requirements.txt                      Python依赖
```
