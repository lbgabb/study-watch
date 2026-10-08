#!/usr/bin/env python
"""入口：等价于 python -m lib.monitor。

示例：
  python monitor.py --once          # 立刻判一次
  python monitor.py --minutes 25    # 番茄钟式监督 25 分钟
  python monitor.py --report        # 今日日报
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.monitor import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
