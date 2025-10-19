from PyQt6 import QtWidgets
from PyQt6.QtCore import pyqtSignal, QObject
import logging
from rich.console import Console
from rich.logging import RichHandler
from io import StringIO
import re


class QTextEditLogger(logging.Handler, QObject):
    # Signal to emit log messages (signals are thread-safe in Qt)
    log_signal = pyqtSignal(str)
    
    def __init__(self, parent):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        
        self.widget = QtWidgets.QTextEdit(parent)
        self.widget.setReadOnly(True)
        
        # Connect signal to slot (runs in GUI thread)
        self.log_signal.connect(self._append_log)
        
        # Buffer to capture console output
        self.string_buffer = StringIO()
        
        # Create a Rich Console that writes to the buffer
        self.console = Console(
            file=self.string_buffer,
            width=150,
            force_terminal=True,
            force_jupyter=False,
            record=True
        )
        
        # Create RichHandler with this console
        self.rich_handler = RichHandler(
            console=self.console,
            rich_tracebacks=True,
            show_time=True,
            show_path=True
        )
        
    def emit(self, record):
        """
        Called from any thread - thread-safe due to logging module's internal locks
        """
        try:
            # Clear the buffer
            self.string_buffer.seek(0)
            self.string_buffer.truncate(0)
            
            # Let RichHandler format and write to buffer
            self.rich_handler.emit(record)
            
            # Get the buffered output as HTML
            html = self.console.export_html(inline_styles=True, clear=True)
            
            # Extract just the body content
            body_match = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL)
            if body_match:
                formatted_html = body_match.group(1)
                
                # Add indentation
                indented_html = f'<div style="padding-left: 20px;">{formatted_html}</div>'
                
                # Emit signal (thread-safe) instead of directly updating widget
                self.log_signal.emit(indented_html)
            
        except Exception as e:
            self.handleError(record)
    
    def _append_log(self, html):
        """
        Slot called in GUI thread - safe to update QTextEdit here
        """
        self.widget.append(html)
        
        # Auto-scroll to bottom
        scrollbar = self.widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append(self, msg):
        """Thread-safe append method"""
        self.log_signal.emit(msg)
