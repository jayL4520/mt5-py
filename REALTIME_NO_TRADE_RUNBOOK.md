# 实盘/模拟盘零成交排查运行手册

## 一、目标

这份文档用于排查以下问题：

- 回测有成交，但模拟盘/真实盘没有成交
- 日志持续出现 `hold`
- 日志持续出现 `outside_trading_window`
- 运行很久都没有任何下单动作

## 二、标准排查顺序

不要一上来就改策略。先按下面顺序排查。

## 三、步骤 1：确认当前运行的是哪个配置

如果你是通过 GUI 启动，真正运行的不是原始配置，而是：

- `profiles/xau.runtime.yaml`
- `profiles/btc.runtime.yaml`

先确认以下几项是不是你以为的值：

- `trading.symbol`
- `trading.timeframe`
- `strategy.name`
- `safety.trading_windows`
- `safety.one_direction_per_day`
- `news_calendar.enabled`

## 四、步骤 2：先看日志里有没有明显的拦截原因

查看：

- `logs/mt5-quant.log`

重点搜索：

- `New trade blocked`
- `Opening`
- `No action`

常见含义：

- `outside_trading_window`
  说明当前时间不在允许交易窗口内
- `news_blackout_window`
  说明当前在新闻黑窗
- `consecutive_loss_limit_reached`
  说明连续亏损熔断已触发
- `daily_loss_limit_reached`
  说明日内最大亏损熔断已触发
- `one_direction_per_day`
  说明日内方向限制拦截了反向信号

## 五、步骤 3：用诊断模式确认“有没有原始信号”

### 黄金

```bash
mt5-quant diagnose-signals --config config.xauusd.m1.yaml --bars 1500 --output-dir reports/xau_diag
```

### BTC

```bash
mt5-quant diagnose-signals --config config.btcusd.m15.yaml --bars 2500 --output-dir reports/btc_diag
```

看生成文件：

- `diagnosis_summary.json`
- `diagnosis_report.md`

重点看：

- `raw_entry_signal_count`
- `recent_entry_signals`
- `blocked_entries`
- `diagnosis_conclusions`

## 六、步骤 4：确认时间周期是不是匹配

这是最容易忽略的点。

例如：

- BTC 配置是 `M15`
- 但你拿来验证的 CSV 或观察样本实际是 `M1`

这种情况下，策略信号结论基本没有参考价值。

诊断报告里重点看：

- `expected_interval_minutes`
- `actual_interval_minutes`
- `interval_matches_config`

## 七、步骤 5：确认观察时间是否正确

### 黄金 XAU

如果配置里是：

```yaml
trading_windows:
  - "14:00-02:00"
```

那就意味着上海时间：

- 14:00 之前不允许新开仓
- 02:00 之后不允许新开仓

所以在 `13:52` 看到：

```text
New trade blocked: outside_trading_window
```

这是正常现象，不是 bug。

### BTC

BTC 是 `M15` 策略，信号频率低，不适合用几分钟的观察窗口去判断系统是否正常。

## 八、步骤 6：确认你是在等“新收盘 K 线”

实盘引擎不是 tick 级无限扫信号，它是：

1. 拉取最新 K 线
2. 跳过最后一根未收盘 K 线
3. 只处理新产生的已收盘 K 线

所以：

- `M1` 需要等每根 1 分钟 K 线收盘
- `M15` 需要等每根 15 分钟 K 线收盘

如果 K 线还没收盘，不应期待系统立即开仓。

## 九、步骤 7：确认是否真的进入过开仓阶段

只有当日志出现类似内容时，才说明系统已经尝试开仓：

```text
Opening buy position because ...
Opening sell position because ...
```

如果完全没有 `Opening`，说明问题仍在“信号/风控链路”，不是下单执行链路。

## 十、步骤 8：如果已尝试开仓但 MT5 没单，再查 MT5 执行层

这时重点查：

- MT5 是否登录成功
- 品种是否在 `Market Watch` 可交易
- 品种名是否与券商实际名称一致
- 最小手数是否满足
- 手数步进是否满足
- 止损止盈距离是否满足券商限制
- 市场是否开盘
- MT5 `Experts` 和 `Journal` 是否有拒单原因

## 十一、建议的日常使用方式

### 黄金

1. 在允许交易时段内启动
2. 先跑 `diagnose-signals`
3. 再观察实盘日志

### BTC

1. 不要用分钟级短窗口判断是否正常
2. 至少观察多个 `M15` 收盘周期
3. 优先用 `diagnose-signals` 看最近一段真实数据

## 十二、推荐命令

### 黄金诊断

```bash
mt5-quant diagnose-signals --config config.xauusd.m1.yaml --bars 1500 --output-dir reports/xau_diag
```

### BTC 诊断

```bash
mt5-quant diagnose-signals --config config.btcusd.m15.yaml --bars 2500 --output-dir reports/btc_diag
```

### 黄金实盘/模拟盘

```bash
mt5-quant live --config config.xauusd.m1.yaml
```

### BTC 实盘/模拟盘

```bash
mt5-quant live --config config.btcusd.m15.yaml
```

## 十三、最终判断规则

可以按下面这条规则快速判断：

- `raw_entry_signal_count = 0`
  先查策略条件和样本质量
- `raw_entry_signal_count > 0` 但 `blocked_entries` 很多
  先查风控和时间窗
- 日志没有 `Opening`
  先查信号与过滤链路
- 日志有 `Opening` 但 MT5 没单
  再查执行链路和券商限制
