# tools/verify_news_blackout.py
import os
import pandas as pd
from datetime import datetime, timedelta

def check_news_calendar():
    path = r"C:\Users\Public\Documents\MT5-Common\Files\mt5_calendar_events.csv"
    
    if not os.path.exists(path):
        print("❌ 新闻日历文件不存在！请确认：")
        print("1. MT5 已运行 ExportEconomicCalendar.mq5")
        print("2. EA 已启用 '允许 DLL'")
        return
        
    df = pd.read_csv(path)
    df['time'] = pd.to_datetime(df['time'])
    recent = df[df['time'] > datetime.now() - timedelta(days=1)]
    
    print(f"✅ 找到 {len(recent)} 条近期新闻事件：")
    for _, row in recent.tail(3).iterrows():
        print(f"  - {row['time'].strftime('%Y-%m-%d %H:%M')} | {row['currency']} | {row['impact']}")
        
    # 检查高影响事件
    high_impact = recent[recent['impact'] >= 3]
    if not high_impact.empty:
        next_event = high_impact.iloc[0]
        now = datetime.now()
        diff_min = (next_event['time'] - now).total_seconds() / 60
        if abs(diff_min) < 60:
            print(f"⚠️ 高影响新闻将在 {diff_min:.1f} 分钟后发生！黑窗应激活")
        else:
            print("ℹ️ 无近期高影响新闻")
    else:
        print("ℹ️ 未来24小时无高影响新闻")

if __name__ == "__main__":
    check_news_calendar()