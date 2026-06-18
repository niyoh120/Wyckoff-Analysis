"""批量研报管线的公共 API 转发层。"""

from scripts.step3_batch_report import (  # noqa: F401
    run as run_step3,
)
from tools.report_builder import (  # noqa: F401
    extract_operation_pool_codes,
    extract_operation_pool_springboards,
    generate_stock_payload,
)

__all__ = [
    "extract_operation_pool_codes",
    "extract_operation_pool_springboards",
    "generate_stock_payload",
    "run_step3",
]
