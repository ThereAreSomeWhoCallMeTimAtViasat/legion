"""
LEGION (https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion)
Author: Tim McLean (Viasat, Inc.)
Copyright (c) 2025-2026 Viasat, Inc.
Copyright (c) 2025 Shane William Scott (original Legion)

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful, but
    WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
    General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.

THIS SOFTWARE IS PROVIDED BY VIASAT, INC. "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES ARE DISCLAIMED. IN NO EVENT SHALL VIASAT, INC. BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE.
"""

from abc import ABC, abstractmethod


class Shell(ABC):
    @abstractmethod
    def get_current_working_directory(self) -> str:
        pass

    @abstractmethod
    def remove_file(self, file_path: str) -> None:
        pass

    @abstractmethod
    def remove_directory(self, directory: str) -> None:
        pass

    @abstractmethod
    def create_temporary_directory(self, prefix: str, suffix: str, directory: str):
        pass

    @abstractmethod
    def create_directory_recursively(self, directory: str):
        pass

    @abstractmethod
    def create_named_temporary_file(self, prefix: str, suffix: str, directory: str, delete_on_close: bool):
        pass

    @abstractmethod
    def move(self, source: str, destination: str) -> None:
        pass

    @abstractmethod
    def copy(self, source: str, destination: str) -> None:
        pass

    @abstractmethod
    def isDirectory(self, name: str) -> bool:
        pass

    @abstractmethod
    def isFile(self, name: str) -> bool:
        pass

    @abstractmethod
    def directoryOrFileExists(self, path: str) -> bool:
        pass
