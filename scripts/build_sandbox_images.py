from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_config
from app.realscan.pipeline import RealscanPipeline
from app.realscan.policy import ImageResolver


def main() -> int:
    parser = argparse.ArgumentParser(description="build the sandbox and target images")
    parser.add_argument("--build-network", choices=("on", "off"), default="on")
    parser.add_argument("--sandbox-image", default="verifix-sandbox:1.0.0")
    parser.add_argument("--target-image", default="verifix-target:1.0.0")
    args = parser.parse_args()

    config = load_config().realscan
    pipeline = RealscanPipeline(config)
    transport = pipeline.transport
    prefix = "wsl.exe -d Debian -u root -- " if getattr(transport, "name", "") == "wsl" else ""
    images: list[dict[str, object]] = []
    for dockerfile, image, context in (
        ("sandbox/Dockerfile.sandbox", args.sandbox_image, "sandbox"),
        ("sandbox/Dockerfile.target", args.target_image, "sandbox"),
    ):
        started = time.perf_counter()
        argv = ["docker", "build", "-f", dockerfile, "-t", image]
        if args.build_network == "off":
            argv.append("--network=none")
        argv.append(context)
        result = transport.run(argv, 900.0, cwd=ROOT)
        elapsed = int((time.perf_counter() - started) * 1000)
        if not result.ok:
            print(
                json.dumps(
                    {
                        "stage": "build",
                        "image": image,
                        "exit_code": result.exit_code,
                        "reason": (result.stderr or result.stdout or "").strip().splitlines()[-1][:200]
                        if (result.stderr or result.stdout).strip()
                        else "build_failed",
                        "build_network": args.build_network,
                        "command": prefix + " ".join(argv),
                    },
                    ensure_ascii=False,
                )
            )
            return 3
        resolution = ImageResolver(transport, [image]).inspect(image)
        images.append(
            {
                "image": image,
                "image_id": resolution.image_id,
                "repo_digests": resolution.repo_digests,
                "local_build": resolution.local_build,
                "build_network": args.build_network,
                "build_elapsed_ms": elapsed,
                "source": resolution.source,
            }
        )
    print(json.dumps({"build_network": args.build_network, "images": images}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())