"""
IniSettingsStore — Qt-free drop-in for QtCore.QSettings (IniFormat).

Provides the same API that AppSettings uses:
  fileName()
  beginGroup(name) / endGroup()
  childKeys()
  value(key)
  setValue(key, value)
  remove(key)
  clear()
  sync()
  status()

Uses Python's configparser internally. Handles the same CSV/list
parsing that QSettings does for [HostActions], [PortActions], etc.
"""

import configparser
import csv
import io
import os


class _Status:
    NoError = 0
    AccessError = 1
    FormatError = 2


class IniSettingsStore:
    """Drop-in replacement for QtCore.QSettings(path, IniFormat)."""

    Status = _Status

    # Sections that store list values (QSettings returns lists for these)
    _LIST_SECTIONS = {
        'HostActions', 'PortActions', 'PortTerminalActions', 'SchedulerSettings',
    }

    def __init__(self, file_path: str):
        self._file_path = str(file_path)
        self._groups = []
        self._status = _Status.NoError
        self._parser = configparser.RawConfigParser()
        self._parser.optionxform = str  # preserve case
        if os.path.exists(self._file_path):
            try:
                self._parser.read(self._file_path, encoding='utf-8')
            except Exception:
                self._status = _Status.FormatError

    def fileName(self) -> str:
        return self._file_path

    def status(self) -> int:
        return self._status

    def beginGroup(self, name: str):
        self._groups.append(str(name).strip())

    def endGroup(self):
        if self._groups:
            self._groups.pop()

    def _section(self) -> str:
        return '/'.join(self._groups) if self._groups else ''

    def childKeys(self):
        sec = self._section()
        if not sec or not self._parser.has_section(sec):
            return []
        return list(self._parser.options(sec))

    def value(self, key: str):
        """Return value for key in the current group.
        For list sections (HostActions, PortActions, etc.) returns a list.
        For all others returns a string.
        """
        sec = self._section()
        if not sec or not self._parser.has_option(sec, key):
            return None
        raw = self._parser.get(sec, key)
        if sec in self._LIST_SECTIONS:
            return self._decode_csv(raw)
        return self._decode_scalar(raw)

    def setValue(self, key: str, value):
        sec = self._section()
        if not sec:
            return
        if not self._parser.has_section(sec):
            self._parser.add_section(sec)
        if sec in self._LIST_SECTIONS and isinstance(value, (list, tuple)):
            encoded = self._encode_csv(value)
        else:
            encoded = self._encode_scalar(value)
        self._parser.set(sec, key, encoded)

    def remove(self, key: str):
        """Remove a key (or all keys if key=='') from current group."""
        sec = self._section()
        if not sec:
            return
        if key == '':
            # Remove all keys in the section
            if self._parser.has_section(sec):
                self._parser.remove_section(sec)
        elif self._parser.has_option(sec, key):
            self._parser.remove_option(sec, key)

    def clear(self):
        """Clear all sections."""
        for sec in self._parser.sections():
            self._parser.remove_section(sec)

    def sync(self):
        """Write to disk."""
        try:
            parent = os.path.dirname(self._file_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self._file_path, 'w', encoding='utf-8') as f:
                self._parser.write(f, space_around_delimiters=False)
            self._status = _Status.NoError
        except Exception:
            self._status = _Status.AccessError

    # ── CSV encoding/decoding (matches QSettings list behavior) ──

    @staticmethod
    def _decode_scalar(raw: str):
        """Strip outer quotes from a scalar value."""
        s = str(raw).strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            return s[1:-1]
        return s

    @staticmethod
    def _decode_csv(raw: str):
        """Decode a CSV value into a list (matches QSettings list behavior)."""
        text = str(raw).strip()
        if not text:
            return []
        try:
            return next(csv.reader([text], skipinitialspace=True))
        except Exception:
            return [text]

    @staticmethod
    def _encode_csv(values) -> str:
        """Encode a list into CSV string."""
        row = [str(v) for v in list(values)]
        buf = io.StringIO()
        csv.writer(buf, lineterminator='').writerow(row)
        return buf.getvalue()

    @staticmethod
    def _encode_scalar(value) -> str:
        """Encode a scalar value, quoting if it contains commas."""
        text = str(value) if value is not None else ''
        if ',' in text:
            buf = io.StringIO()
            csv.writer(buf, lineterminator='').writerow([text])
            return buf.getvalue()
        return text
