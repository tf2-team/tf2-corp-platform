#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
import re


# Tìm các field có dạng key=value trong log hiện tại.
_FIELD_START = re.compile(r"(?<!\S)([A-Za-z_][A-Za-z0-9_.-]*)=")


class FullPrettyFormatter(logging.Formatter):
    """
    Chuyển log một dòng thành block dễ đọc.

    Formatter không summary, không làm tròn số và không cố tình bỏ field.
    Các đoạn phân cách bằng "|" được hiển thị thành từng segment riêng.
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        timestamp = f"{timestamp}.{int(record.msecs):03d}"

        lines = [
            f"┌─ {timestamp}  {record.levelname}  {record.name}"
        ]

        message = record.getMessage()
        segments = [
            segment.strip()
            for segment in message.split("|")
        ]

        for index, segment in enumerate(segments):
            if index > 0:
                lines.append("│")
                lines.append(f"│ Segment {index + 1}")

            lines.extend(self._format_segment(segment))

        # Giữ đầy đủ exception traceback nếu log có exception.
        if record.exc_info:
            lines.append("│ Exception:")
            exception = self.formatException(record.exc_info)

            for line in exception.splitlines():
                lines.append(f"│   {line}")

        # Giữ đầy đủ stack information nếu có.
        if record.stack_info:
            lines.append("│ Stack:")
            stack = self.formatStack(record.stack_info)

            for line in stack.splitlines():
                lines.append(f"│   {line}")

        lines.append("└─")

        return "\n".join(lines)

    @staticmethod
    def _format_segment(segment: str) -> list[str]:
        matches = list(_FIELD_START.finditer(segment))

        # Log không có key=value vẫn được giữ nguyên.
        if not matches:
            return [f"│ Message : {segment}"]

        lines: list[str] = []

        # Phần đứng trước key=value, ví dụ:
        # AIOPS_DETECT threshold_fire
        prefix = segment[:matches[0].start()].strip()

        if prefix:
            lines.append(f"│ Event   : {prefix}")

        # Căn các dấu ":" thẳng hàng.
        width = max(
            len(match.group(1))
            for match in matches
        )

        for index, match in enumerate(matches):
            key = match.group(1)
            value_start = match.end()

            if index + 1 < len(matches):
                value_end = matches[index + 1].start()
            else:
                value_end = len(segment)

            # Không convert sang float và không làm tròn.
            value = segment[value_start:value_end].strip()

            lines.append(
                f"│ {key.ljust(width)} : {value}"
            )

        return lines


def configure_root_logging(
    level: str = "INFO",
    output_format: str = "pretty",
) -> None:
    """
    Cấu hình root logger.

    output_format=pretty: block nhiều dòng.
    output_format=plain: format một dòng cũ.
    """

    if output_format.lower() == "plain":
        formatter: logging.Formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    else:
        formatter = FullPrettyFormatter()

    root_logger = logging.getLogger()

    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())

    root_logger.setLevel(level.upper())

    for handler in root_logger.handlers:
        handler.setFormatter(formatter)