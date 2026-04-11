"""
Windows 下 Rasa 加载模型时，官方会对 tar.extractall 使用 \\\\?\\ 扩展路径前缀；
与归档内使用正斜杠的成员路径组合时，部分环境会触发 WinError 123。
本入口在启动 CLI 前替换解压逻辑，避免该问题。

非 Windows 或未遇到该问题时，行为与直接执行 `rasa` 一致。
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path


def _apply_windows_extract_patch() -> None:
    if platform.system() != "Windows":
        return

    from tarsafe import TarSafe

    from rasa.engine.storage.local_model_storage import LocalModelStorage

    def _extract_archive_to_directory(model_archive_path, temporary_directory) -> None:
        with TarSafe.open(model_archive_path, mode="r:gz") as tar:
            tar.extractall(Path(temporary_directory))
        LocalModelStorage._assert_not_rasa2_archive(temporary_directory)

    LocalModelStorage._extract_archive_to_directory = staticmethod(
        _extract_archive_to_directory
    )


if __name__ == "__main__":
    _apply_windows_extract_patch()
    sys.argv[0] = "rasa"
    from rasa.__main__ import main

    main()
