from __future__ import annotations

import sys

from scripts import _bootstrap

sys.modules.setdefault("_bootstrap", _bootstrap)
