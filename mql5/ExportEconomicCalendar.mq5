//+------------------------------------------------------------------+
//| 把 MT5 内置经济日历导出为 CSV，供 Python 风控层自动读取               |
//| 重点用途：只导出 USD 高影响新闻，给黄金 / BTC 策略做自动新闻黑窗      |
//+------------------------------------------------------------------+
#property strict

input string InpOutputFileName    = "mt5_calendar_events.csv"; // 导出到 Common\Files 的 CSV 文件名
input string InpStatusLogFileName = "mt5_calendar_status.log"; // 导出状态日志文件名
input string InpCurrencyFilter    = "USD";                     // 只导出该货币事件，默认 USD
input int    InpImportanceMin     = 3;                         // 最低重要性：1=低，2=中，3=高
input int    InpLookaheadDays     = 7;                         // 向前导出未来多少天事件
input int    InpRefreshMinutes    = 30;                        // 自动刷新间隔，单位分钟

void WriteStatusLog(string status,string detail)
  {
   int handle=FileOpen(InpStatusLogFileName,FILE_WRITE|FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE)
     {
      PrintFormat("[状态日志] 写入失败，error=%d",GetLastError());
      return;
     }

   FileSeek(handle,0,SEEK_END);
   FileWriteString(
      handle,
      StringFormat(
         "%s | %s | %s\r\n",
         TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
         status,
         detail
      )
   );
   FileClose(handle);
  }

void PrintSelfCheckHints()
  {
   bool connected=(bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   Print("========== 经济日历导出器自检 ==========");
   PrintFormat("[自检] 当前终端连接状态: %s",connected ? "已连接" : "未连接");
   PrintFormat("[自检] 当前将只导出货币=%s、重要性>=%d 的事件",InpCurrencyFilter,InpImportanceMin);
   PrintFormat("[自检] CSV 输出位置: Common\\Files\\%s",InpOutputFileName);
   PrintFormat("[自检] 状态日志位置: Common\\Files\\%s",InpStatusLogFileName);
   Print("[自检] 如 Python 侧提示缺少新闻文件，请先确认本 EA 已挂到图表并成功输出。");
   Print("[自检] 如导出记录为 0，请确认 MT5 已联网、经济日历可用，并检查未来几天是否确有 USD 高影响事件。");
   Print("======================================");
  }

int OnInit()
  {
   PrintSelfCheckHints();
   WriteStatusLog("INIT","导出器已启动，准备执行首次导出。");
   EventSetTimer(MathMax(60,InpRefreshMinutes*60));
   ExportCalendar();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   WriteStatusLog("STOP",StringFormat("导出器停止，reason=%d",reason));
  }

void OnTick()
  {
   // 该 EA 仅负责导出经济日历，不参与交易逻辑。
  }

void OnTimer()
  {
   ExportCalendar();
  }

void ExportCalendar()
  {
   datetime from_time=TimeTradeServer();
   if(from_time==0)
      from_time=TimeCurrent();

   datetime to_time=from_time+InpLookaheadDays*24*60*60;
   MqlCalendarValue values[];
   ArrayFree(values);

   int raw_count=CalendarValueHistory(values,from_time,to_time,NULL,InpCurrencyFilter);
   if(raw_count<0)
     {
      string detail=StringFormat(
         "CalendarValueHistory 调用失败，error=%d。请检查 MT5 是否联网，以及经济日历是否可用。",
         GetLastError()
      );
      Print(detail);
      WriteStatusLog("ERROR",detail);
      return;
     }

   int file_handle=FileOpen(
      InpOutputFileName,
      FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,
      ','
   );
   if(file_handle==INVALID_HANDLE)
     {
      string detail=StringFormat("FileOpen 打开 CSV 失败，error=%d",GetLastError());
      Print(detail);
      WriteStatusLog("ERROR",detail);
      return;
     }

   FileWrite(file_handle,"utc_time","server_time","title","currency","country","importance");

   // 经济日历时间默认是交易服务器时区，这里统一折算成 UTC，便于 Python 端处理。
   int server_offset_seconds=(int)(TimeTradeServer()-TimeGMT());
   int exported_count=0;
   int skipped_non_usd=0;
   int skipped_low_impact=0;

   for(int i=0;i<raw_count;i++)
     {
      MqlCalendarEvent event_info;
      if(!CalendarEventById(values[i].event_id,event_info))
         continue;

      if((int)event_info.importance<InpImportanceMin)
        {
         skipped_low_impact++;
         continue;
        }

      MqlCalendarCountry country_info;
      string currency=InpCurrencyFilter;
      string country_name="";
      if(CalendarCountryById(event_info.country_id,country_info))
        {
         currency=country_info.currency;
         country_name=country_info.name;
        }

      if(currency!=InpCurrencyFilter)
        {
         skipped_non_usd++;
         continue;
        }

      datetime utc_time=values[i].time-server_offset_seconds;

      FileWrite(
         file_handle,
         TimeToString(utc_time,TIME_DATE|TIME_SECONDS),
         TimeToString(values[i].time,TIME_DATE|TIME_SECONDS),
         event_info.name,
         currency,
         country_name,
         (int)event_info.importance
      );
      exported_count++;
     }

   FileClose(file_handle);

   if(exported_count>0)
     {
      string success_detail=StringFormat(
         "导出成功：原始事件=%d，导出=%d，过滤掉非 %s=%d，过滤掉低影响=%d，文件=Common\\Files\\%s",
         raw_count,
         exported_count,
         InpCurrencyFilter,
         skipped_non_usd,
         skipped_low_impact,
         InpOutputFileName
      );
      Print(success_detail);
      WriteStatusLog("SUCCESS",success_detail);
      return;
     }

   string warn_detail=StringFormat(
      "本次导出完成但结果为 0。原始事件=%d，低影响过滤=%d，非 %s 过滤=%d。请检查未来 %d 天是否存在 %s 高影响事件。",
      raw_count,
      skipped_low_impact,
      InpCurrencyFilter,
      skipped_non_usd,
      InpLookaheadDays,
      InpCurrencyFilter
   );
   Print(warn_detail);
   WriteStatusLog("WARN",warn_detail);
  }
