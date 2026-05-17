# MT5 量化交易系统

这是一个基于 `Python + MetaTrader 5` 的量化交易系统骨架，当前已经围绕 `XAUUSD / M1` 做了专门增强，适合先跑模拟盘，再逐步推进到半自动或全自动实盘。

## 一、系统能力

- 连接 MT5 终端并获取账户、持仓、历史 K 线
- 支持策略信号、风控、仓位计算、下单执行
- 支持 `XAUUSD / M1` 趋势突破动量策略
- 支持固定百分比止盈止损
- 支持移动止损
- 支持交易时段过滤
- 支持日内最大亏损熔断
- 支持连续亏损熔断
- 支持“日内只做一个方向”开关
- 支持手工新闻黑窗
- 支持 MT5 自带经济日历自动生成新闻黑窗
- 支持外部财经日历作为备用来源
- 支持本地回测与报表导出

## 二、当前默认交易逻辑

默认策略为 `xau_m1_momentum`，主要逻辑如下：

### 1. 入场

- 快速 EMA 在慢速 EMA 上方，视为多头趋势
- 收盘价向上突破最近一段时间高点
- RSI 高于多头阈值
- 满足以上条件后开多

- 快速 EMA 在慢速 EMA 下方，视为空头趋势
- 收盘价向下跌破最近一段时间低点
- RSI 低于空头阈值
- 满足以上条件后开空

### 2. 出场

- 固定止盈：`+0.3%`
- 固定止损：`-0.4%`
- 动量衰减或趋势反转时提前平仓
- 浮盈达到阈值后启动移动止损

## 三、项目结构

```text
src/mt5_quant/
  backtest.py          # 回测引擎
  cli.py               # 命令行入口
  config.py            # 配置加载
  data.py              # MT5 数据访问
  execution.py         # 下单与改止损
  guardrails.py        # 时段、新闻、方向、熔断守卫
  live.py              # 实盘轮询引擎
  models.py            # 通用数据模型
  news_calendar.py     # 自动财经日历
  risk.py              # 仓位计算
  strategy/
    base.py
    ma_cross_atr.py
    xau_m1_momentum.py
mql5/
  ExportEconomicCalendar.mq5  # MT5 经济日历导出器
```

## 四、安装

```bash
pip install -e .
```

如果只想直接运行，也可以自行安装依赖：

```bash
pip install MetaTrader5 pandas numpy PyYAML
```

## 五、配置文件说明

建议优先使用：

- [config.xauusd.m1.yaml](C:\Users\A\Documents\Codex\2026-05-14\mt5\config.xauusd.m1.yaml)

目前我已经把所有配置文件都加了中文备注，后续你可以直接边看边改。

### 重点配置

- `strategy.risk_per_trade`
  含义：单笔最大风险占净值比例

- `safety.one_direction_per_day`
  含义：是否限制同一天只做一个方向
  示例：当天先开多后，不再允许开空

- `safety.news_blackout_windows`
  含义：手工新闻黑窗
  格式：`YYYY-MM-DD HH:MM/YYYY-MM-DD HH:MM`

- `news_calendar.enabled`
  含义：是否启用自动财经日历

- `news_calendar.provider`
  含义：自动财经日历提供方
  当前支持：`disabled`、`mt5_file`、`tradingeconomics`

- `news_calendar.countries`
  含义：重点关注的国家列表
  `XAUUSD` 默认重点关注 `united states`

- `news_calendar.importance`
  含义：新闻重要性等级
  `1=低`、`2=中`、`3=高`

- `safety.trailing_trigger_pct`
  含义：浮盈达到多少比例后启动移动止损

- `safety.trailing_distance_pct`
  含义：移动止损距离当前价格的比例

## 六、运行方式

### 1. 回测

```bash
mt5-quant backtest --config config.xauusd.m1.yaml --bars 5000
```

如果需要把回测结果导出到指定目录：

```bash
mt5-quant backtest --config config.xauusd.m1.yaml --bars 5000 --report-dir reports\run_002
```

### 2. 实盘或模拟盘运行

```bash
mt5-quant live --config config.xauusd.m1.yaml
```

## 七、自动财经日历说明

当前版本支持自动从财经日历接口读取高影响事件，并自动生成新闻黑窗。

### 默认工作方式（推荐）

1. 系统按配置从外部财经日历读取未来若干天的重要事件
2. 按 `pre_blackout_minutes` 和 `post_blackout_minutes` 自动扩展为禁开仓时间窗
3. 到达这些时间窗时，系统只禁止“开新仓”，不会强制平已有仓位
4. 若接口读取失败，系统自动退回到手工配置的新闻黑窗，不会中断主流程

当前默认已经改成 `MT5 自带经济日历 -> MQL5 导出 CSV -> Python 自动读取`。

### MT5 官方日历接入步骤

1. 打开 [mql5/ExportEconomicCalendar.mq5](C:\Users\A\Documents\Codex\2026-05-14\mt5\mql5\ExportEconomicCalendar.mq5)
2. 把文件放到 MT5 的 `MQL5\Experts` 目录
3. 在 MT5 中编译并挂到任意图表
4. 保持 MT5 在线，EA 会定时把事件导出到 `Common\Files\mt5_calendar_events.csv`
5. Python 侧默认会自动读取这个文件，无需再改绝对路径

### 备用来源

- `TradingEconomics` 官方接口
- 仅当你有可用 API 凭证时建议启用
- 当前配置默认不再依赖它

### 默认过滤逻辑

- 国家：`united states`
- 重要性：`3`（高影响）
- 黑窗：新闻前 `10` 分钟，后 `10` 分钟

### 配置建议

- 如果使用 MT5 官方日历：
  `news_calendar.provider: "mt5_file"`
- 如果使用外部接口：
  `news_calendar.provider: "tradingeconomics"`
- 如果完全禁用自动日历：
  `news_calendar.enabled: false`

## 八、风控守卫说明

系统当前已支持以下守卫：

- 交易时段过滤
- 日内最大亏损熔断
- 连续亏损熔断
- 日内只做一个方向
- 手工新闻黑窗
- 自动财经日历黑窗
- 移动止损

## 九、回测报表

回测完成后会导出：

- `summary.json`
- `trades.csv`
- `equity_curve.csv`

`summary.json` 当前会包含：

- 最终资金
- 净利润
- 胜率
- 毛利润
- 毛亏损
- 平均单笔收益
- 平均盈利
- 平均亏损
- Profit Factor
- 最大回撤比例
- 被哪些风控规则拦下过多少次开仓

## 十、实盘前建议

建议你至少先做这几步：

1. 先用模拟盘跑 3 到 5 个交易日
2. 检查你券商 `XAUUSD` 的最小手数、步长、合约乘数、点值
3. 检查欧盘和美盘时段的实际滑点
4. 观察自动新闻黑窗是否覆盖你关注的高影响事件
5. 根据结果再细调：
   `risk_per_trade`
   `take_profit_pct`
   `stop_loss_pct`
   `trailing_trigger_pct`
   `trailing_distance_pct`

## 十一、说明

- 当前自动财经日历是“可开关”的，不想用时可以直接把 `news_calendar.enabled` 改成 `false`
- 当前“日内只做一个方向”也已经是“可开关”的，把 `safety.one_direction_per_day` 改成 `false` 即可
- 所有核心代码文件都建议用中文注释维护，当前版本我已经开始统一整理
