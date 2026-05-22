# src/mt5_quant/strategy/xau_m5_wave.py
import numpy as np
import talib as ta
from .base import Strategy, Signal

class XAUM5WaveStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.name = "XAU_M5_WAVE"
        
    def generate_signal(self, data):
        close = np.array(data['close'])
        high = np.array(data['high'])
        low = np.array(data['low'])
        volume = np.array(data.get('volume', []))
        
        if len(close) < 70:
            return Signal.HOLD
        
        # === 1. 三层 EMA 趋势确认 ===
        ema_fast = ta.EMA(close, timeperiod=12)
        ema_mid = ta.EMA(close, timeperiod=30)
        ema_slow = ta.EMA(close, timeperiod=70)
        
        price_above_slow = close[-1] > ema_slow[-1]
        price_below_slow = close[-1] < ema_slow[-1]
        uptrend = (ema_fast[-1] > ema_mid[-1] > ema_slow[-1]) and price_above_slow
        downtrend = (ema_fast[-1] < ema_mid[-1] < ema_slow[-1]) and price_below_slow
        
        if not (uptrend or downtrend):
            return Signal.HOLD
            
        # === 2. ATR 动态波动过滤 ===
        atr = ta.ATR(high, low, close, timeperiod=20)
        if atr[-1] < 10.0:  # 黄金ATR<10美元视为低波动
            return Signal.HOLD
            
        # === 3. 时间过滤：避开美盘开盘剧烈波动 ===
        from datetime import datetime
        current_time = datetime.now()
        # 北京时间 20:00-20:30 是美盘开盘（夏令时）
        if 20 <= current_time.hour <= 20 and current_time.minute < 30:
            return Signal.HOLD
            
        # === 4. 入场信号：回调至EMA21 ===
        if uptrend:
            if close[-1] < ema_mid[-1] and close[-2] > ema_mid[-2]:  # 回踩不破
                sl = low[-3:].min() - 1.5 * atr[-1]
                tp = close[-1] + 2.5 * atr[-1]
                return Signal(
                    action="BUY",
                    price=close[-1],
                    stop_loss=sl,
                    take_profit=tp,
                    meta={"reason": "wave_pullback", "atr": atr[-1]}
                )
                
        elif downtrend:
            if close[-1] > ema_mid[-1] and close[-2] < ema_mid[-2]:  # 反弹受阻
                sl = high[-3:].max() + 1.5 * atr[-1]
                tp = close[-1] - 2.5 * atr[-1]
                return Signal(
                    action="SELL",
                    price=close[-1],
                    stop_loss=sl,
                    take_profit=tp,
                    meta={"reason": "wave_rejection", "atr": atr[-1]}
                )
                
        return Signal.HOLD