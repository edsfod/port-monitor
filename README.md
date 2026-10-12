# port-monitor —— 本机监听端口一览，并停止自己的后台工具

> 创建/重写：2026-09-24
> 边界：只记本工具的用法、说明来源与设计。各端口对应的系统组件本身不记；网页的配色、显示设置与服务外壳见本目录 `web-kit/`（web-kit 原是一个独立的项目，2026-10-12 停止维护，线上仓库已删除；这份 v1.0.0 的副本现在是本工具自己的一部分，来历见 `vendor.json`）。
> 仓库：https://github.com/edsfod/port-monitor 。许可证：MIT（见 `LICENSE`）。
> 失效判据：Windows PowerShell 的 `Get-NetTCPConnection` / `Get-NetUDPEndpoint` / CIM 进程与服务查询不再可用，或自建的网页工具不再用 web-kit 外壳（「自己的工具」的主要识别方式失效）时，本篇相应部分失效。

列出本机所有 TCP 监听端口与 UDP 端点：属于哪个进程、它在做什么（并注明这条说明从哪来）、是否局域网可访问。自己的后台工具（如在 `127.0.0.1:8765` 上无窗口运行的 clash-review 网页服务）可以在页面上停止；系统与第三方进程只显示，不提供结束。仅用 Python 标准库，不联网。

---

## 一、快速使用

### 下载与运行

