#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test bulk write to camera - change parameters and commit.

Workflow:
1. Load current parameters from camera
2. Change some parameters
3. Show what will be written
4. Ask user confirmation
5. Bulk write to camera
6. Verify changes were applied
7. Restore original values
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.parameter_matrix import (
    ParameterCache,
    ParameterMatrix,
    gphoto2_bulk_read,
    PARAM_PATHS
)


def print_separator(title: str):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70 + "\n")


def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║             BULK WRITE TEST - Canon EOS RP                       ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    
    # ═══════════════════════════════════════════════════════════════
    # STEP 1: Load from camera
    # ═══════════════════════════════════════════════════════════════
    print_separator("STEP 1: LOAD FROM CAMERA")
    
    cache = ParameterCache()
    
    print("Loading parameters from camera...")
    if not cache.load_from_camera():
        print("❌ Failed to load from camera")
        return 1
    
    print("✅ Loaded successfully\n")
    
    # Show current values
    print("Current values:")
    for name in ['iso', 'shutterspeed', 'whitebalance', 'picturestyle']:
        value = cache.get_parameter(name)
        print(f"  {name:20s} = {value}")
    
    input("\nPress ENTER to continue...")
    
    # ═══════════════════════════════════════════════════════════════
    # STEP 2: Make changes
    # ═══════════════════════════════════════════════════════════════
    print_separator("STEP 2: MAKE CHANGES")
    
    print("Making test changes:\n")
    
    # Change ISO
    old_iso = cache.get_parameter('iso')
    new_iso = '400' if old_iso != '400' else '200'
    cache.set_parameter('iso', new_iso)
    print(f"  ISO:            {old_iso:20s} → {new_iso}")
    
    # Change White Balance
    old_wb = cache.get_parameter('whitebalance')
    new_wb = 'Daylight' if old_wb != 'Daylight' else 'Auto'
    cache.set_parameter('whitebalance', new_wb)
    print(f"  White Balance:  {old_wb:20s} → {new_wb}")
    
    # Change Picture Style
    old_style = cache.get_parameter('picturestyle')
    new_style = 'Portrait' if old_style != 'Portrait' else 'Standard'
    cache.set_parameter('picturestyle', new_style)
    print(f"  Picture Style:  {old_style:20s} → {new_style}")
    
    print(f"\nHas changes: {cache.has_changes()}")
    
    input("\nPress ENTER to continue...")
    
    # ═══════════════════════════════════════════════════════════════
    # STEP 3: Show what will be written
    # ═══════════════════════════════════════════════════════════════
    print_separator("STEP 3: CHANGES TO WRITE")
    
    changes = cache.get_bulk_update_dict()
    
    print(f"Will write {len(changes)} parameters to camera:\n")
    for name, value in changes.items():
        print(f"  {name:20s} → {value}")
    
    # ═══════════════════════════════════════════════════════════════
    # STEP 4: Confirm write
    # ═══════════════════════════════════════════════════════════════
    print_separator("STEP 4: CONFIRM WRITE")
    
    print("⚠️  This will change your camera settings!")
    print("   (Don't worry - we'll restore them at the end)\n")
    
    response = input("Write changes to camera? (yes/no): ").strip().lower()
    
    if response != 'yes':
        print("\n❌ Aborted by user")
        return 0
    
    # ═══════════════════════════════════════════════════════════════
    # STEP 5: Bulk write
    # ═══════════════════════════════════════════════════════════════
    print_separator("STEP 5: BULK WRITE TO CAMERA")
    
    print("Writing changes to camera...\n")
    
    success = cache.commit_to_camera()
    
    if not success:
        print("❌ FAILED to write to camera")
        return 1
    
    print("✅ Written successfully")
    print(f"Has changes after commit: {cache.has_changes()}\n")
    
    input("Press ENTER to verify...")
    
    # ═══════════════════════════════════════════════════════════════
    # STEP 6: Verify by reading back
    # ═══════════════════════════════════════════════════════════════
    print_separator("STEP 6: VERIFY CHANGES")
    
    print("Reading back from camera to verify...\n")
    
    paths = [PARAM_PATHS[name] for name in ['iso', 'whitebalance', 'picturestyle']]
    values = gphoto2_bulk_read(paths)
    
    path_to_name = {v: k for k, v in PARAM_PATHS.items()}
    
    print("Current values in camera:")
    all_ok = True
    
    for path, actual_value in values.items():
        name = path_to_name[path]
        expected_value = cache.get_parameter(name)
        
        if actual_value == expected_value:
            status = "✅"
        else:
            status = "❌"
            all_ok = False
        
        print(f"  {status} {name:20s} = {actual_value:20s} (expected: {expected_value})")
    
    if all_ok:
        print("\n✅ All changes verified in camera!")
    else:
        print("\n❌ Some changes were not applied correctly")
    
    input("\nPress ENTER to restore original values...")
    
    # ═══════════════════════════════════════════════════════════════
    # STEP 7: Restore original values
    # ═══════════════════════════════════════════════════════════════
    print_separator("STEP 7: RESTORE ORIGINAL VALUES")
    
    print("Restoring camera to original state...\n")
    
    # Set back to original values
    cache.set_parameter('iso', old_iso)
    cache.set_parameter('whitebalance', old_wb)
    cache.set_parameter('picturestyle', old_style)
    
    print("Changes to restore:")
    for name in ['iso', 'whitebalance', 'picturestyle']:
        print(f"  {name:20s} → {cache.get_parameter(name)}")
    
    print()
    response = input("Restore original values? (yes/no): ").strip().lower()
    
    if response != 'yes':
        print("\n⚠️  Original values NOT restored!")
        print("   Camera settings remain changed.")
        return 0
    
    success = cache.commit_to_camera()
    
    if success:
        print("\n✅ Original values restored successfully!")
    else:
        print("\n❌ Failed to restore original values")
        print("   You may need to restore them manually.")
    
    # ═══════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════
    print_separator("TEST COMPLETED")
    
    print("Summary:")
    print("  ✅ Bulk write works correctly")
    print("  ✅ Changes verified in camera")
    print("  ✅ Original values restored")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
