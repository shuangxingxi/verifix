from __future__ import annotations

SNAPSHOT_PROBE = r'''
import json
import os

facts = {"uid": os.getuid(), "gid": os.getgid()}
try:
    with open("/proc/self/mountinfo", "r", encoding="utf-8", errors="replace") as handle:
        mounts = handle.read()
    facts["mountinfo_lines"] = len(mounts.splitlines())
    facts["root_ro"] = " ro," in mounts
except OSError as exc:
    facts["mountinfo_error"] = type(exc).__name__
try:
    with open("/etc/shadow", "rb") as handle:
        handle.read(1)
    facts["shadow_readable"] = True
except OSError as exc:
    facts["shadow_readable"] = False
    facts["shadow_error"] = type(exc).__name__
print(json.dumps(facts, sort_keys=True))
'''

EGRESS_PROBE = r'''
import json
import socket

target = "1.1.1.1:53"
try:
    connection = socket.create_connection(("1.1.1.1", 53), timeout=3)
    connection.close()
    print(json.dumps({"target": target, "ok": True, "error_type": "", "detail": "connected"}, sort_keys=True))
except OSError as exc:
    print(json.dumps({"target": target, "ok": False, "error_type": type(exc).__name__, "detail": str(exc)[:120]}, sort_keys=True))
'''

LOOPBACK_PROBE = r'''
import json
import socket

result = {"bind": False, "listen": True, "connect": False}
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    server.bind(("127.0.0.1", 0))
    result["bind"] = True
    result["port"] = server.getsockname()[1]
    server.listen(1)
    client = socket.create_connection(("127.0.0.1", result["port"]), timeout=2)
    result["connect"] = True
    client.close()
except OSError as exc:
    result["error_type"] = type(exc).__name__
finally:
    server.close()
print(json.dumps(result, sort_keys=True))
'''

FILESYSTEM_PROBE = r'''
import json
import os

result = {
    "root_write": False,
    "tmp_writable": False,
    "workspace_writable": False,
    "src_write": False,
    "src_read": False,
}
try:
    with open("/etc/.vf-probe", "w", encoding="utf-8") as handle:
        handle.write("1")
    os.unlink("/etc/.vf-probe")
    result["root_write"] = True
except OSError as exc:
    result["root_error"] = type(exc).__name__
for name, path in (("tmp_writable", "/tmp"), ("workspace_writable", "/workspace")):
    marker = os.path.join(path, ".vf-probe")
    try:
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("1")
        os.unlink(marker)
        result[name] = True
    except OSError as exc:
        result[name + "_error"] = type(exc).__name__
try:
    with open("/src/.vf-probe", "w", encoding="utf-8") as handle:
        handle.write("1")
    result["src_write"] = True
    os.unlink("/src/.vf-probe")
except OSError as exc:
    result["src_error"] = type(exc).__name__
try:
    with open("/src/app/main.py", "rb") as handle:
        handle.read(1)
    result["src_read"] = True
except OSError as exc:
    result["src_read_error"] = type(exc).__name__
print(json.dumps(result, sort_keys=True))
'''

IDENTITY_PROBE = r'''
import json
import os

result = {"uid": os.getuid(), "gid": os.getgid(), "cap_eff": "unknown", "no_new_privs": "unknown", "setuid_blocked": False}
try:
    with open("/proc/self/status", "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("CapEff:"):
                result["cap_eff"] = line.split()[1]
            elif line.startswith("NoNewPrivs:"):
                result["no_new_privs"] = line.split()[1]
except OSError as exc:
    result["status_error"] = type(exc).__name__
try:
    os.setuid(0)
    result["setuid_blocked"] = False
except OSError as exc:
    result["setuid_blocked"] = True
    result["setuid_error"] = type(exc).__name__
print(json.dumps(result, sort_keys=True))
'''

CGROUP_PROBE = r'''
import json
import os

result = {}
for key, path in (("memory_max", "/sys/fs/cgroup/memory.max"), ("cpu_max", "/sys/fs/cgroup/cpu.max"), ("pids_max", "/sys/fs/cgroup/pids.max")):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            result[key] = handle.read().strip()
    except OSError as exc:
        result[key] = "unknown"
        result[key + "_error"] = type(exc).__name__
print(json.dumps(result, sort_keys=True))
'''

P4_01_PROBE = r'''
import json
import os

result = {"dot_git_visible": False, "git_config_readable": False, "positive_control": False}
for _root, dirs, _files in os.walk("/src"):
    if ".git" in dirs:
        result["dot_git_visible"] = True
        break
try:
    with open("/src/.git/config", "rb") as handle:
        handle.read(1)
    result["git_config_readable"] = True
except OSError as exc:
    result["git_config_error"] = type(exc).__name__
try:
    with open("/src/app/main.py", "rb") as handle:
        handle.read(1)
    result["positive_control"] = True
except OSError as exc:
    result["positive_error"] = type(exc).__name__
print(json.dumps(result, sort_keys=True))
'''
P4_05_PROBE = r'''
import time
while True:
    time.sleep(0.5)
'''