# AGENTS.md — 给 AI Agent 的使用与维护指南

本文件面向将要**使用或维护 TQRelay** 的 AI agent（ZCode / Claude / Cursor 等）。读完即可正确部署、调用、改代码、跑验证，不需要向用户追问背景。

## 30 秒理解本工具

通达信的 TQ 量化服务（tqcenter）只监听本机 `127.0.0.1:17709`，局域网其他机器无法访问。TQRelay 运行在**通达信所在机器**，把 TQ 全部接口以 HTTP 暴露给局域网：`POST /tq?token=...`（token 鉴权，通用透传）+ 可选透明端口 `:17711`（无 token 纯透传，配客户端 portproxy 让旧代码零改动跨机）。

- 纯 Python 标准库；GUI（tkinter）与 `--serve` 无界面双模式
- 返回 TQ 原始 JSON；错误分**两层**：转发层 `{"error": ...}`、TQ 层 `result.ErrorId != "0"`
- 公式类接口（含 `WINNER`/`COST` 筹码）由通达信引擎原生计算，与图上指标 100% 一致

## 何时用 / 何时不用

**用**：调用方（ZCode、大QMT 策略、任意 Python）与通达信**不同机**；或 QMT 平台禁止读写文件、MiniQMT 停用，HTTP 是唯一通道。
**不用**：调用方与通达信**同机**——直连 `127.0.0.1:17709` 即可，不必经网关。

## 部署（通达信机上，一次性）

```bash
python tq_relay.py            # GUI模式, 启动即自动开服务, 首次运行自动生成配置与随机token
python tq_relay.py --serve    # 无界面后台
netsh advfirewall firewall add rule name="TQRelay" dir=in action=allow protocol=TCP localport=17710
```

token 在同目录 `TQ转发器_配置.json`（或 GUI 查看）；**token 是机密，不要写进代码仓库或公开文档**。透明端口无鉴权，开启时务必配 `allow_ips` 白名单；不做交易就 `allow_trade=false`。

## 调用方式（替用户写代码时）

**推荐仓库自带客户端** `skills/tq-relay/scripts/tq_client.py`（纯标准库，CLI 与 Python 类两种用法，已封装两层错误检查）：

```python
from tq_client import TQRelay, TQRelayError
relay = TQRelay('<通达信机IP>', token='XXX', timeout=300)
resp = relay.call('get_market_data', {...})      # 失败统一抛 TQRelayError
```

QMT 策略内不能带依赖文件时，用 README「客户端示例」的内嵌 `tq()` 模板（token 用常量手工粘贴——部分 QMT 平台策略进程读不到用户环境变量，已实测）。

## 替用户做技术决策的规则（全部实测踩坑）

1. **两层错误都要查**：转发层 `error`（连接/超时/token），TQ 层 `result.ErrorId != "0"`。用自带客户端则已封装。
2. **筹码函数绝不在客户端重算**：纯 Python 复现信号段起点当日吻合度仅约 73%；必须走 `formula_process_mul_zb` 让通达信原生算。
3. **复权参数类型不统一**：`get_market_data` 用字符串 `'none'/'front'/'back'`；formula 接口用**整数** `0/1`。搞混会静默返回错数据。
4. **K线分页**：单窗 >约 2 年只回一页（`KlinePaged`/`has_more`）——按年份分窗拼接，别一次拉全历史。
5. **公式喂入窗口影响筹码**：要与图一致就 `start_time=19900101` 喂全历史 + `return_count` 只取末尾 N 根。
6. **公式输出默认四舍五入**：阈值判断必须 `xsflag=3` 以上精度。
7. **串行化**：TQ 调用全局锁排队，不会并行；批量任务预估排队时间、加大 timeout（重公式建议 300s）。
8. **品种查无此码**：先在通达信手动打开该品种促发本地数据下载。
9. **只透传接口调用**：不转发"整段策略代码交给通达信跑"的托管模式。

## 硬约束（违反即出错）

1. `tq_relay.py` 必须保持**纯标准库**（任何第三方依赖都会破坏 exe 单文件分发与 QMT 环境兼容）。
2. 安全三开关：主端口 token、`allow_ips` 白名单（透明端口）、`allow_trade`（默认建议 false）。不要建议用户全开，除非用户明确要求并知晓风险。
3. 配置文件 `TQ转发器_配置.json` 含 token，已被 `.gitignore` 排除——不要把它提交或复制进仓库其他位置。
4. 服务端日志按日期写在 `log_dir`；排查问题先看机器 A 的日志（含来源 IP、方法、参数摘要、耗时）。

## 改代码后的必做验证协议（历史教训驱动，别省略）

1. **静态**：`py -3.14 -m pyflakes tq_relay.py` —— 必须无 undefined name（v1.0.0 曾漏 `import queue`，GUI 一开就 NameError 崩溃，而 `--serve` 正常，只跑一种模式发现不了）。
2. **实弹**：`python tq_relay.py --serve` 起服务后跑全套：ping、错误 token 拒绝、`get_market_data`/`get_market_snapshot`/`get_trading_dates` 真数据、交易接口被 `allow_trade` 拦截、透明端口裸转发、当日日志落盘。
3. **GUI**：真实打开一次 GUI（服务自动启动），点『自检』和『测试通达信』（v1.0.0 时代后者曾因未定义变量 TODAY 报 NameError——两处教训同源：GUI 专属代码路径必须真实点过）。
4. **QMT 端**：把 `tests/selftest_qmt.py` 全文粘进 QMT 新策略运行（GBK 文件），16 项应全过。
5. 打包 exe：`py -3.14 -m PyInstaller --onefile --windowed --name TQRelay tq_relay.py`。

## 文件地图

| 文件 | 角色 | 说明 |
|---|---|---|
| `tq_relay.py` | 服务端 | GUI + --serve 双模式；配置同目录自动生成 |
| `tests/selftest_qmt.py` | QMT 端 16 项自测 | GBK 编码，整段粘贴进 QMT 运行；改接口参数示例看这里 |
| `skills/tq-relay/` | ZCode skill | SKILL.md + `scripts/tq_client.py` 客户端 + `references/interfaces.md` 接口速查；整目录拷到 `~/.zcode/skills/` 即生效 |
| `README.md` | 完整使用文档 | 协议、配置表、接口速查、QMT 内嵌模板、已知坑 |
| `TQ转发器_配置.json` | 运行时配置（gitignored） | 首次运行自动生成；含 token |

## 报错速查

| 报错片段 | 根因 | 处理 |
|---|---|---|
| `{'error': 'token错误'}` | token 不对/为空 | 机器 A 配置文件或 GUI 查 token |
| ConnectionRefused | 转发器没运行/端口错/防火墙 | 机器 A 起服务；放行 17710 |
| 超时 | 重公式计算中 | 加大客户端 timeout；看机器 A 日志 |
| `result.Error`="资金账户未登录" | 通达信端无交易账户 | 登录资金账户或不用交易接口 |
| K线根数不符 | 分页 | 按年份分窗拼接 |
| GUI 打开即崩 | 依赖缺失/未定义名 | 跑 pyflakes；确认标准库导入齐全 |
