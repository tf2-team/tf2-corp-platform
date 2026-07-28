#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
import re


_FIELD_START = re.compile(r"(?<!\S)([A-Za-z_][A-Za-z0-9_.-]*)=")


class FullPrettyFormatter(logging.Formatter):
    """Render a one-line structured event as a readable block."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        timestamp = f"{timestamp}.{int(record.msecs):03d}"
        lines = [f"+- {timestamp}  {record.levelname}  {record.name}"]

        segments = [segment.strip() for segment in record.getMessage().split("|")]
        for index, segment in enumerate(segments):
            if index > 0:
                lines.append("|")
                lines.append(f"| Segment {index + 1}")
            lines.extend(self._format_segment(segment))

        if record.exc_info:
            lines.append("| Exception:")
            for line in self.formatException(record.exc_info).splitlines():
                lines.append(f"|   {line}")

        if record.stack_info:
            lines.append("| Stack:")
            for line in self.formatStack(record.stack_info).splitlines():
                lines.append(f"|   {line}")

        lines.append("+-")
        return "\n".join(lines)

    @staticmethod
    def _format_segment(segment: str) -> list[str]:
        matches = list(_FIELD_START.finditer(segment))
        if not matches:
            return [f"| Message : {segment}"]

        lines: list[str] = []
        prefix = segment[: matches[0].start()].strip()
        if prefix:
            lines.append(f"| Event   : {prefix}")

        width = max(len(match.group(1)) for match in matches)
        for index, match in enumerate(matches):
            key = match.group(1)
            value_start = match.end()
            value_end = matches[index + 1].start() if index + 1 < len(matches) else len(segment)
            value = segment[value_start:value_end].strip()
            lines.append(f"| {key.ljust(width)} : {value}")
        return lines


def configure_root_logging(level: str = "INFO", output_format: str = "pretty") -> None:
    """Configure the process-wide root logger."""
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
