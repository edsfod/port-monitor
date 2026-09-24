#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
port_monitor —— 本机监听端口一览，并可停止自己的后台工具（仅标准库）

启动一个只监听 127.0.0.1 的 HTTP 服务，提供 web/ 下的单页面与 /api/*，并打开浏览器。
页面列出本机所有 TCP 监听与 UDP 端点、属于哪个进程、它在做什么、是否局域网可访问；
只有自己的工具提供「停止」，系统与第三方进程只显示。「自己的工具」有两种认法：
带 web-kit 外壳的本地网页服务（/api/ping 回的 PID 与监听进程相同），以及命令行或路径位于 settings.json
的 tool_dirs 下的进程。

数据：一次 PowerShell 调用（Get-NetTCPConnection / Get-NetUDPEndpoint / Win32_Process / Win32_Service /
Get-NetIPAddress / 可执行文件版本信息），结果缓存 CACHE_SECONDS 秒。非管理员时部分进程的路径与命令行读不到。

安全：只绑定 127.0.0.1；校验 Host 头（防 DNS 重绑定）；写操作要求自定义头 X-Port-Monitor: 1
（跨站页面带不了这个头而不触发预检，本服务不应答预检），并校验 Origin。

服务外壳（后台运行的日志与失败对话框、单实例、--stop、空闲退出、安全校验、/api/display、/api/prefs、
配色与显示设置 /kit/*）来自本目录的 web-kit/（随工具带的副本，见本工具 README）。本文件只写采集与业务接口。

用法：pythonw port_monitor.py [--port 8766] [--no-browser] [--stop] [--json]
已有实例在同一端口运行时，只打开浏览器后退出。--stop 停止正在运行的实例；--json 打印采集结果后退出（不起服务）。

在后台运行、不开控制台窗口（ui-style 第 3 节「后台运行」）：port-monitor.bat 用 pythonw 启动后立即返回。
没有控制台时，输出写到 var/web.log；启动失败（端口被占）弹系统对话框告知。
页面每 60 秒发一次 /api/ping；连续 IDLE_MINUTES 分钟没有任何请求，服务自动退出。
"""
import os, sys, re, json, time, base64, argparse, threading, subprocess, webbrowser, datetime, urllib.request
import concurrent.futures as cf

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "web-kit"))      # 随本工具带的副本（来历见 vendor.json）
import webkit, tooldirs
WEB = os.path.join(HERE, "web")
# 设置在 %APPDATA%\port-monitor\，运行数据（日志、显示设置默认值）在 %LOCALAPPDATA%\port-monitor\；
# 工具目录里有 portable 文件时都在工具目录（数据在 var/）。见 web-kit/tooldirs.py。
CONF_DIR, VAR = tooldirs.dirs(HERE, "port-monitor")
SIGNATURE = "port-monitor"
DEFAULT_PORT = 8766
IDLE_MINUTES = 30          # 连续这么久没有任何请求（页面开着时每 60 秒一次心跳），服务自动退出
CACHE_SECONDS = 5          # 采集结果缓存；页面的「刷新」强制重采
CREATE_NO_WINDOW = 0x08000000
NO_ADMIN = "读不到（需要管理员权限）"


ApiError = webkit.ApiError


# ---------------- 使用者的设置（settings.json，可选；格式见 settings.example.json）----------------
#   tool_dirs    自己的工具所在目录：命令行或路径在这些目录下的进程算「自己的工具」，提供停止
#   known_ports  追加的端口说明，格式同下面的 KNOWN_PORTS（端口号写成字符串，procs / svcs 写成列表），排在内置的前面
#   known_apps   追加或覆盖的程序说明，格式同 KNOWN_APPS（ports 的端口号写成字符串）
SETTINGS = os.path.join(CONF_DIR, "settings.json")

def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f: d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        webkit.log(f"settings.json 读不了，按没有设置处理：{e}")
        return {}


# ============================================================================
# 内置说明表：常见端口与常见程序。要补充就在这里加，别处不用改。
#
# KNOWN_PORTS：端口号 → 若干条说明，按顺序取第一条条件满足的。每条可带：
#   proto  "tcp" / "udp"，不写则两者都算
#   procs  进程名（小写）集合，只在这些进程上成立
#   svcs   服务名集合，只在该进程承载了其中某个服务时成立
#   text   它是什么；note  是否正常、要不要管
# KNOWN_RANGES：端口段的说明，字段同上，另有 lo / hi。
# KNOWN_APPS：进程名（小写）→ 程序说明；ports 给出该程序各端口的具体用途，
#   other 是该程序其它端口的说法。程序对该端口有专门说明（ports 里有）时排在端口表前面
#   （同一端口号，不同程序用途不同，如 53）；否则端口表在前、程序的泛泛说明在后。
# ============================================================================
_SYS_RPC = {"lsass.exe", "wininit.exe", "services.exe", "spoolsv.exe", "svchost.exe"}

KNOWN_PORTS = {
    53:   [{"svcs": {"SharedAccess"}, "text": "DNS 转发：Internet 连接共享（ICS）给 Hyper-V / WSL 的虚拟网卡提供 DNS",
            "note": "装了 Hyper-V 或 WSL 时正常"},
           {"text": "DNS 服务", "note": "普通电脑上一般只有代理内核或 DNS 服务器才监听"}],
    67:   [{"proto": "udp", "svcs": {"SharedAccess"}, "text": "DHCP 服务端：ICS 给虚拟网卡上的虚拟机分配地址", "note": "装了 Hyper-V 或 WSL 时正常"},
           {"proto": "udp", "text": "DHCP 服务端", "note": "普通电脑上少见，留意是谁"}],
    68:   [{"proto": "udp", "svcs": {"SharedAccess"}, "text": "DHCP（ICS 的虚拟网络）", "note": "装了 Hyper-V 或 WSL 时正常"},
           {"proto": "udp", "text": "DHCP 客户端", "note": "正常"}],
    123:  [{"proto": "udp", "text": "NTP 时间同步（W32Time）", "note": "正常"}],
    135:  [{"proto": "tcp", "text": "RPC 终结点映射（RpcEptMapper）：告诉别的程序某个 RPC 服务在哪个端口", "note": "Windows 常驻，正常"}],
    137:  [{"proto": "udp", "text": "NetBIOS 名称服务", "note": "Windows 自带，每块网卡一份，正常；不用旧式局域网共享可在网卡属性里关掉 NetBIOS"}],
    138:  [{"proto": "udp", "text": "NetBIOS 数据报服务", "note": "Windows 自带，正常"}],
    139:  [{"proto": "tcp", "text": "NetBIOS 会话服务（旧版 SMB 文件共享）", "note": "Windows 自带，每块网卡一份，正常"}],
    445:  [{"proto": "tcp", "text": "SMB 文件共享（共享文件夹、打印机）", "note": "Windows 自带，正常；是否真能从外面连到取决于防火墙"}],
    500:  [{"proto": "udp", "text": "IKE（IPsec / VPN 协商）", "note": "用 VPN 时正常"}],
    1900: [{"proto": "udp", "text": "SSDP：UPnP 设备发现（找局域网里的电视、打印机、路由器）", "note": "Windows 自带，正常"}],
    2177: [{"proto": "udp", "text": "qWave：音视频传输质量服务", "note": "Windows 自带，正常"}],
    2179: [{"proto": "tcp", "text": "Hyper-V 虚拟机连接（vmms，「虚拟机连接」窗口用它连虚拟机控制台）", "note": "装了 Hyper-V 时正常"}],
    3389: [{"text": "远程桌面（RDP）", "note": "开了远程桌面才有；不用就关掉"}],
    3702: [{"proto": "udp", "text": "WS-Discovery：网络设备发现", "note": "Windows 自带，正常"}],
    4500: [{"proto": "udp", "text": "IPsec NAT 穿透（VPN）", "note": "用 VPN 时正常"}],
    5040: [{"proto": "tcp", "text": "CDPSvc（连接设备平台）：跨设备体验、附近共享", "note": "Windows 自带，正常"}],
    5050: [{"proto": "udp", "procs": {"svchost.exe"}, "text": "CDPSvc（连接设备平台）的 UDP 端口", "note": "Windows 自带，正常"}],
    5353: [{"proto": "udp", "text": "mDNS：局域网内按名字找设备（.local）", "note": "Windows 与浏览器都会用，正常"}],
    5355: [{"proto": "udp", "text": "LLMNR：局域网名字解析（DNS 查不到时的后备）", "note": "Windows 自带，正常"}],
    5357: [{"proto": "tcp", "text": "WSDAPI：网络设备发现（打印机、扫描仪）", "note": "Windows 自带，正常"}],
    7680: [{"proto": "tcp", "text": "传递优化（DoSvc）：Windows 更新在局域网内互相分发", "note": "Windows 自带，正常；可在「传递优化」设置里关掉局域网分享"}],
}

KNOWN_RANGES = [
    {"lo": 49664, "hi": 65535, "proto": "tcp", "procs": _SYS_RPC,
     "text": "RPC 动态端口：系统服务通过 135 登记后在这里接受远程调用",
     "note": "lsass / wininit / services / spoolsv / svchost 在这一段监听是 Windows 的常态，正常"},
    {"lo": 49152, "hi": 65535,
     "text": "动态端口：程序临时向系统要的端口，号码每次启动都可能变",
     "note": "用途看是哪个程序"},
]

KNOWN_APPS = {
    "verge-mihomo.exe": {"what": "Clash Verge 内核（mihomo）", "note": "本机代理，正常",
                         "ports": {7897: "mixed-port：代理入口（HTTP 与 SOCKS5 共用），系统代理指向这里",
                                   53: "内核 DNS（dns.listen），给 TUN / 虚拟网卡做解析",
                                   9090: "控制接口（external-controller），Clash Verge 界面用它管理内核",
                                   9097: "控制接口（external-controller），Clash Verge 界面用它管理内核"},
                         "other": "Clash Verge 内核的其它端口（见 Clash Verge 的端口设置）"},
    "clash-verge.exe": {"what": "Clash Verge 界面程序", "note": "正常",
                        "other": "界面程序内部用的本机端口"},
    "clash-verge-service.exe": {"what": "Clash Verge 服务模式的后台服务（以系统权限启动内核）", "note": "正常"},
    "esrv.exe": {"what": "Intel System Usage Report（SUR）：随 Intel 驱动与支持助手安装的使用情况采集",
                 "note": "只在本机回环上；不想要可卸载 Intel 驱动与支持助手相关组件"},
    "esrv_svc.exe": {"what": "Intel System Usage Report（SUR）的服务进程（Energy Server Service）",
                     "note": "只在本机回环上；不想要可卸载 Intel 驱动与支持助手相关组件"},
    "vmms.exe": {"what": "Hyper-V 虚拟机管理服务（vmms）", "note": "装了 Hyper-V 时正常"},
    "system": {"what": "Windows 内核（System）：SMB、NetBIOS、HTTP.sys 等内核态网络服务", "note": "正常"},
    "lsass.exe": {"what": "本地安全机构（lsass）", "note": "Windows 核心进程"},
    "wininit.exe": {"what": "Windows 启动初始化进程（wininit）", "note": "Windows 核心进程"},
    "services.exe": {"what": "服务控制管理器（services）", "note": "Windows 核心进程"},
    "spoolsv.exe": {"what": "打印后台处理程序（Spooler）", "note": "Windows 自带"},
    "msedge.exe": {"what": "Microsoft Edge 浏览器", "note": "正常",
                   "ports": {5353: "网页用的 mDNS（局域网设备发现、WebRTC 隐藏本机地址）"}},
    "chrome.exe": {"what": "Google Chrome 浏览器", "note": "正常",
                   "ports": {5353: "网页用的 mDNS（局域网设备发现、WebRTC 隐藏本机地址）"}},
    "code.exe": {"what": "Visual Studio Code", "note": "编辑器或其扩展开的端口"},
    "node.exe": {"what": "Node.js 程序", "note": "看命令行判断是哪个项目"},
}

def _user_tables(st):
    """settings.json 的 known_ports / known_apps 转成与内置表相同的形状。"""
    ports = {}
    for k, entries in (st.get("known_ports") or {}).items():
        try: port = int(k)
        except ValueError: continue
        ports[port] = [dict(e, **{x: set(e[x]) for x in ("procs", "svcs") if e.get(x)}) for e in entries if isinstance(e, dict)]
    apps = {}
    for name, a in (st.get("known_apps") or {}).items():
        if isinstance(a, dict):
            apps[name.lower()] = dict(a, ports={int(p): t for p, t in (a.get("ports") or {}).items() if str(p).isdigit()})
    return ports, apps
# ============================================================================


# ---------------- 采集（一次 PowerShell 调用）----------------
_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$conn = @(Get-NetTCPConnection -State Listen, Established)   # 一次取两种状态：Get-NetTCPConnection 每次调用约 2 秒
$tcp = @($conn | Where-Object { $_.State -eq 'Listen' } | ForEach-Object { [pscustomobject]@{ a = [string]$_.LocalAddress; p = [int]$_.LocalPort; id = [int]$_.OwningProcess } })
$est = @($conn | Where-Object { $_.State -eq 'Established' } | Group-Object OwningProcess, LocalPort | ForEach-Object { [pscustomobject]@{ k = $_.Name; n = $_.Count } })
$udp = @(Get-NetUDPEndpoint | ForEach-Object { [pscustomobject]@{ a = [string]$_.LocalAddress; p = [int]$_.LocalPort; id = [int]$_.OwningProcess } })
$ids = @(($tcp + $udp) | ForEach-Object { $_.id } | Sort-Object -Unique)
$svc = @(Get-CimInstance Win32_Service -Filter 'ProcessId <> 0' -Property Name, DisplayName, Description, State, PathName, ProcessId | Where-Object { $_.ProcessId -and ($ids -contains [int]$_.ProcessId) } | ForEach-Object {
  [pscustomobject]@{ id = [int]$_.ProcessId; name = $_.Name; display = $_.DisplayName; desc = $_.Description; state = $_.State; bin = $_.PathName } })
$proc = @(Get-CimInstance Win32_Process | Where-Object { $ids -contains [int]$_.ProcessId } | ForEach-Object {
  $path = $_.ExecutablePath; $vi = $null
  if ($path) { $vi = (Get-Item -LiteralPath $path).VersionInfo }
  $start = $null; if ($_.CreationDate) { $start = $_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss') }
  [pscustomobject]@{ id = [int]$_.ProcessId; name = $_.Name; path = $path; cmd = $_.CommandLine; start = $start;
    ppid = [int]$_.ParentProcessId; company = $vi.CompanyName; desc = $vi.FileDescription } })
$bins = @{}
foreach ($s in $svc) {   # 路径读不到的服务进程：从服务的 PathName 取可执行文件，读它的版本信息
  if ($s.bin -and -not $bins.ContainsKey($s.id)) {
    $b = $s.bin.Trim(); if ($b.StartsWith('"')) { $b = $b.Substring(1, $b.IndexOf('"', 1) - 1) } else { $b = ($b -split ' ')[0] }
    $b = [Environment]::ExpandEnvironmentVariables($b)
    $vi = (Get-Item -LiteralPath $b).VersionInfo
    $bins[$s.id] = [pscustomobject]@{ id = $s.id; path = $b; company = $vi.CompanyName; desc = $vi.FileDescription } } }
$ip = @(Get-NetIPAddress | ForEach-Object { [pscustomobject]@{ a = [string]$_.IPAddress; alias = $_.InterfaceAlias } })
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
ConvertTo-Json -Depth 4 -Compress -InputObject @{ tcp = $tcp; est = $est; udp = $udp; svc = $svc; proc = $proc; bins = @($bins.Values); ip = $ip; admin = $admin }
"""

def run_ps():
    enc = base64.b64encode(_PS.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=60, creationflags=CREATE_NO_WINDOW)
    out = r.stdout.decode("utf-8", "replace").strip().lstrip("﻿")
    if not out:
        raise RuntimeError("PowerShell 没有输出：" + r.stderr.decode("utf-8", "replace")[:300])
    return json.loads(out)


# ---------------- 判断：暴露范围 ----------------
def exposure(addr):
    a = addr.split("%")[0].lower()
    if a.startswith("127.") or a == "::1":
        return "local"
    return "lan"          # 0.0.0.0 / :: / 具体网卡地址（含 fe80:: 链路本地）

def addr_note(addr, aliases):
    a = addr.split("%")[0].lower()
    if a in ("0.0.0.0", "::"):
        return "所有网卡"
    if a.startswith("127.") or a == "::1":
        return "本机回环"
    al = aliases.get(a)
    if a.startswith("fe80:"):
        return "链路本地" + (f" · {al}" if al else "")
    return al or ""


# ---------------- 判断：自己的工具 ----------------
def _norm_dir(d):
    return os.path.normpath(os.path.expandvars(d)).lower().rstrip("\\") + "\\"

def _scripts_in(cmd):
    """命令行里的 .py / .pyw（带引号或不带都认）。"""
    for m in re.finditer(r'"([^"]+)"|(\S+)', cmd or ""):
        tok = (m.group(1) or m.group(2)).replace("/", "\\")
        if tok.lower().endswith((".py", ".pyw")):
            yield tok

def _doc_title(script):
    """脚本文档字符串首行里「——」之后的一句，去掉末尾括注：clash_review_web —— clash_review 的本地网页界面（仅标准库）。"""
    try:
        with open(script, encoding="utf-8") as f:
            head = f.read(4000)
    except OSError:
        return ""
    m = re.search(r'"""\s*\n?\s*[^\n]*?——\s*([^\n]+)', head)
    return re.sub(r"（[^（）]*）\s*$", "", m.group(1)).strip() if m else ""

def _tool_info(script, name, where, read_src=True):
    title = _doc_title(script) if script else ""
    src = ""
    if script and read_src:
        try:
            with open(script, encoding="utf-8") as f: src = f.read()
        except OSError: src = ""
    return {"tool": name, "where": where, "script": script, "label": name + (f"：{title}" if title else ""),
            "graceful": bool(script and '"--stop"' in src), "takes_port": bool(script and '"--port"' in src), "kit": None}

def own_by_dirs(p, tool_dirs):
    """进程的命令行或路径位于 settings.json 的 tool_dirs 之一下 → 工具信息，否则 None。"""
    cmd = p.get("cmd") or ""; path = p.get("path") or ""
    hay = (cmd + " " + path).replace("/", "\\").lower()
    for d in tool_dirs:
        nd = _norm_dir(d)
        if nd not in hay: continue
        script = next((t for t in _scripts_in(cmd) if t.lower().startswith(nd)), None)
        name = os.path.basename(os.path.dirname(script)) if script else (os.path.basename(path) or "自己的程序")
        return _tool_info(script, name, "位于 " + os.path.normpath(d))
    return None

def _ping(port):
    try:
        with webkit._NOPROXY.open(urllib.request.Request(f"http://127.0.0.1:{port}/api/ping"), timeout=0.5) as r:
            return json.loads(r.read(4096).decode("utf-8"))
    except Exception:
        return None

def own_by_kit(candidates):
    """带 web-kit 外壳的本地网页服务：/api/ping 回的 PID 与监听进程相同，且带写操作的请求头名（停止要用）。
    candidates：[(port, pid, 进程信息)]，只问 Python 进程在本机回环或全部网卡上的 TCP 监听。返回 {(port, pid): 工具信息}。"""
    out = {}
    if not candidates: return out
    with cf.ThreadPoolExecutor(max_workers=min(8, len(candidates))) as ex:
        for (port, pid, p), d in zip(candidates, ex.map(lambda c: _ping(c[0]), candidates)):
            if not isinstance(d, dict) or d.get("pid") != pid or not d.get("header") or not d.get("app"): continue
            script = next(_scripts_in((p or {}).get("cmd")), None)
            info = _tool_info(script, str(d["app"]), "web-kit 网页服务", read_src=False)
            info.update(graceful=True, kit={"port": port, "header": str(d["header"])})
            out[(port, pid)] = info
    return out


# ---------------- 判断：它在做什么（按优先级，每条注明来源）----------------
def _match(entry, proto, pname, svcs):
    if entry.get("proto") and entry["proto"] != proto: return False
    if entry.get("procs") and pname not in entry["procs"]: return False
    if entry.get("svcs") and not (entry["svcs"] & svcs): return False
    return True

def explain(proto, port, pname, pid, proc, svcs, bin_info, own, known_ports, known_apps):
    lines = []
    if own:
        lines.append({"src": "自己的工具", "text": f"{own['label']}（{own['where']}）", "note": "可在本页停止"})
    # 程序表对这个端口有专门说明时排在端口表前面（如 mihomo 的 53）；只有程序的泛泛说明时排在后面（如 System 的 445）
    app = known_apps.get(pname); app_line = port_line = None; app_specific = False
    if app:
        spec = (app.get("ports") or {}).get(port)
        app_specific = bool(spec)
        spec = spec or app.get("other")
        app_line = {"src": "内置程序表", "text": app["what"] + (f"：{spec}" if spec else ""), "note": app.get("note", "")}
    names = {s["name"] for s in svcs}
    for e in known_ports.get(port, []):
        if _match(e, proto, pname, names):
            port_line = {"src": "内置端口表", "text": e["text"], "note": e.get("note", "")}; break
    else:
        for e in KNOWN_RANGES:
            if e["lo"] <= port <= e["hi"] and _match(e, proto, pname, names):
                port_line = {"src": "内置端口表", "text": e["text"], "note": e.get("note", "")}; break
    lines += [x for x in ((app_line, port_line) if app_specific else (port_line, app_line)) if x]
    for s in svcs:
        desc = (s.get("desc") or "").strip()
        first = re.split(r"(?<=[.。])\s", desc, maxsplit=1)[0] if desc else ""
        lines.append({"src": "Windows 服务", "text": f"{s.get('display') or s['name']}（{s['name']}）" + (f"：{first}" if first else ""),
                      "note": ""})
    company = (proc or {}).get("company") or (bin_info or {}).get("company")
    fdesc = (proc or {}).get("desc") or (bin_info or {}).get("desc")
    if company or fdesc:
        lines.append({"src": "文件信息", "text": " · ".join(x for x in (fdesc, company) if x), "note": ""})
    if not lines:
        path = (proc or {}).get("path") or (bin_info or {}).get("path") or NO_ADMIN
        lines.append({"src": "看不出", "text": f"看不出（进程 {pname or '?'}，路径 {path}）", "note": ""})
    return lines


# ---------------- 组装 ----------------
def collect():
    raw = run_ps()
    L = lambda k: raw.get(k) or []
    procs = {p["id"]: p for p in L("proc")}
    bins = {b["id"]: b for b in L("bins")}
    svcs = {}
    for s in L("svc"):
        svcs.setdefault(s["id"], []).append(s)
    aliases = {i["a"].split("%")[0].lower(): i.get("alias") or "" for i in L("ip")}
    est = {}
    for e in L("est"):
        try:
            pid_s, port_s = [x.strip() for x in e["k"].split(",")]
            est[(int(pid_s), int(port_s))] = e["n"]
        except (ValueError, KeyError):
            pass
    admin = bool(raw.get("admin"))
    st = load_settings(); tool_dirs = [d for d in st.get("tool_dirs") or [] if isinstance(d, str) and d.strip()]
    up, ua = _user_tables(st)
    known_ports = {k: up.get(k, []) + v for k, v in KNOWN_PORTS.items()}
    known_ports.update({k: v for k, v in up.items() if k not in KNOWN_PORTS})
    known_apps = {**KNOWN_APPS, **ua}

    groups = {}
    for proto in ("tcp", "udp"):
        for ep in L(proto):
            groups.setdefault((proto, ep["p"], ep["id"]), []).append(ep["a"])

    kit_cands = [(port, pid, procs.get(pid)) for (proto, port, pid), addrs in groups.items()
                 if proto == "tcp" and ((procs.get(pid) or {}).get("name") or "").lower().startswith("python")
                 and any(exposure(a) == "local" or a in ("0.0.0.0", "::") for a in addrs)]
    kit_own = own_by_kit(kit_cands)

    rows = []
    for (proto, port, pid), addrs in groups.items():
        p = procs.get(pid)
        pname = (p or {}).get("name") or ("System" if pid == 4 else "")
        if pid == 0: pname = pname or "System Idle Process"
        sv = sorted(svcs.get(pid, []), key=lambda s: s["name"])
        own = kit_own.get((port, pid)) if proto == "tcp" else None
        if not own:   # 同一进程的其它端口（如 UDP）也认
            own = next((v for (kp, kpid), v in kit_own.items() if kpid == pid), None)
        if not own and p and tool_dirs: own = own_by_dirs(p, tool_dirs)
        addr_rows = []
        for a in sorted(set(addrs), key=lambda a: (":" in a, a)):
            addr_rows.append({"addr": a, "scope": exposure(a), "note": addr_note(a, aliases)})
        lan = any(x["scope"] == "lan" for x in addr_rows)
        path = (p or {}).get("path") or ((bins.get(pid) or {}).get("path") and f"{bins[pid]['path']}（取自服务配置）")
        rows.append({
            "key": f"{proto}:{port}:{pid}", "proto": proto, "port": port, "pid": pid, "name": pname or "?",
            "addrs": addr_rows, "exposure": "lan" if lan else "local",
            "own": own, "stoppable": bool(own),
            "est": est.get((pid, port), 0) if proto == "tcp" else None,
            "path": path or (None if pid in (0, 4) else NO_ADMIN),
            "cmd": (p or {}).get("cmd") or (None if pid in (0, 4) else NO_ADMIN),
            "start": (p or {}).get("start") or (None if pid in (0, 4) else NO_ADMIN),
            "ppid": (p or {}).get("ppid"),
            "services": [{"name": s["name"], "display": s.get("display"), "state": s.get("state"),
                          "desc": s.get("desc")} for s in sv],
            "explain": explain(proto, port, pname.lower(), pid, p, sv, bins.get(pid), own, known_ports, known_apps),
        })
    rows.sort(key=lambda r: (r["port"], r["proto"], r["pid"]))
    return {"rows": rows, "admin": admin, "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "self_pid": os.getpid(), "idle_minutes": IDLE_MINUTES,
            "summary": {"tcp": sum(r["proto"] == "tcp" for r in rows), "udp": sum(r["proto"] == "udp" for r in rows),
                        "own": sum(bool(r["own"]) for r in rows), "lan": sum(r["exposure"] == "lan" for r in rows)}}

_CACHE = {"t": 0.0, "data": None}
_CACHE_LOCK = threading.Lock()

def cached(fresh=False):
    with _CACHE_LOCK:
        if fresh or _CACHE["data"] is None or time.time() - _CACHE["t"] > CACHE_SECONDS:
            _CACHE["data"] = collect(); _CACHE["t"] = time.time()
        return _CACHE["data"]


# ---------------- 停止（只对自己的工具）----------------
def _open_proc(pid):
    import ctypes
    SYNCHRONIZE = 0x00100000
    return ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)

def _wait_exit(h, seconds):
    import ctypes
    return ctypes.windll.kernel32.WaitForSingleObject(h, int(seconds * 1000)) == 0

def _pythonw_for(exe):
    """用目标进程自己的解释器跑 --stop，换成 pythonw 以免弹窗；读不到就用本进程的。"""
    exe = exe if exe and os.path.isfile(exe) else sys.executable
    d, b = os.path.split(exe)
    if b.lower() == "python.exe" and os.path.isfile(os.path.join(d, "pythonw.exe")):
        return os.path.join(d, "pythonw.exe")
    return exe

def api_stop(body):
    try:
        pid, port = int(body.get("pid")), int(body.get("port"))
    except (TypeError, ValueError):
        raise ApiError("参数不对")
    data = cached(fresh=True)     # 以当下为准，防 PID 已被别的进程复用
    row = next((r for r in data["rows"] if r["pid"] == pid and r["port"] == port), None)
    if not row:
        raise ApiError("这个进程已不在监听该端口（刷新后再看）")
    if not row["own"]:
        raise ApiError("只停止自己的工具；系统与第三方进程只显示，不提供结束")
    if pid == os.getpid():
        threading.Timer(0.5, lambda: _SERVER and _SERVER.shutdown()).start()
        return {"method": "self", "stopped": True, "notes": ["本服务将退出，本页随之失效"]}
    own = row["own"]; notes = []
    h = _open_proc(pid)
    try:
        if own.get("kit"):      # web-kit 网页服务：请它自己退出（POST /api/shutdown），不用找脚本与解释器
            k = own["kit"]
            ok = webkit.stop(k["port"], k["header"])
            notes.append(f"已请它自己退出（POST 127.0.0.1:{k['port']}/api/shutdown）" if ok else "它没有应答停止请求")
            if h and _wait_exit(h, 8):
                return {"method": "graceful", "stopped": True, "notes": notes}
            notes.append("8 秒内没有退出，改为结束进程")
        elif own["graceful"] and own["script"]:
            cmd = [_pythonw_for(row["path"] if row["path"] and not row["path"].startswith("读不到") else None),
                   own["script"], "--stop"] + (["--port", str(port)] if own["takes_port"] else [])
            try:
                subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
                notes.append("已调用工具自己的 --stop：" + " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
            except (OSError, subprocess.SubprocessError) as e:
                notes.append(f"--stop 调用失败：{e}")
            if h and _wait_exit(h, 8):
                return {"method": "graceful", "stopped": True, "notes": notes}
            notes.append("8 秒内没有退出，改为结束进程")
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=20, creationflags=CREATE_NO_WINDOW)
        msg = (r.stdout or r.stderr).decode("mbcs", "replace").strip()
        if msg: notes.append(msg)
        ok = bool(h) and _wait_exit(h, 5)
        return {"method": "taskkill", "stopped": ok, "notes": notes}
    finally:
        if h:
            import ctypes; ctypes.windll.kernel32.CloseHandle(h)


# ---------------- 以管理员身份重新启动 ----------------
# 非管理员读不到系统进程（svchost、lsass、verge-mihomo 等）的路径与命令行。页面上的按钮触发 UAC 确认；
# 确认后由管理员权限的新进程（带 --takeover）接替同一端口，本进程随即退出，页面等新进程起来后自动刷新。
def api_elevate(body):
    import ctypes
    exe = _pythonw_for(sys.executable)
    params = f'"{os.path.abspath(__file__)}" --port {Handler.port} --no-browser --takeover'
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, HERE, 0)   # 等 UAC 确认后才返回
    if r <= 32:
        raise ApiError("已取消（UAC 没有确认）" if r == 5 else f"启动失败（ShellExecute 返回 {r}）")
    threading.Timer(0.5, _SERVER.shutdown).start()      # 让出端口给管理员进程
    return {"ok": True}

def api_ports(q):
    return cached(fresh=q.get("fresh") == "1")

GET = {"/api/ports": api_ports}
POST = {"/api/stop": api_stop, "/api/elevate": api_elevate}


# ---------------- HTTP（外壳在 web-kit）----------------
_SERVER = None

class Handler(webkit.Handler):
    signature = SIGNATURE; header = "X-Port-Monitor"; web_dir = WEB
    get_routes = GET; post_routes = POST
    prefs = webkit.Prefs(os.path.join(VAR, "ui_prefs.json"))
    server_version = "port-monitor"


def main():
    global _SERVER
    webkit.setup_log(VAR)
    ap = argparse.ArgumentParser(prog="port_monitor", description="本机监听端口一览（本地网页界面）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--stop", action="store_true", help="停止正在运行的实例")
    ap.add_argument("--json", action="store_true", help="打印采集结果（JSON）后退出，不起服务")
    ap.add_argument("--takeover", action="store_true", help="接替正在退出的旧实例（以管理员身份重新启动时用）：端口被占时等它释放")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    if args.json:
        print(json.dumps(collect(), ensure_ascii=False, indent=1)); return
    if args.stop:
        print("已停止" if webkit.stop(args.port, Handler.header) else "没有在运行"); return
    if webkit.already_running(args.port, SIGNATURE) and not args.takeover:
        print(f"已在运行：{url}")
        if not args.no_browser: webbrowser.open(url)
        return
    Handler.port = args.port
    Handler.idle = webkit.IdleWatch(IDLE_MINUTES)
    try:
        srv = webkit.bind(args.port, Handler, wait_seconds=10 if args.takeover else 0)   # 接替时旧实例还在退出，最多等 10 秒
    except OSError as e:
        webkit.fail(f"端口 {args.port} 用不了（{e}）。换一个：port-monitor.bat --port {args.port + 1}", "端口监视")
    _SERVER = srv
    Handler.idle.start(srv)
    webkit.log(f"端口监视已启动：{url}（PID {os.getpid()}；停止：port_monitor.py --stop）")
    if not args.no_browser: webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    webkit.log("端口监视已退出")

if __name__ == "__main__":
    main()
