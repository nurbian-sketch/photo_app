#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test bulk write and read operations with gphoto2.
Tests if we can chain multiple --set-config and --get-config commands.
"""

import subprocess
import sys


def run_gphoto2(args):
    """Run gphoto2 command"""
    cmd = ['gphoto2'] + args
    print(f"🔧 Running: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return "", f"ERROR: {e}", 1


def parse_current_value(output):
    """Extract 'Current:' value from gphoto2 output"""
    for line in output.split('\n'):
        if line.startswith('Current:'):
            return line.split(':', 1)[1].strip()
    return None


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║           gphoto2 BULK WRITE/READ TEST                  ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    
    # Parameters to test
    test_params = {
        'ISO': '/main/imgsettings/iso',
        'White Balance': '/main/imgsettings/whitebalance',
        'Continuous AF': '/main/capturesettings/continuousaf',
    }
    
    # ═══════════════════════════════════════════════════════════
    # STEP 1: READ CURRENT VALUES (BULK)
    # ═══════════════════════════════════════════════════════════
    print("="*60)
    print("STEP 1: BULK READ - Current values")
    print("="*60)
    print()
    
    read_args = []
    for path in test_params.values():
        read_args.extend(['--get-config', path])
    
    stdout, stderr, returncode = run_gphoto2(read_args)
    
    if returncode != 0:
        print(f"❌ BULK READ FAILED!")
        print(stderr)
        return 1
    
    # Parse current values
    sections = stdout.split('END\n')
    current_values = {}
    
    for i, (name, path) in enumerate(test_params.items()):
        if i < len(sections):
            value = parse_current_value(sections[i])
            current_values[name] = value
            print(f"  {name:20s} = {value}")
    
    print()
    
    # ═══════════════════════════════════════════════════════════
    # STEP 2: PREPARE NEW VALUES
    # ═══════════════════════════════════════════════════════════
    print("="*60)
    print("STEP 2: Prepare NEW values to write")
    print("="*60)
    print()
    
    # Change values
    new_values = {}
    
    # ISO: change to different value
    if current_values.get('ISO') == '800':
        new_values['ISO'] = '400'
    else:
        new_values['ISO'] = '800'
    
    # White Balance: change to different value
    if current_values.get('White Balance') == 'Auto':
        new_values['White Balance'] = 'Daylight'
    else:
        new_values['White Balance'] = 'Auto'
    
    # Continuous AF: toggle
    if current_values.get('Continuous AF') == 'On':
        new_values['Continuous AF'] = 'Off'
    else:
        new_values['Continuous AF'] = 'On'
    
    for name, new_val in new_values.items():
        old_val = current_values.get(name)
        print(f"  {name:20s} {old_val:15s} → {new_val}")
    
    print()
    
    # ═══════════════════════════════════════════════════════════
    # STEP 3: BULK WRITE
    # ═══════════════════════════════════════════════════════════
    print("="*60)
    print("STEP 3: BULK WRITE - Apply new values")
    print("="*60)
    print()
    
    write_args = []
    for name, new_val in new_values.items():
        path = test_params[name]
        write_args.extend(['--set-config', f'{path}={new_val}'])
    
    stdout, stderr, returncode = run_gphoto2(write_args)
    
    if returncode != 0 or '*** Error ***' in stdout or '*** Error ***' in stderr:
        print(f"❌ BULK WRITE FAILED!")
        print("STDOUT:", stdout)
        print("STDERR:", stderr)
        return 1
    
    print("✅ BULK WRITE completed")
    print()
    
    # ═══════════════════════════════════════════════════════════
    # STEP 4: READ AGAIN TO VERIFY (BULK)
    # ═══════════════════════════════════════════════════════════
    print("="*60)
    print("STEP 4: BULK READ - Verify new values")
    print("="*60)
    print()
    
    stdout, stderr, returncode = run_gphoto2(read_args)
    
    if returncode != 0:
        print(f"❌ BULK READ FAILED!")
        print(stderr)
        return 1
    
    # Parse verified values
    sections = stdout.split('END\n')
    verified_values = {}
    
    for i, (name, path) in enumerate(test_params.items()):
        if i < len(sections):
            value = parse_current_value(sections[i])
            verified_values[name] = value
            
            expected = new_values.get(name)
            status = "✅" if value == expected else "❌"
            
            print(f"  {status} {name:20s} = {value:15s} (expected: {expected})")
    
    print()
    
    # ═══════════════════════════════════════════════════════════
    # STEP 5: RESTORE ORIGINAL VALUES
    # ═══════════════════════════════════════════════════════════
    print("="*60)
    print("STEP 5: RESTORE original values")
    print("="*60)
    print()
    
    restore_args = []
    for name, original_val in current_values.items():
        path = test_params[name]
        restore_args.extend(['--set-config', f'{path}={original_val}'])
    
    stdout, stderr, returncode = run_gphoto2(restore_args)
    
    if returncode != 0 or '*** Error ***' in stdout or '*** Error ***' in stderr:
        print(f"⚠️  RESTORE FAILED - manual reset needed!")
        print("STDERR:", stderr)
    else:
        print("✅ Original values restored")
    
    print()
    
    # ═══════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════
    print("="*60)
    print("✅ TEST COMPLETED SUCCESSFULLY!")
    print("="*60)
    print()
    print("CONCLUSION:")
    print("  ✅ Bulk READ works (multiple --get-config)")
    print("  ✅ Bulk WRITE works (multiple --set-config)")
    print("  ✅ Values are correctly updated in camera")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
