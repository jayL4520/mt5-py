# MT5 量化交易系统

当前代码版本：`1.0.1`

这是一个基于 `Python + MetaTrader 5` 的量化交易系统。  
目前已经包含两条可直接使用的专用品种方案：

- `1.0.0`：`XAUUSD / M1` 黄金专用版
- `1.0.1`：在 `1.0.0` 基础上新增 `BTCUSD / M15` 比特币专用策略

## 一、版本说明

### 1.0.0

这是第一版黄金专用版，重点是把 `XAUUSD / M1` 做成可直接运行、可回测、可接 MT5 的版本。

已完成：

- 黄金专用策略 `xau_m1_momentum`
- 风控、仓位、执行、回测
- 交易时段过滤
- 日内最大亏损熔断
- 连续亏损熔断
- 日内单方向开关
- 新闻黑窗
- MT5 自带经济日历自动黑窗
- 中文配置说明
- 中文代码注释
- `exe` 打包支持

### 1.0.1

这是策略扩展版，新增 `BTCUSD` 专业策略并融入原系统。

已完成：

- 新增 `btc_m15_regime` 策略
- 新增 BTC 示例配置
- BTC 接入同一套风控、回测、实盘和报表系统
- 项目版本升级到 `1.0.1`

## 二、当前支持的策略

### 1. 黄金策略：`xau_m1_momentum`

适用品种：

- `XAUUSD`
- 默认周期：`M1`

逻辑核心：

- EMA 趋势过滤
- 突破确认
- RSI 动量确认
- 固定百分比止盈止损
- 移动止损

推荐配置文件：

- [config.xauusd.m1.yaml](C:\Users\A\Documents\Codex\2026-05-14\mt5\config.xauusd.m1.yaml)

### 2. BTC 策略：`btc_m15_regime`

适用品种：

- `BTCUSD`
- 默认周期：`M15`

逻辑核心：

- EMA 快慢线识别趋势状态
- ADX 判断趋势是否足够强
- Donchian Breakout 判断关键区间突破
- RSI 做动量确认
- Volume Mean 过滤低质量突破
- ATR 动态止损 + 固定收益风险比止盈

推荐配置文件：

- [config.btcusd.m15.yaml](C:\Users\A\Documents\Codex\2026-05-14\mt5\config.btcusd.m15.yaml)

## 三、项目结构

```text
src/mt5_quant/
  backtest.py
  cli.py
  config.py
  data.py
  execution.py
  guardrails.py
  live.py
  models.py
  news_calendar.py
  risk.py
  strategy/
    base.py
    ma_cross_atr.py
    xau_m1_momentum.py
    btc_m15_regime.py

mql5/
  ExportEconomicCalendar.mq5

build_exe.ps1
mt5_quant.spec
RELEASE_NOTES.md
```

## 四、安装

### 1. 普通安装

```bash
pip install -e .
```

### 2. 带打包依赖安装

```bash
pip install -e .[build]
```

## 五、运行方式

### 0. 多品种切换启动器

现在同一个 `exe` 或同一个 Python 入口已经支持“多品种切换启动器”。
默认会优先打开图形界面窗口；如果图形界面启动失败，则自动回退到文本菜单。

如果你直接双击：

- `mt5-quant.exe`

或者直接运行：

```bash
mt5-quant
```

系统会自动进入菜单，你可以直接选择：

- 黄金 `XAUUSD / M1`
- 比特币 `BTCUSD / M15`
- 实盘 / 模拟盘
- MT5 历史回测
- CSV 回测
- 配置编辑并保存为运行副本

### 图形界面版新增能力

图形界面启动器当前支持：

- 选择黄金或 BTC 预设
- 直接编辑账号、服务器、交易品种、风险参数
- 编辑交易时段、移动止损、新闻日历等关键配置
- 保存为运行时配置副本
- 一键启动实盘 / 模拟盘
- 一键启动 MT5 历史回测
- 一键启动 CSV 回测

### 运行配置副本机制

为了保留你原始配置文件里的中文备注，GUI 不会直接覆盖原始配置，而是把修改后的内容写到：

- `profiles/xau.runtime.yaml`
- `profiles/btc.runtime.yaml`

之后启动器会优先使用这些运行副本。

如果你想用命令直接指定预设，也可以：

```bash
mt5-quant launch --profile xau --mode live
mt5-quant launch --profile btc --mode backtest --bars 5000
```

### 1. 黄金回测

```bash
mt5-quant backtest --config config.xauusd.m1.yaml --bars 5000
```

### 2. 黄金实盘或模拟盘

```bash
mt5-quant live --config config.xauusd.m1.yaml
```

### 3. BTC 回测

```bash
mt5-quant backtest --config config.btcusd.m15.yaml --bars 5000
```

### 4. BTC 实盘或模拟盘

```bash
mt5-quant live --config config.btcusd.m15.yaml
```

## 六、打包 EXE

当前版本已经加好打包工具，可以直接打包成 `exe`。

### 打包前准备

先安装打包依赖：

```bash
pip install -e .[build]
```

### 开始打包

在项目根目录运行：

```powershell
.\build_exe.ps1
```

### 打包结果

打包完成后会在 `dist` 目录生成：

- `mt5-quant.exe`

同时 `spec` 文件会把这些资源一起带上：

- `README.md`
- `config.example.yaml`
- `config.xauusd.m1.yaml`
- `config.btcusd.m15.yaml`
- `mql5/ExportEconomicCalendar.mq5`

## 七、自动财经日历

默认推荐使用 `MT5 自带经济日历`：

- 由 [ExportEconomicCalendar.mq5](C:\Users\A\Documents\Codex\2026-05-14\mt5\mql5\ExportEconomicCalendar.mq5) 导出
- Python 自动读取 `Common\Files\mt5_calendar_events.csv`

### 接入步骤

1. 把 `ExportEconomicCalendar.mq5` 放到 MT5 的 `MQL5\Experts`
2. 在 MT5 中编译
3. 挂到任意图表
4. 保持 MT5 在线
5. Python 侧会自动读取导出的新闻事件

## 八、配置说明

我已经把主要配置文件都改成了中文备注版：

- [config.example.yaml](C:\Users\A\Documents\Codex\2026-05-14\mt5\config.example.yaml)
- [config.xauusd.m1.yaml](C:\Users\A\Documents\Codex\2026-05-14\mt5\config.xauusd.m1.yaml)
- [config.btcusd.m15.yaml](C:\Users\A\Documents\Codex\2026-05-14\mt5\config.btcusd.m15.yaml)
- [config.yaml](C:\Users\A\Documents\Codex\2026-05-14\mt5\config.yaml)

关键开关包括：

- `safety.one_direction_per_day`
- `safety.news_blackout_windows`
- `safety.trailing_stop_enabled`
- `news_calendar.enabled`
- `news_calendar.provider`

## 九、回测输出

回测完成后会输出：

- `summary.json`
- `trades.csv`
- `equity_curve.csv`

## 十、建议

实盘前建议至少先做：

1. 模拟盘验证
2. 检查券商品种点值、合约乘数、最小手数
3. 检查欧盘、美盘和周末时段的滑点
4. 检查自动新闻黑窗是否正常导出
5. 分别独立验证黄金和 BTC 的实际成交行为
