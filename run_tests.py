"""在 VS Code 中打开本文件并点击运行，即可使用项目虚拟环境执行全部测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print(
            "未找到项目虚拟环境，请按 tests/README.md 的说明创建 .venv 并安装依赖。",
            file=sys.stderr,
        )
        return 2
    try:
        result = subprocess.run(
            [str(python), str(root / "tests" / "run_tests.py"), *sys.argv[1:]],
            cwd=root,
            check=False,
        )
    except KeyboardInterrupt:
        return 130
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
