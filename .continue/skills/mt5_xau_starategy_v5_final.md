# 技能：MT5 黄金策略 V5 —— 三重滤网 + 阶梯熔断 + 多周期协同 + Web 全栈系统

## 描述
构建一个专为 XAUUSD 设计的抗脆弱交易系统，解决 M1 周期高噪音、假突破、插针等实战痛点。通过 **三重信号过滤（价格结构+RSI+MACD） + 阶梯冷却 + M5/M15 趋势锚定 + Web 可视化控制**，实现“低频高胜率、连亏即退守、一切可配置、全周期可诊断”。

---

## 执行计划（7 步，全部展开）
## 执行器的特别说明
分形高低点：使用 ta.highest(high, 5) 和 ta.lowest(low, 5) 实现，避免未来函数
RSI 背离检测：记录最近 3 个 Swing 点及其 RSI 值，比较是否背离
美盘避险：作为独立 Guardrail，不硬编码在策略逻辑中
Web 配置同步：前端表单字段名必须与 Pydantic 模型严格一致
熔断状态加载：主循环启动时必须从 JSON 加载状态
行情片段保存：CSV 文件包含 time, open, high, low, close, tick_volume
错误处理：所有模块必须捕获异常，不得崩溃主交易进程
💡 终极原则：M1 策略必须 宁可错过，不可做错。在不确定时，一律返回 HOLD。
---
### 步骤 1：重构 M1 动量策略（`xau_m1_momentum.py`）
- **路径**：`src/mt5_quant/strategy/xau_m1_momentum.py`
- **逻辑**：
  - 前置检查：ATR<6 或美盘20:00–20:30(配置可控) → HOLD
  - 三重过滤：
    1. **价格结构**：用分形识别 Swing High/Low，价格需在趋势通道内
    2. **RSI(14)**：50–70（多）或 30–50（空），且无背离
    3. **MACD**：柱状图连续2根同向放大
  - 动态入场：`entry = high/low ± ATR × breakout_atr_multiple`
  - 返回：仅当全部通过才返回 BUY/SELL

### 步骤 2：开发 M5/M15 波段策略
- **路径**：
  - `src/mt5_quant/strategy/xau_m5_wave.py`
  - `src/mt5_quant/strategy/xau_m15_wave.py`
- **逻辑**：
  - 趋势确认：EMA12>30>70 + ADX>20（M15）或 >25（M5）
  - 入场：价格回踩 EMA30 + RSI 40–60
  - 出场：trailing stop = ATR×2
  - 协同：调用 `trend_arbiter.get_global_trend("XAUUSD", "M15")`，逆趋势禁止开仓

### 步骤 3：阶梯式熔断系统
- **路径**：`src/mt5_quant/guardrails/loss_streak.py`
- **规则**：
  - ≥3 连亏：PAUSE 15分钟
  - ≥5 连亏：CLOSE_ONLY 1小时
  - ≥7 连亏：ALERT + 保存行情片段
- **持久化**：状态写入 `~/.mt5_py/state/xauusd_m1.cooling.json`

### 步骤 4：增强 Telegram 警报
- **路径**：`src/mt5_quant/alerts/telegram_alert.py`
- **内容**：连亏详情 + 当前指标状态 + CSV 路径 + 建议（如“切换至M5”）

### 步骤 5：自动调参脚本
- **路径**：`tools/auto_tune_params.py`
- **功能**：每日优化 `breakout_atr_multiple`，目标假突破率 <15%

### 步骤 6：多周期信号诊断脚本
- **路径**：`tools/diagnose_xau_signals.py`
- **输出**：M1/M5/M15 对比表格（信号数、胜率、盈亏比、最大连亏） + 建议语句

### 步骤 7：Web 全栈控制系统
- **后端（FastAPI）**：
  - 路由：`/api/config`, `/api/diagnosis`, WebSocket `/ws/signals`
  - 安全：JWT 认证 + 配置变更日志
- **前端（Vue3 + Vite + TS）**：
  - 页面：Dashboard、StrategyView（含配置表单、实时信号、诊断报告）
  - 技术：Pinia + ECharts + Tailwind CSS
- **部署**：`web/start.sh` + `web/Dockerfile`

---

## 输出要求（必须生成的完整文件清单）
## 成功标准（7 项可验证行为）

1. ✅ **M1 策略**：在 ATR<6 或美盘20:00–20:30 期间返回 `HOLD`
2. ✅ **M5/M15 策略**：仅在全局趋势方向一致时开仓（通过 `trend_arbiter`）
3. ✅ **熔断系统**：连亏5次后进入“仅平仓”模式，重启后状态仍有效
4. ✅ **Telegram 警报**：连亏7次时发送含 CSV 路径的警报
5. ✅ **自动调参**：`auto_tune_params.py` 能成功更新 YAML 中的 `breakout_atr_multiple`
6. ✅ **诊断脚本**：`diagnose_xau_signals.py` 输出 M1/M5/M15 对比表格
7. ✅ **Web 系统**：
   - 访问 `http://localhost:5173` 可打开界面
   - 修改配置后，YAML 文件被正确更新且有备份
   - WebSocket 实时推送新信号

---

## 配置文件规范（YAML 必须包含字段）

```yaml
# xauusd.m1.yaml 示例
symbol: XAUUSD
timeframe: M1
lot_size: 0.1
slippage: 3

strategy_params:
  breakout_atr_multiple: 1.0
  ema_fast: 9
  ema_mid: 21
  ema_slow: 50

guardrails:
  max_loss_streak_3: 3
  max_loss_streak_5: 5
  max_loss_streak_7: 7
  atr_min_threshold: 6
  us_session_blackout: true  # 美盘避险开关

auto_tune:
  enabled: true
  breakout_param_path: "strategy_params.breakout_atr_multiple"
### Python 策略与工具