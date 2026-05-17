//+------------------------------------------------------------------+
//| 将 MT5 内置经济日历导出为 CSV，供 Python 风控层自动读取。        |
//| 使用方式：把该 EA 挂到任意图表上，保持终端在线即可定时刷新。      |
//+------------------------------------------------------------------+
#property strict

input string InpOutputFileName    = "mt5_calendar_events.csv"; // 输出到 Common\Files 的文件名
input string InpCurrencyFilter    = "USD";                     // 过滤货币，黄金通常关注 USD
input int    InpImportanceMin     = 3;                         // 最低重要性：1低 2中 3高
input int    InpLookaheadDays     = 7;                         // 向前导出未来多少天事件
input int    InpRefreshMinutes    = 30;                        // 定时刷新间隔，单位分钟

int OnInit()
  {
   EventSetTimer(MathMax(60, InpRefreshMinutes * 60));
   ExportCalendar();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTick()
  {
   // 该 EA 只负责导出经济日历，不参与交易逻辑。
  }

void OnTimer()
  {
   ExportCalendar();
  }

void ExportCalendar()
  {
   datetime from_time = TimeTradeServer();
   if(from_time == 0)
      from_time = TimeCurrent();

   datetime to_time = from_time + InpLookaheadDays * 24 * 60 * 60;
   MqlCalendarValue values[];
   ArrayFree(values);

   int count = CalendarValueHistory(values, from_time, to_time, NULL, InpCurrencyFilter);
   if(count < 0)
     {
      PrintFormat("CalendarValueHistory failed, error=%d", GetLastError());
      return;
     }

   int file_handle = FileOpen(
      InpOutputFileName,
      FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON,
      ','
   );
   if(file_handle == INVALID_HANDLE)
     {
      PrintFormat("FileOpen failed, error=%d", GetLastError());
      return;
     }

   FileWrite(file_handle, "utc_time", "server_time", "title", "currency", "country", "importance");

   // 经济日历时间默认是交易服务器时区，这里在导出时统一折算成 UTC，方便 Python 端处理。
   int server_offset_seconds = (int)(TimeTradeServer() - TimeGMT());

   for(int i = 0; i < count; i++)
     {
      MqlCalendarEvent event_info;
      if(!CalendarEventById(values[i].event_id, event_info))
         continue;

      if((int)event_info.importance < InpImportanceMin)
         continue;

      MqlCalendarCountry country_info;
      string currency = InpCurrencyFilter;
      string country_name = "";
      if(CalendarCountryById(event_info.country_id, country_info))
        {
         currency = country_info.currency;
         country_name = country_info.name;
        }

      datetime utc_time = values[i].time - server_offset_seconds;

      FileWrite(
         file_handle,
         TimeToString(utc_time, TIME_DATE | TIME_SECONDS),
         TimeToString(values[i].time, TIME_DATE | TIME_SECONDS),
         event_info.name,
         currency,
         country_name,
         (int)event_info.importance
      );
     }

   FileClose(file_handle);
   PrintFormat("Economic calendar exported: %d rows -> Common\\\\Files\\\\%s", count, InpOutputFileName);
  }
