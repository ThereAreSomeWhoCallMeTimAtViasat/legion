from PyQt6 import QtWidgets
from PyQt6.QtCore import pyqtSignal, QObject
import logging
from rich.console import Console
from rich.logging import RichHandler
from io import StringIO
import re


class QTextEditLogger(logging.Handler, QObject):
    log_signal = pyqtSignal(str)

    def __init__(self, parent):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.widget = QtWidgets.QTextEdit(parent)
        self.widget.setReadOnly(True)

        # Signal to emit log messages (signals are thread-safe in Qt)
        self.log_signal.connect(self.append_log)  # Connect signal to slot (runs in GUI thread)

        self.string_buffer = StringIO()  # Buffer to capture console output
        self.console = Console(file=self.string_buffer, width=150, force_terminal=True, force_jupyter=False, record=True)  # Create a Rich Console that writes to the buffer
        self.rich_handler = RichHandler(console=self.console, rich_tracebacks=True, show_time=True, show_path=True)
        
        # Set initial level to INFO
        self.setLevel(logging.INFO)

    def emit(self, record):
        # Called from any thread - thread-safe due to logging module's internal locks
        try:
            # Create RichHandler with this console
            self.string_buffer.seek(0)
            self.string_buffer.truncate(0)  # Clear the buffer
            self.rich_handler.emit(record)  # Let RichHandler format and write to buffer
            html = self.console.export_html(inline_styles=True, clear=True)  # Get the buffered output as HTML
            body_match = re.search(r'<pre.*?>(.*?)</pre>', html, re.DOTALL)
            if body_match:
                formatted_html = body_match.group(1)  # Extract just the body content
                indented_html = f'<div style="padding-left: 20px;">{formatted_html}</div>'  # Add indentation
                self.log_signal.emit(indented_html)
        except Exception as e:
            self.handleError(record)

    def append_log(self, html):
        # Slot called in GUI thread - safe to update QTextEdit here
        self.widget.append(html)  # Emit signal (thread-safe) instead of directly updating widget
        scrollbar = self.widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())  # Auto-scroll to bottom

    def append(self, msg):
        # Thread-safe append method
        self.log_signal.emit(msg)
    
    def setLogLevel(self, level):
        """Set the logging level for this handler"""
        self.setLevel(level)