1. 在 [Releases](https://github.com/edsfod/port-monitor/releases) 下载 `port-monitor-<版本>-win64.zip`，解压到任意位置。
2. 双击 `port-monitor.bat`，浏览器打开 `http://127.0.0.1:8766/`。
3. 包里带 python.org 官方的免安装版 Python（`python\`），不用另装。命令行用 `python\python.exe port_monitor.py …`（无窗口运行用 `python\pythonw.exe`）；下文的 `python` / `pythonw` 都指它（用源码时指你自己的 Python 3.8+）。
4. 设置在 `%APPDATA%\port-monitor\settings.json`（可选，样例见 `settings.example.json`），日志与显示设置默认值在 `%LOCALAPPDATA%\port-monitor\`。升级时把程序目录整个换成新版即可。想全部留在程序目录里，在程序目录放一个名为 `portable` 的空文件。

### 前置条件
- Python 3.8 以上（发布包自带）。只用标准库，无需装包。`port-monitor.bat` 用 `web-kit\find-python.ps1` 找解释器（注册表、py 启动器、常见安装目录、PATH），不写死路径；要指定就设环境变量 `TOOL_PYTHON`。
- 本目录自成一体，可以整个拷走单独用（见「可迁移」）。配色、显示设置、显示参数、心跳与服务外壳在 `web-kit/`，是随工具带的副本，不要在这里改。
- 可选的 `settings.json`（在设置目录里；格式见 `settings.example.json`）：`tool_dirs`、`known_ports`、`known_apps`，见第三节。
- 数据由 Windows PowerShell 5.1（`powershell.exe`，系统自带）采集。不需要管理员；以管理员运行时能多读到系统进程的路径与命令行。

### 网页界面
双击 `port-monitor.bat`（或 `pythonw port_monitor.py`）：在 `http://127.0.0.1:8766/` 后台启动本地服务（`pythonw`，不开控制台窗口）并打开浏览器；bat 启动后立即返回。已在运行时再双击只会打开浏览器。

- 停止：`pythonw port_monitor.py --stop`；或在页面「自己的工具」里对 8766 那一行点「停止」。
- 自动退出：页面开着时每 60 秒发一次心跳（`/api/ping`）；连续 30 分钟没有任何请求，服务自己退出（常量 `IDLE_MINUTES`，在 `port_monitor.py` 顶部）。
- 运行日志在数据目录的 `web.log`；启动失败（端口被占）弹系统对话框告知。

### 命令行
```powershell
# 打印采集结果（JSON）后退出，不起服务。用于核对说明表、排查采集问题
python port_monitor.py --json

# 换端口（默认 8766）、不开浏览器
pythonw port_monitor.py --port 8767 --no-browser
pythonw port_monitor.py --port 8767 --stop
```

### 页面
- **顶栏**：非管理员提示、浏览器缩放不是 100% 时提示 Ctrl+0、采集时间（鼠标停上去看显示参数）；「刷新」重新采集（约 5 秒，结果缓存 5 秒）；调节按钮打开「显示设置」；最右的按钮在同一对配色的深浅之间切换（深青↔青瓷，暖炭↔象牙）。
- **页头**：「说明」弹窗（来源、暴露范围、停止方式、读不到的字段、后台运行），一行统计：TCP 监听、UDP、自己的工具、局域网可访问的行数（最后一项非零时为琥珀色）。
- **筛选**：全部 / 自己的工具 / 局域网可访问 / TCP / UDP，各带行数，选中项实心填充；搜索框匹配端口、进程、地址、命令行、说明与服务名。
- **列表**：一行是「协议 + 端口 + 进程」，同一进程在多个地址上开同一端口（如 `0.0.0.0` 与 `::`）合成一行，地址逐个列出并各带「仅本机 / 局域网可访问」标签和网卡名。吸顶表头可点排序（端口、协议、进程、监听地址；再点一次反向）。「它在做什么」列显示优先级最高的一条说明，下面一行是来源标签、是否正常、另有几条来源；自己的工具带「自己的工具」标签。点一行展开（左侧铜色竖条）：全部说明（各注来源）、命令行、路径、启动时间、父进程、连到该端口的已建立连接数、所承载的服务、停止方式。
- **停止**：只在自己的工具的行上出现，点后先弹确认框，写明将用哪种方式停止；结果在右下角提示。
- **显示设置**（面板由 web-kit 提供）：配色（四套，见下）、英文字体、英文粗细（300–500）、灰字亮度（四档，每套配色各有自己的四档）。三层取值：当前值存在该浏览器的 localStorage（键 `pm-display`）；「设为默认」写 `var/ui_prefs.json`，浏览器没存过设置时与「恢复默认」都用它；「还原出厂」删掉该文件（出厂：深青、Segoe UI Variable、400、灰字默认）。后端对写入的值做白名单校验（取值表是 web-kit 的 `schemes.json`）。
- **窄窗口**：1024px 以下列表行改两行（协议并入端口下方），720px 以下顶栏换行、筛选可横向滚动；页面本身不出现横向滚动。

### 界面样式与配色
页面样式照 [clash-review](https://github.com/edsfod/clash-review) 的 `web/`（顶栏、按钮、分段控件、列表行、标签、说明弹窗），写在本工具自己的 `web/app.css`。配色、显示设置面板、本机显示参数检测与心跳来自本目录 `web-kit/`（`/kit/kit.css`、`/kit/kit.js`；与 clash-review 各带一份同样的副本）。配色四套，每套是一组完整的取值，由根元素 `data-scheme` 切换，页面样式只引用变量；取值只在 web-kit 的 `schemes.json`：

| 配色 | 深浅 | 来源 | 观感 |
|---|---|---|---|
| 深青（出厂） | 深 | 作者的界面风格笔记，深色（原「青铜」） | 冷调深蓝绿黑，青绿 + 铜 |
| 青瓷 | 浅 | 作者的界面风格笔记，浅色 | 冷灰青白，墨青 + 赭铜 |
| 暖炭 | 深 | `aoe2_balance\v5\app\tokens.css` 深色 | 暖近黑，珊瑚强调 |
| 象牙 | 浅 | `aoe2_balance\v5\app\tokens.css` 浅色 | 暖米白，墨字，珊瑚强调 |

v5 的取值怎么映射到变量名见本目录 `web-kit/README.md` 与 `web-kit/schemes.json`。

同日曾先后试过照 v5 的整套页面样式（页头、表格、个性化面板）做，使用者比较后定为 clash-review 的页面样式，v5 只取配色。

---

## 二、它解决什么问题

- 想知道本机开着哪些端口、各是谁、要不要管。`netstat -ano` 只给 PID，还要自己查进程、查服务、查这个端口是干什么的；svchost 更要查它承载了哪个服务。
- 自建工具用 `pythonw` 在后台运行，没有窗口，忘了停就一直占着端口。本页把它们标出来并提供停止，停的方式优先用工具自己的 `--stop`。
- 系统与第三方进程故意不提供结束：结束一个系统服务进程的后果本页判断不了。

---

## 三、数据来源与判断依据

### 采集
一次 `powershell -NoProfile -NonInteractive -EncodedCommand …`（脚本在 `port_monitor.py` 的 `_PS`，以 `-EncodedCommand` 传入以免命令行转义问题；子进程带 `CREATE_NO_WINDOW`，pythonw 下不闪窗口），输出 `ConvertTo-Json -Depth 4`：

| 内容 | 来源 |
|---|---|
| TCP 监听、每个进程每个本地端口上的已建立连接数 | `Get-NetTCPConnection -State Listen, Established`（一次取两种：该命令每调一次约 2 秒） |
| UDP 端点 | `Get-NetUDPEndpoint` |
| 进程名、路径、命令行、启动时间、父进程 | `Get-CimInstance Win32_Process` |
| 文件说明、公司 | 可执行文件的 `VersionInfo`；进程路径读不到而它是服务时，从服务的 `PathName` 取可执行文件 |
| 进程承载的服务 | `Get-CimInstance Win32_Service`（`ProcessId`、名称、显示名、描述、状态） |
| 地址属于哪块网卡 | `Get-NetIPAddress` 的 `InterfaceAlias` |

非管理员时，系统服务进程与以系统账户运行的程序（如 Clash Verge 内核 `verge-mihomo.exe`）的路径与命令行为空，页面显示「读不到（需要管理员权限）」。端口、进程名、启动时间、服务信息不受影响。顶栏的「以管理员身份重新启动」弹出 UAC 确认；确认后由管理员权限的新进程（`--takeover`：端口被占时最多等 10 秒）接替同一端口，旧进程退出，页面在新进程起来后自动刷新。UAC 没确认时页面提示「已取消」，服务照旧。

### 「它在做什么」
按下面的顺序各查一遍，查到的都列出、各注来源；表格里显示第一条。

1. **自己的工具**，两种认法，先后：
   - **web-kit 网页服务**：Python 进程在本机回环（或全部网卡）上的 TCP 监听，向它发 `GET /api/ping`（0.5 秒超时、并发），回答里的 `pid` 等于监听进程、且带 `header`（写操作要求的请求头名）的，就是带 web-kit 外壳的自建服务。名字取回答里的 `app`。不需要任何设置，工具放在哪都认得出。同一进程的其它端口一并算。
   - **设置里的目录**：命令行或路径位于 `settings.json` 的 `tool_dirs` 之一下的进程。名字取脚本所在目录名。本机设为 `Config\`，照旧认出本仓库里不带 web-kit 的脚本。
   用途取自命令行里那个 `.py` 脚本文档字符串首行「——」后面的一句（如 clash-review 的「clash_review 的本地网页界面」）。
2. **内置程序表 / 内置端口表**：`port_monitor.py` 顶部「内置说明表」一节的三个表，要补充只改那里：
   - `KNOWN_APPS`：按进程名。可给该程序各端口的具体用途（如 `verge-mihomo.exe` 的 7897 = mixed-port 代理入口、53 = 内核 DNS、9090/9097 = 控制接口）。同一端口号在不同程序上用途不同（如 53），所以程序表对该端口有专门说明时排在端口表前面；只有程序的泛泛说明时（如 System 的 445）排在端口表后面。
   - `KNOWN_PORTS`：按端口号，每条可限定协议、进程名、服务名（如 UDP 53 在承载 `SharedAccess` 的 svchost 上 = ICS 给 Hyper-V / WSL 虚拟网卡做 DNS 转发）。每条带「是否正常」。
   - `KNOWN_RANGES`：端口段。TCP 49664–65535 上的 lsass / wininit / services / spoolsv / svchost = RPC 动态端口，正常；其余 49152–65535 = 动态端口。
3. **Windows 服务**：该进程承载的服务的显示名与描述首句。svchost 主要靠这一条。
4. **文件信息**：可执行文件的「文件说明 · 公司」。
5. 以上都没有：「看不出（进程 X，路径 Y）」。

### 谁能连进来
- `127.x.x.x`、`::1` → 仅本机。
- `0.0.0.0`、`::`（所有网卡）、某块网卡的地址（含 `fe80::` 链路本地）→ 局域网可访问，琥珀色标签，后面注明网卡名。`vEthernet (…)` 是 Hyper-V / WSL 的虚拟网卡，只有本机的虚拟机能连到。
- **不查防火墙规则**：标为局域网可访问的端口，防火墙仍可能挡住外来连接。

### 停止
只对自己的工具开放，后端在执行前重新采集一次，确认该 PID 此刻仍在监听该端口且仍认得出是自己的工具（防 PID 被别的进程复用），否则拒绝。
1. 目标就是本服务自己：直接退出。
2. web-kit 网页服务：带它在 `/api/ping` 里给的请求头 `POST /api/shutdown`，等进程退出，最多 8 秒。
3. 其它（按目录认出的）脚本里有 `"--stop"` 参数（按源码文本判断）：用目标进程自己的解释器（`python.exe` 换成同目录的 `pythonw.exe`）运行 `<脚本> --stop`，脚本也接受 `--port` 时带上该行的端口。之后等进程退出，最多 8 秒。clash-review 的 `--stop` 即 `POST /api/shutdown` 带 `X-Clash-Review: 1`。
4. 不支持以上两种，或 8 秒内没退出：`taskkill /PID <n> /T /F`。要 `/F`：pythonw 进程没有窗口，不带 `/F` 的 taskkill 结束不了它。

### 安全
服务只绑定 `127.0.0.1`（独占绑定，不开 `SO_REUSEADDR`），校验 `Host` 头；写操作（停止、设为默认、`/api/shutdown`）要求请求头 `X-Port-Monitor: 1` 并校验 `Origin`，别的网页无法借浏览器让它结束进程。

---

## 四、文件与数据

**设置与数据放在哪**（web-kit 的 `tooldirs.py`）：设置（`settings.json`）在 `%APPDATA%\port-monitor\`，运行数据在 `%LOCALAPPDATA%\port-monitor\`，程序目录里只有发布的内容，升级时整个换掉。工具目录里放一个名为 `portable` 的文件（内容不限）就是便携模式：设置在工具目录，数据在工具目录的 `var/`。本篇其它地方说的 `var/` 都指数据目录。

| 文件 | 作用 |
|---|---|
| `port_monitor.py` | 采集、判断与业务接口（`/api/ports`、`/api/stop`、`/api/elevate`）；服务外壳（后台运行日志、失败对话框、单实例、`--stop`、空闲退出、Host / 自定义头 / Origin 校验、`/api/prefs`、`/api/display`、`/api/ping`、`/api/shutdown`、`/kit/*`）来自 `web-kit/webkit.py`；不在源码目录生成 `__pycache__` |
| `web/index.html` / `web/app.css` / `web/app.js` | 单页面（无构建步骤），只写页面内容与样式；配色与显示设置来自 web-kit，见第一节「界面样式与配色」 |
| `port-monitor.bat` | 用 `web-kit\find-python.ps1` 找到 `pythonw`，在后台启动并立即返回（纯 ASCII），参数原样传给脚本 |
| `web-kit/` | 网页外壳。web-kit v1.0.0 的完整副本，现在是本工具自己的一部分（web-kit 原是一个独立的项目，2026-10-12 停止维护，线上仓库已删除） |
| `vendor.json` | 副本的来历：来源网址、标签、提交、tree 哈希（SWHID 格式）。核对与更新见「可迁移」 |
| `settings.example.json` | 设置的格式样例。本机的设置在 `settings.json`（不随工具给别人） |

运行产物（`var/`，任何时候可整体删除）：

| 文件 | 作用 |
|---|---|
| `var/web.log` | 后台运行时的输出：启动、停止、空闲退出、接口出错 |
| `var/ui_prefs.json` | 显示设置的默认值（「设为默认」写入；删掉即回到出厂值） |

---

## 五、注意事项

- 采集一次约 5–6 秒，大部分花在 `Get-NetTCPConnection` 上。
- 行数随时间变化：UDP 的动态端口（49152 以上）由程序临时申请，每次刷新都可能不同。
- 不带 web-kit 的工具靠命令行里的路径认（`tool_dirs`）。用 `python -c "…"` 之类方式启动、命令行不含脚本路径的进程，认不出来，也就不提供停止。
- 以管理员运行 `port-monitor.bat` 能读到更多路径与命令行，但页面上的「停止」也随之以管理员权限执行；范围不变，仍只限自己的工具。
- 说明表是手写的，只覆盖本机见过的与常见的端口；遇到「看不出」的，查清后补进 `KNOWN_PORTS` / `KNOWN_APPS`（通用的）或 `settings.json` 的 `known_ports` / `known_apps`（只跟自己有关的；排在内置说明前面，程序说明同名时覆盖内置）。

---

## 可迁移

目标：以后给别人用，做成独立软件（exe）或插件、增强扩展，形式未定。约束：目录能单独拿走，不读目录以外的文件，不写死本机路径与个人常量。

缺口与处理（2026-09-24 查，同日处理）：

| 缺口 | 处理 | 状态 |
|---|---|---|
| 引用工具目录以外的 web-kit | 本目录带一份副本 `web-kit/`，只导入自己那份；来历记在 `vendor.json` | 已处理 |
| 「本仓库工具」的识别写死了本仓库的目录结构 | 改为两种认法：web-kit 网页服务按 `/api/ping` 认（无需设置）；其余按 `settings.json` 的 `tool_dirs` 认。停止 web-kit 服务直接发 `/api/shutdown` | 已处理 |
| 说明表只覆盖本机见过的端口与程序 | 允许使用者在 `settings.json` 的 `known_ports` / `known_apps` 追加 | 追加已可用；发布前补常见项未做 |
| Python 路径写死 | `port-monitor.bat` 改用 `web-kit\find-python.ps1` 查找；打包成 exe 后不再需要 | 已处理 |
| 只有中文界面 | 视发布对象再定 | 未做 |

整目录拷到别处单独运行已试过（2026-09-24，去掉 `var/` 与 `settings.json`）：bat 找到解释器、服务起得来、`/kit/*` 从自己的副本送出、认得出 clash-review 与自己、`--stop` 正常。

副本 `web-kit/` 不引用任何本地工作目录。web-kit 原是一个独立的项目，2026-10-12 停止维护，线上仓库已删除，所以它不再有新版，也不再更新；`vendor.json` 里的 `source` 只作来历的记录：

- 核对副本没被改过：`git rev-parse HEAD:web-kit` 应等于 `vendor.json` 里 `tree` 的哈希部分，`git status web-kit` 应无改动。
- 个人文件不进仓库（`.gitignore`）：`settings.json`、`var/`、`portable`。平常它们也不在程序目录里（见第四节「设置与数据放在哪」）。
- 发布：打 `v*` 标签时 GitHub Actions（`.github/workflows/release.yml`）用 `web-kit/pack.py` 打成带免安装版 Python 的 zip 挂到 Releases；只在公开项目里运行。

---

## 六、否定结论

- 照 aoe2_balance v5 的整套页面样式做不行：使用者比较后认为 clash-review 那种页面样式更合适，v5 只取配色（2026-09-24）。
- 给系统与第三方进程也提供「结束」不行：误杀系统服务的代价远大于便利，只对自己的工具开放，且先请工具自己退出。
- 结束 pythonw 进程不能只用 `taskkill /PID`：没有窗口的进程收不到关闭消息，要 `/F`；只在工具没有 `--stop` 或 8 秒内没退出时才用。
- 用 Python `http.server` 的默认绑定不行：Windows 上默认的 `SO_REUSEADDR` 允许第二个进程绑定同一端口，改为独占（`SO_EXCLUSIVEADDRUSE`）。
- 按「命令行位于本仓库下、工具名取自 `topics\<主题>\tools\<工具名>\`」认自己的工具不行（以后给别人用）：换一台机器、换一种放法就认不出；改为 web-kit 的 `/api/ping` 标记加可设置的目录。
- 每个「IP + 端口」各列一行不行：`0.0.0.0` 与 `::`、每块网卡各自的 NetBIOS / SSDP 会让列表翻倍到约 90 行；按协议 + 端口 + 进程合并，地址逐个列出。

---

## 修订记录

- 2026-10-12：web-kit（原是一个独立的项目）停止维护，线上仓库已删除。本篇里指向那个仓库的链接、查新版和更新副本的两条命令去掉；`web-kit/` 这份副本原样留着，当作本工具自己的一部分。程序没有改。
- 2026-09-24（v1.0.0）：首次公开发布。此前在作者的私有工作区里开发，历史不随公开仓库发布。
