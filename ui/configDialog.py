#!/usr/bin/env python

"""
LEGION (https://shanewilliamscott.com)
Copyright (c) 2025 Shane William Scott

    This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
    License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
    version.

    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
    warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
    details.

    You should have received a copy of the GNU General Public License along with this program.
    If not, see <http://www.gnu.org/licenses/>.

"""

import os
import json
import shutil
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *
from PyQt6 import QtWidgets, QtGui, QtCore
from app.auxiliary import *
from app.timing import getTimestamp
from six import u as unicode
from ui.ancillaryDialog import flipState

class Config(QtWidgets.QTextEdit):
    def __init__(self, qss, parent=None):
        super(Config, self).__init__(parent)
        self.setMinimumHeight(550)
        self.setStyleSheet(qss)
        self.originalText = ""
        self.setReadOnly(False)
        
        # Track changes
        self.textChanged.connect(self.markAsModified)
        self.modified = False
    
    def loadFile(self, filepath):
        """Load a config file into the editor."""
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            self.originalText = content
            self.setPlainText(content)
            self.modified = False
            return True
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                "Load Failed",
                f"Could not load config file:\n{e}"
            )
            return False
    
    def markAsModified(self):
        """Track that content has been modified."""
        self.modified = True
    
    def getText(self):
        return self.toPlainText()
    
    def hasUnsavedChanges(self):
        """Check if current text differs from original."""
        return self.toPlainText() != self.originalText
    
    def reloadFromFile(self, filepath):
        """Reload original content from file, discarding changes."""
        self.loadFile(filepath)
        self.modified = False

