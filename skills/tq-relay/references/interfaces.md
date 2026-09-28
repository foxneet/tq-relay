# TQ 接口速查（经 TQRelay 全部实测）

> 代码格式 `159582.SZ` / `518880.SH`。返回值挂在 `resp['result']` 下。
> `dividend_type`：get_market_data 用字符串 `'none'/'front'/'back'`；formula 接口用**整数** `0=不复权, 1=前复权`（实测确认，勿混）。

| method | 关键 params | result 要点 |
|---|---|---|
| `get_market_data` | stock_list, period='1d', start_time/end_time(YYYYMMDD), dividend_type, fill_data=False | `Value['<code>'].{Date,Open,High,Low,Close,Volume(股),Amount(万元),VolInStock,ForwardFactor,...}`；**窗口>约2年分页**（`KlinePaged`/`has_more`），全历史按年份分窗拼接 |
| `formula_process_mul_zb` | formula_name, stock_list, stock_period, start_time(建议19900101), end_time, return_date=True, return_count(末尾N根), dividend_type(整数1=前复权), xsflag(小数位) | `result['<code>']['<输出行名>'] = [{'Date','Value'},...]`；输出行名/公式名为中文；未命名行叫 OUTPUTn；WINNER/COST 等筹码函数由通达信原生计算，与图上 100% 一致 |
| `get_market_snapshot` | stock_code | `result.Now/LastClose/Volume/...` 实时快照 |
| `get_stock_info` | stock_code | `result.Name/ActiveCapital(流通股本,万股)/J_start(上市日)/HSStockKind(7=基金)...` |
| `get_match_stkinfo` | key_word(中文名) | `result.Value=[{Code,Name},...]` 名称模糊检索 |
| `get_stock_list` | market('31'=全部ETF基金), list_type 0/1 | `result.Value` |
| `get_more_info` | stock_code | `result.fHSL(换手)/Zsz/Ltsz/ZTPrice/...`（个别字段对部分品种为空） |
| `get_gb_info_by_date` | stock_code, start_date, end_date | `result.Value=[{Date,Zgb,Ltgb},...]` 历史逐日股本 → 精确换手率 |
| `get_divid_factors` | stock_code | `result.Value`（ETF可能为空） |
| `get_zdt_data` | stock_list | `result.Value['<code>'].{ZDTStatusNow,...}` 涨跌停状态 |
| `get_trading_dates` | market, start_time, end_time | `result.Value`（个别参数组合实测返回空，用前自验） |
| `query_stock_positions` | account_id(默认0) | `result.{ErrorId,Value}`；需通达信端登录资金账户 |
| `order_stock` | account_id, stock_code, order_type(0买1卖), order_volume, price_type, price | 交易类；受服务端 `allow_trade` 约束；需通达信端登录资金账户 |

完整接口清单见通达信官方 `help.tdx.com.cn/quant/`——tqcenter 有的接口，转发器都能调（`POST /tq` 零维护透传）。

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `{'error': 'token错误'}` | token 不对/为空 | 通达信机配置文件 `TQ转发器_配置.json` 或 GUI 查 token |
| ConnectionRefused | 转发器没运行/端口错/防火墙 | 通达信机起服务；放行 17710 |
| 超时 | 重公式计算中/TQ 卡死 | 加大客户端 timeout；看通达信机日志 |
| `result.Error`="资金账户未登录" | 通达信端无交易账户 | 登录资金账户，或不用交易接口 |
| K线根数不符 | 分页 | 按年份分窗拼接 |
| 公式返回空/值全0 | 喂入窗口太短或品种无本地数据 | `start_time=19900101`；先在通达信打开该品种 |
