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

import os
import shutil
import subprocess
import tempfile

from app.shell.Shell import Shell


class DefaultShell(Shell):
    def copy(self, source: str, destination: str) -> None:
        shutil.copyfile(source, destination)

    def move(self, source: str, destination: str) -> None:
        shutil.move(source, destination)

    def directoryOrFileExists(self, path: str) -> bool:
        return os.path.exists(path)

    def get_current_working_directory(self) -> str:
        return str(subprocess.check_output("echo $PWD", shell=True)[:-1].decode()) + '/'

    def create_directory_recursively(self, directory: str):
        os.makedirs(directory)

    def remove_file(self, file_path: str) -> None:
        os.remove(file_path)

    def remove_directory(self, directory: str) -> None:
        shutil.rmtree(directory)

    def create_temporary_directory(self, prefix: str, suffix: str, directory: str):
        return tempfile.mkdtemp(prefix=prefix, suffix=suffix, dir=directory)

    def create_named_temporary_file(self, prefix: str, suffix: str, directory: str, delete_on_close: bool):
        return tempfile.NamedTemporaryFile(prefix=prefix, suffix=suffix, dir=directory, delete=delete_on_close)

    def isDirectory(self, name: str) -> bool:
        return os.path.isdir(name)

    def isFile(self, name: str) -> bool:
        return os.path.isfile(name)
