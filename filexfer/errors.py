"""异常类型定义。"""


class TransferError(Exception):
    """传输库基础异常。"""


class TaskNotFoundError(TransferError):
    """任务不存在。"""


class SourceReadError(TransferError):
    """源文件读取失败。"""


class SourceMismatchError(TransferError):
    """源文件分块摘要与登记清单不一致。"""