class ConfigDialog(QtWidgets.QDialog):
    def __init__(self, controller, qss, parent=None):
        super(ConfigDialog, self).__init__(parent)
        self.controller = controller
        self.qss = qss
        self.setWindowTitle("Config Manager - Multiple Profiles")
        self.setGeometry(0, 0, 900, 700)
        self.center()
        
        # Setup profile system
        self.profilesDir = os.path.expanduser('~/.local/share/legion/profiles')
        self.ensureProfilesDirectory()
        self.ensureDefaultProfile()
        
        self.currentProfile = self.loadActiveProfile()
        self.profiles = {}  # {name: filepath}
        self.loadProfilesList()
        
        # Store editor widgets for each profile
        self.profileEditors = {}  # {profile_name: Config widget}
        
        self.buildUI()
        self.setStyleSheet(self.qss)

    def center(self):
        frameGm = self.frameGeometry()
        centerPoint = QtGui.QGuiApplication.primaryScreen().availableGeometry().center()
        frameGm.moveCenter(centerPoint)
        self.move(frameGm.topLeft())

    def buildUI(self):
        """Build the entire UI with profile tabs and controls."""
        mainLayout = QtWidgets.QVBoxLayout()
        
        # Top section: Profile selector and action buttons
        topLayout = self.buildTopSection()
        mainLayout.addLayout(topLayout)
        
        # Separator
        mainLayout.addWidget(QtWidgets.QLabel(""))
        
        # Tab widget for editing profiles
        self.profileTabs = QtWidgets.QTabWidget()
        self.profileTabs.setTabsClosable(True)
        self.profileTabs.tabCloseRequested.connect(self.closeProfileTab)
        
        # Add tabs for each profile
        for profile_name, profile_path in sorted(self.profiles.items()):
            editor = Config(qss=self.qss)
            editor.loadFile(profile_path)
            
            # Add tab with icon if active
            if profile_name == self.currentProfile:
                tab_icon = QtGui.QIcon('images/star.png')
                self.profileTabs.addTab(editor, tab_icon, profile_name)
            else:
                self.profileTabs.addTab(editor, profile_name)
            
            self.profileEditors[profile_name] = editor
        
        # Add "+" button to create new profile
        self.addProfileButton = QtWidgets.QPushButton("+")
        self.addProfileButton.setFixedWidth(40)
        self.addProfileButton.setToolTip("Create new profile")
        self.addProfileButton.clicked.connect(self.createNewProfile)
        self.profileTabs.setCornerWidget(self.addProfileButton, QtCore.Qt.Corner.TopRightCorner)
        
        mainLayout.addWidget(self.profileTabs)
        
        # Bottom section: Action buttons
        bottomLayout = self.buildBottomSection()
        mainLayout.addLayout(bottomLayout)
        
        self.setLayout(mainLayout)

    def buildTopSection(self):
        """Build top section with profile selector and activate button."""
        layout = QtWidgets.QHBoxLayout()
        
        # Label
        layout.addWidget(QtWidgets.QLabel("Active Profile:"))
        
        # Profile selector dropdown
        self.profileSelector = QtWidgets.QComboBox()
        self.profileSelector.addItems(sorted(self.profiles.keys()))
        if self.currentProfile in self.profiles:
            self.profileSelector.setCurrentText(self.currentProfile)
        self.profileSelector.setMinimumWidth(150)
        layout.addWidget(self.profileSelector)
        
        # Activate button
        self.activateButton = QtWidgets.QPushButton("★ Activate Profile")
        self.activateButton.setToolTip("Make selected profile active for this session")
        self.activateButton.clicked.connect(self.activateProfile)
        layout.addWidget(self.activateButton)
        
        # Info label showing current active
        self.activeInfoLabel = QtWidgets.QLabel(f"Currently Active: {self.currentProfile}")
        self.activeInfoLabel.setStyleSheet("color: #ffaa00; font-weight: bold;")
        layout.addWidget(self.activeInfoLabel)
        
        layout.addStretch()
        return layout

    def buildBottomSection(self):
        """Build bottom section with action buttons."""
        layout = QtWidgets.QHBoxLayout()
        
        # Save current profile
        self.saveButton = QtWidgets.QPushButton("Save")
        self.saveButton.setFixedWidth(90)
        self.saveButton.setIcon(QtGui.QIcon('images/save.png'))
        self.saveButton.clicked.connect(self.saveCurrentProfile)
        layout.addWidget(self.saveButton)
        
        # Rename profile
        self.renameButton = QtWidgets.QPushButton("Rename Profile")
        self.renameButton.setFixedWidth(120)
        self.renameButton.clicked.connect(self.renameProfile)
        layout.addWidget(self.renameButton)
        
        # Duplicate profile
        self.duplicateButton = QtWidgets.QPushButton("Duplicate")
        self.duplicateButton.setFixedWidth(90)
        self.duplicateButton.clicked.connect(self.duplicateProfile)
        layout.addWidget(self.duplicateButton)
        
        layout.addStretch()
        
        # Close button
        self.closeButton = QtWidgets.QPushButton("Close")
        self.closeButton.setFixedWidth(90)
        self.closeButton.setIcon(QtGui.QIcon('images/close.png'))
        self.closeButton.clicked.connect(self.closeDialog)
        layout.addWidget(self.closeButton)
        
        return layout

    def ensureProfilesDirectory(self):
        """Ensure profiles directory exists."""
        if not os.path.exists(self.profilesDir):
            os.makedirs(self.profilesDir, exist_ok=True)

    def ensureDefaultProfile(self):
        """Ensure default profile exists."""
        default_path = os.path.join(self.profilesDir, 'default.conf')
        working_config = os.path.expanduser('~/.local/share/legion/legion.conf')
        
        if not os.path.exists(default_path) and os.path.exists(working_config):
            shutil.copy(working_config, default_path)

    def loadProfilesList(self):
        """Load all available profiles."""
        self.profiles = {}
        
        if not os.path.exists(self.profilesDir):
            return
        
        for filename in os.listdir(self.profilesDir):
            if filename.endswith('.conf'):
                profile_name = filename.replace('.conf', '')
                profile_path = os.path.join(self.profilesDir, filename)
                self.profiles[profile_name] = profile_path

    def loadActiveProfile(self):
        """Load name of currently active profile."""
        active_file = os.path.expanduser('~/.local/share/legion/active_profile.txt')
        
        if os.path.exists(active_file):
            try:
                with open(active_file, 'r') as f:
                    return f.read().strip()
            except:
                pass
        
        return 'default'

    def saveActiveProfile(self, profile_name):
        """Save which profile is currently active."""
        active_file = os.path.expanduser('~/.local/share/legion/active_profile.txt')
        try:
            with open(active_file, 'w') as f:
                f.write(profile_name)
        except Exception as e:
            print(f"Error saving active profile: {e}")

    def saveCurrentProfile(self):
        """Save the currently selected profile tab."""
        current_index = self.profileTabs.currentIndex()
        if current_index < 0:
            return
        
        profile_name = self.profileTabs.tabText(current_index)
        editor = self.profileEditors[profile_name]
        
        # Validate config
        config_text = editor.getText()
        
        validation_errors = self.validateConfigSyntax(config_text)
        if validation_errors:
            self.showScrollableErrorDialog(
                f"Cannot Save - {len(validation_errors)} Syntax Error(s)",
                f"Profile '{profile_name}' has syntax errors:",
                validation_errors
            )
            return
        
        # Validate setting names
        semantic_errors = self.validateSettingNames(config_text)
        if semantic_errors:
            self.showScrollableErrorDialog(
                f"Cannot Save - {len(semantic_errors)} Invalid Setting(s)",
                f"Profile '{profile_name}' contains unknown settings:",
                semantic_errors
            )
            return
        
        # Write profile file
        profile_path = self.profiles[profile_name]
        try:
            with open(profile_path, 'w') as f:
                f.write(config_text)
            
            editor.originalText = config_text
            editor.modified = False
            
            QtWidgets.QMessageBox.information(
                self,
                "Saved",
                f"Profile '{profile_name}' saved successfully."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Save Failed",
                f"Failed to save profile:\n{e}"
            )

    def activateProfile(self):
        """Switch to selected profile and reload Legion settings."""
        profile_name = self.profileSelector.currentText()
        
        # Check for unsaved changes in current profile
        current_editor = self.profileEditors.get(self.currentProfile)
        if current_editor and current_editor.hasUnsavedChanges():
            reply = QtWidgets.QMessageBox.warning(
                self,
                "Unsaved Changes",
                f"Profile '{self.currentProfile}' has unsaved changes.\n\n"
                "Save before switching?",
                QtWidgets.QMessageBox.StandardButton.Save | 
                QtWidgets.QMessageBox.StandardButton.Discard |
                QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel
            )
            
            if reply == QtWidgets.QMessageBox.StandardButton.Save:
                self.saveCurrentProfile()
            elif reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                return
        
        # Copy profile to active location
        profile_path = self.profiles[profile_name]
        working_config = os.path.expanduser('~/.local/share/legion/legion.conf')
        
        try:
            shutil.copy(profile_path, working_config)
            self.currentProfile = profile_name
            self.saveActiveProfile(profile_name)
            
            # Reload settings
            self.controller.loadSettings()
            
            # Update UI
            self.updateProfileIndicators()
            
            QtWidgets.QMessageBox.information(
                self,
                "Profile Activated",
                f"Profile '{profile_name}' is now active.\n\n"
                "Legion has reloaded with the new configuration."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Activation Failed",
                f"Failed to activate profile:\n{e}"
            )

    def createNewProfile(self):
        """Create a new profile."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Create New Profile")
        dialog.setModal(True)
        
        layout = QtWidgets.QVBoxLayout()
        
        # Profile name input
        layout.addWidget(QtWidgets.QLabel("Profile name:"))
        nameInput = QtWidgets.QLineEdit()
        layout.addWidget(nameInput)
        
        # Copy from selector
        layout.addWidget(QtWidgets.QLabel("Copy settings from:"))
        copySelector = QtWidgets.QComboBox()
        copySelector.addItems(sorted(self.profiles.keys()))
        layout.addWidget(copySelector)
        
        # Buttons
        buttonLayout = QtWidgets.QHBoxLayout()
        createBtn = QtWidgets.QPushButton("Create")
        cancelBtn = QtWidgets.QPushButton("Cancel")
        createBtn.clicked.connect(dialog.accept)
        cancelBtn.clicked.connect(dialog.reject)
        buttonLayout.addWidget(createBtn)
        buttonLayout.addWidget(cancelBtn)
        layout.addLayout(buttonLayout)
        
        dialog.setLayout(layout)
        
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        
        profile_name = nameInput.text().strip()
        if not profile_name:
            QtWidgets.QMessageBox.warning(self, "Invalid", "Profile name cannot be empty.")
            return
        
        if profile_name in self.profiles:
            QtWidgets.QMessageBox.warning(self, "Exists", f"Profile '{profile_name}' already exists.")
            return
        
        # Copy from selected profile
        source_profile = copySelector.currentText()
        source_path = self.profiles[source_profile]
        dest_path = os.path.join(self.profilesDir, f'{profile_name}.conf')
        
        try:
            shutil.copy(source_path, dest_path)
            self.profiles[profile_name] = dest_path
            
            # Add new tab
            editor = Config(qss=self.qss)
            editor.loadFile(dest_path)
            self.profileEditors[profile_name] = editor
            self.profileTabs.addTab(editor, profile_name)
            
            # Update selector
            self.profileSelector.addItem(profile_name)
            
            QtWidgets.QMessageBox.information(
                self,
                "Created",
                f"Profile '{profile_name}' created successfully."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Creation Failed",
                f"Failed to create profile:\n{e}"
            )

    def renameProfile(self):
        """Rename current profile."""
        current_index = self.profileTabs.currentIndex()
        if current_index < 0:
            return
        
        old_name = self.profileTabs.tabText(current_index)
        
        if old_name == 'default':
            QtWidgets.QMessageBox.warning(self, "Cannot Rename", "Cannot rename the default profile.")
            return
        
        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Rename Profile",
            f"New name for '{old_name}':",
            text=old_name
        )
        
        if not ok or not new_name.strip():
            return
        
        new_name = new_name.strip()
        
        if new_name in self.profiles:
            QtWidgets.QMessageBox.warning(self, "Exists", f"Profile '{new_name}' already exists.")
            return
        
        old_path = self.profiles[old_name]
        new_path = os.path.join(self.profilesDir, f'{new_name}.conf')
        
        try:
            os.rename(old_path, new_path)
            
            # Update internal tracking
            del self.profiles[old_name]
            self.profiles[new_name] = new_path
            
            # Update UI
            self.profileTabs.setTabText(current_index, new_name)
            self.profileEditors[new_name] = self.profileEditors.pop(old_name)
            
            # Update selector
            index = self.profileSelector.findText(old_name)
            if index >= 0:
                self.profileSelector.removeItem(index)
            self.profileSelector.addItem(new_name)
            
            QtWidgets.QMessageBox.information(
                self,
                "Renamed",
                f"Profile renamed to '{new_name}'."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Rename Failed",
                f"Failed to rename profile:\n{e}"
            )

    def duplicateProfile(self):
        """Duplicate current profile."""
        current_index = self.profileTabs.currentIndex()
        if current_index < 0:
            return
        
        source_name = self.profileTabs.tabText(current_index)
        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Duplicate Profile",
            f"Name for copy of '{source_name}':",
            text=f"{source_name}_copy"
        )
        
        if not ok or not new_name.strip():
            return
        
        new_name = new_name.strip()
        
        if new_name in self.profiles:
            QtWidgets.QMessageBox.warning(self, "Exists", f"Profile '{new_name}' already exists.")
            return
        
        source_path = self.profiles[source_name]
        dest_path = os.path.join(self.profilesDir, f'{new_name}.conf')
        
        try:
            shutil.copy(source_path, dest_path)
            self.profiles[new_name] = dest_path
            
            # Add new tab
            editor = Config(qss=self.qss)
            editor.loadFile(dest_path)
            self.profileEditors[new_name] = editor
            self.profileTabs.addTab(editor, new_name)
            
            # Update selector
            self.profileSelector.addItem(new_name)
            
            QtWidgets.QMessageBox.information(
                self,
                "Duplicated",
                f"Profile '{source_name}' duplicated as '{new_name}'."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Duplication Failed",
                f"Failed to duplicate profile:\n{e}"
            )

    def closeProfileTab(self, index):
        """Close a profile tab (delete profile)."""
        profile_name = self.profileTabs.tabText(index)
        
        if profile_name == 'default':
            QtWidgets.QMessageBox.warning(self, "Cannot Delete", "Cannot delete the default profile.")
            return
        
        if profile_name == self.currentProfile:
            QtWidgets.QMessageBox.warning(
                self,
                "Cannot Delete",
                "Cannot delete the currently active profile.\n\n"
                "Switch to another profile first."
            )
            return
        
        reply = QtWidgets.QMessageBox.warning(
            self,
            "Delete Profile",
            f"Delete profile '{profile_name}'?\n\nThis cannot be undone.",
            QtWidgets.QMessageBox.StandardButton.Delete |
            QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel
        )
        
        if reply != QtWidgets.QMessageBox.StandardButton.Delete:
            return
        
        try:
            profile_path = self.profiles[profile_name]
            os.remove(profile_path)
            
            del self.profiles[profile_name]
            del self.profileEditors[profile_name]
            
            self.profileTabs.removeTab(index)
            
            index = self.profileSelector.findText(profile_name)
            if index >= 0:
                self.profileSelector.removeItem(index)
            
            QtWidgets.QMessageBox.information(
                self,
                "Deleted",
                f"Profile '{profile_name}' deleted."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Deletion Failed",
                f"Failed to delete profile:\n{e}"
            )

    def updateProfileIndicators(self):
        """Update UI to show which profile is active."""
        self.activeInfoLabel.setText(f"Currently Active: {self.currentProfile}")
        
        # Update star icons on tabs
        for i in range(self.profileTabs.count()):
            profile_name = self.profileTabs.tabText(i)
            if profile_name == self.currentProfile:
                self.profileTabs.setTabIcon(i, QtGui.QIcon('images/star.png'))
            else:
                self.profileTabs.setTabIcon(i, QtGui.QIcon())
        
        # Update selector
        self.profileSelector.setCurrentText(self.currentProfile)

    def closeDialog(self):
        """Handle close button with unsaved changes check."""
        # Check all editors for unsaved changes
        for profile_name, editor in self.profileEditors.items():
            if editor.hasUnsavedChanges():
                reply = QtWidgets.QMessageBox.warning(
                    self,
                    "Unsaved Changes",
                    f"Profile '{profile_name}' has unsaved changes.\n\n"
                    "Are you sure you want to close without saving?",
                    QtWidgets.QMessageBox.StandardButton.Discard |
                    QtWidgets.QMessageBox.StandardButton.Cancel,
                    QtWidgets.QMessageBox.StandardButton.Cancel
                )
                
                if reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                    return
                break
        
        self.close()

    def closeEvent(self, event):
        """Handle window close (X button)."""
        for profile_name, editor in self.profileEditors.items():
            if editor.hasUnsavedChanges():
                reply = QtWidgets.QMessageBox.warning(
                    self,
                    "Unsaved Changes",
                    f"Profile '{profile_name}' has unsaved changes.\n\n"
                    "Are you sure you want to close without saving?",
                    QtWidgets.QMessageBox.StandardButton.Discard |
                    QtWidgets.QMessageBox.StandardButton.Cancel,
                    QtWidgets.QMessageBox.StandardButton.Cancel
                )
                
                if reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                break
        
        event.accept()

    def showScrollableErrorDialog(self, title, message, errors):
        """Show scrollable error dialog."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.resize(700, 500)
        
        layout = QtWidgets.QVBoxLayout()
        
        header = QtWidgets.QLabel(message)
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: bold; padding: 10px;")
        layout.addWidget(header)
        
        summary = QtWidgets.QLabel(f"Found {len(errors)} error(s):")
        summary.setStyleSheet("padding: 5px 10px;")
        layout.addWidget(summary)
        
        error_text = QtWidgets.QTextEdit()
        error_text.setReadOnly(True)
        formatted_errors = "\n\n".join(errors)
        error_text.setPlainText(formatted_errors)
        error_text.setStyleSheet("""
            QTextEdit {
                font-family: monospace;
                font-size: 10pt;
                padding: 10px;
                background-color: #2b2b2b;
                color: #ffffff;
            }
        """)
        layout.addWidget(error_text)
        
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        
        dialog.setLayout(layout)
        dialog.exec()

    def validateConfigSyntax(self, config_text):
        """
        Comprehensive INI validation with element count checking for dynamic sections.
        """
        from app.auxiliary import getAppLogger
        log = getAppLogger()
        
        # Define expected element counts for each section type
        section_element_counts = {
            'HostActions': 2,
            'PortActions': 3,
            'PortTerminalActions': 3,
            'SchedulerSettings': 2,
            'MatchSettings': None
        }
        
        errors = []
        lines = config_text.split('\n')
        current_section = None
        
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Skip empty lines and comments
            if not stripped or stripped.startswith('#') or stripped.startswith(';'):
                continue
            
            # Check for section headers
            if stripped.startswith('['):
                if not stripped.endswith(']'):
                    errors.append(
                        f"❌ Line {line_num}: Unclosed section header\n"
                        f"   Found: {stripped}\n"
                        f"   Fix: Add closing bracket ]"
                    )
                    continue
                
                section_name = stripped[1:-1].strip()
                if not section_name:
                    errors.append(
                        f"❌ Line {line_num}: Empty section header\n"
                        f"   Found: {stripped}\n"
                        f"   Fix: Provide a section name between [ ]"
                    )
                elif ' ' in section_name:
                    errors.append(
                        f"❌ Line {line_num}: Section name contains spaces\n"
                        f"   Found: [{section_name}]\n"
                        f"   Fix: Remove spaces (use CamelCase)"
                    )
                
                current_section = section_name
                log.debug(f"DEBUG: Line {line_num} - Entered section [{current_section}]")
                continue
            
            # Check for key=value pairs
            if '=' in stripped:
                # Extract key and value (split on FIRST equals)
                first_equals_pos = stripped.index('=')
                key = stripped[:first_equals_pos].strip()
                value = stripped[first_equals_pos + 1:].strip()
                
                log.debug(f"DEBUG: Line {line_num} - key: '{key}', value: '{value[:80]}...'")
                
                # Validate key
                if not key:
                    errors.append(
                        f"❌ Line {line_num}: Missing key name before '='\n"
                        f"   Found: {stripped}\n"
                        f"   Fix: Add a key name: key=value"
                    )
                    continue
                
                if '=' in key:
                    errors.append(
                        f"❌ Line {line_num}: Key contains '=' sign\n"
                        f"   Found key: {key}\n"
                        f"   Fix: Key name cannot contain '=' character"
                    )
                    continue
                
                if key.startswith('[') or key.endswith(']'):
                    errors.append(
                        f"❌ Line {line_num}: Key name contains brackets\n"
                        f"   Found: {key}\n"
                        f"   Fix: Did you mean to create a [SectionHeader]?"
                    )
                    continue
                
                # QUOTE VALIDATION
                quote_errors = self.validateQuotes(value, line_num, key)
                if quote_errors:
                    errors.extend(quote_errors)
                    continue
                
                # ELEMENT COUNT VALIDATION for dynamic sections
                if current_section and current_section in section_element_counts:
                    expected_count = section_element_counts[current_section]
                    
                    if expected_count is not None:
                        elements = self.parseCommaSeparated(value)
                        actual_count = len(elements)
                        
                        log.debug(f"DEBUG: Line {line_num} - Section [{current_section}]: "
                                f"expected {expected_count} elements, found {actual_count}")
                        
                        if actual_count != expected_count:
                            errors.append(
                                f"❌ Line {line_num}: Wrong number of elements in [{current_section}]\n"
                                f"   Key: {key}\n"
                                f"   Expected: {expected_count} comma-separated elements\n"
                                f"   Found: {actual_count} elements\n"
                                f"   Value: {value}\n"
                                f"   Fix: Ensure value has exactly {expected_count} comma-separated parts"
                            )
                
                # Check if key-value pair is inside a section
                if current_section is None:
                    errors.append(
                        f"❌ Line {line_num}: Key-value pair outside of any section\n"
                        f"   Found: {stripped}\n"
                        f"   Fix: Add a [SectionName] header before this line"
                    )
            else:
                # No equals sign found
                log.warning(f"DEBUG: Line {line_num} has NO '=' sign: '{stripped}'")
                errors.append(
                    f"❌ Line {line_num}: Invalid syntax - missing '=' sign\n"
                    f"   Found: {stripped}\n"
                    f"   Fix: Lines must be [Section], key=value, or comment (#)"
                )
        
        log.info(f"DEBUG: validateConfigSyntax() found {len(errors)} syntax errors")
        return errors

    def validateQuotes(self, value, line_num, key):
        """
        Validate that quotes are properly balanced and closed.
        Returns list of error messages if invalid.
        """
        errors = []
        
        # Check for unbalanced double quotes
        double_quote_count = value.count('"')
        if double_quote_count % 2 != 0:
            errors.append(
                f"❌ Line {line_num}: Unclosed double quote (\") in value\n"
                f"   Key: {key}\n"
                f"   Value: {value}\n"
                f"   Fix: Close all double quotes - found {double_quote_count} quotes (should be even)"
            )
        
        # Check for unbalanced single quotes
        single_quote_count = value.count("'")
        if single_quote_count % 2 != 0:
            errors.append(
                f"❌ Line {line_num}: Unclosed single quote (') in value\n"
                f"   Key: {key}\n"
                f"   Value: {value}\n"
                f"   Fix: Close all single quotes - found {single_quote_count} quotes (should be even)"
            )
        
        return errors

    def parseCommaSeparated(self, value):
        """
        Parse comma-separated values, treating quoted strings as single elements.
        
        RULES:
        - Commas in quotes don't split: 'a, "b,c"' → ['a', 'b,c']
        - Trailing comma ignored: 'a, b,' → ['a', 'b'] (NOT 3 elements)
        - Explicit empty needs quotes: 'a, b, ""' → ['a', 'b', '']
        """
        from app.auxiliary import getAppLogger
        log = getAppLogger()
        
        elements = []
        current_element = []
        in_quotes = False
        quote_char = None
        
        for char in value:
            if char in ['"', "'"]:
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                    current_element.append(char)
                elif char == quote_char:
                    in_quotes = False
                    quote_char = None
                    current_element.append(char)
                else:
                    current_element.append(char)
            elif char == ',':
                if in_quotes:
                    current_element.append(char)
                else:
                    element_text = ''.join(current_element).strip()
                    elements.append(element_text)
                    current_element = []
            else:
                current_element.append(char)
        
        # Final element: only add if non-empty (trailing comma case)
        final_element = ''.join(current_element).strip()
        if final_element:
            elements.append(final_element)
        
        log.debug(f"DEBUG: Parsed {len(elements)} elements from value")
        return elements

    def validateSettingNames(self, config_text):
        """
        Validate that all setting keys are recognized/expected by Legion.
        Handles dynamic sections like PortActions where keys are tool names.
        """
        from app.auxiliary import getAppLogger
        log = getAppLogger()
        
        # Complete list of valid setting keys by section
        valid_settings = {
            'GeneralSettings': {
                'default-terminal',
                'tool-output-black-background',
                'screenshooter-timeout',
                'web-services',
                'enable-scheduler',
                'enable-scheduler-on-import',
                'max-fast-processes',
                'max-slow-processes',
                'tool-duplication'
            },
            'BruteSettings': {
                'store-cleartext-passwords-on-exit',
                'username-wordlist-path',
                'password-wordlist-path',
                'default-username',
                'default-password',
                'services',
                'no-username-services',
                'no-password-services'
            },
            'ToolSettings': {
                'nmap-path',
                'hydra-path',
                'cutycapt-path',
                'texteditor-path',
                'pyshodan-api-key'
            },
            'StagedNmapSettings': {
                'stage1-ports',
                'stage2-ports',
                'stage3-ports',
                'stage4-ports',
                'stage5-ports',
                'stage6-ports'
            },
            'GUISettings': {
                'process-tab-column-widths',
                'hosts-table-column-widths',
                'service-names-table-column-widths',
                'cves-table-column-widths',
                'scripts-table-column-widths',
                'splitter-sizes',
                'splitter-3-sizes',
                'splitter-2-sizes',
                'main-window-geometry',
                'process-tab-detail',
                'hosts-tab-splitter-sizes',
                'hosts-tab-splitter-2-sizes',
                'hosts-tab-splitter-3-sizes',
                'services-tab-splitter-sizes',
                'services-tab-splitter-2-sizes',
                'services-tab-splitter-3-sizes',
                'tools-tab-splitter-sizes',
                'tools-tab-splitter-2-sizes',
                'tools-tab-splitter-3-sizes',
                'os-tab-splitter-sizes',
                'os-tab-splitter-2-sizes',
                'os-tab-splitter-3-sizes'
            },

            # These sections have dynamic keys (tool names, action names, etc.)
            'HostActions': 'dynamic',
            'PortActions': 'dynamic',
            'PortTerminalActions': 'dynamic',
            'SchedulerSettings': 'dynamic',
            'MatchSettings': 'dynamic'
        }
        
        errors = []
        lines = config_text.split('\n')
        current_section = None
        
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Skip empty and comments
            if not stripped or stripped.startswith('#') or stripped.startswith(';'):
                continue
            
            # Track current section
            if stripped.startswith('[') and stripped.endswith(']'):
                current_section = stripped[1:-1].strip()
                
                # Check if section itself is valid
                if current_section not in valid_settings:
                    log.warning(f"DEBUG: Line {line_num}: Unknown section '{current_section}'")
                    errors.append(
                        f"⚠️  Line {line_num}: Unknown section [{current_section}]\n"
                        f"   This section is not recognized by Legion.\n"
                        f"   Valid sections: {', '.join(sorted(valid_settings.keys()))}"
                    )
                continue
            
            # Check key=value pairs
            if '=' in stripped:
                # Extract key (everything before FIRST equals sign)
                first_equals_pos = stripped.index('=')
                key = stripped[:first_equals_pos].strip()
                
                log.debug(f"DEBUG: Line {line_num} - checking key '{key}' in section '{current_section}'")
                
                if current_section and current_section in valid_settings:
                    expected_keys = valid_settings[current_section]
                    
                    # Skip validation for sections with dynamic keys
                    if expected_keys == 'dynamic':
                        log.debug(f"DEBUG: Line {line_num} - skipping validation (dynamic section)")
                        continue
                    
                    # Check if key is in expected set
                    if key not in expected_keys:
                        log.info(f"DEBUG: Line {line_num}: Invalid key '{key}' in [{current_section}]")
                        
                        # Find similar key names (likely typos)
                        suggestions = []
                        for valid_key in expected_keys:
                            if abs(len(key) - len(valid_key)) <= 2:
                                overlap = sum(1 for c in key if c in valid_key)
                                if overlap >= len(key) - 2:
                                    suggestions.append(valid_key)
                        
                        error_msg = f"❌ Line {line_num}: Unknown setting '{key}' in [{current_section}]\n"
                        if suggestions:
                            error_msg += f"   Did you mean: {', '.join(suggestions)}?"
                        else:
                            error_msg += f"   Valid settings in [{current_section}]:\n"
                            for valid_key in sorted(expected_keys):
                                error_msg += f"     • {valid_key}\n"
                        
                        errors.append(error_msg)
        
        log.debug(f"DEBUG: validateSettingNames() found {len(errors)} invalid settings")
        return errors

    def checkSettingExists(self, config_text, section, key):
        """
        Check if a specific setting exists in the config text.
        """
        lines = config_text.split('\n')
        in_section = False
        
        for line in lines:
            stripped = line.strip()
            
            # Check if we're entering the target section
            if stripped == f'[{section}]':
                in_section = True
                continue
            
            # Check if we're leaving the section
            if in_section and stripped.startswith('['):
                in_section = False
                break
            
            # Check for the key in this section
            if in_section and '=' in stripped:
                line_key = stripped.split('=', 1)[0].strip()
                if line_key == key:
                    return True
        
        return False

