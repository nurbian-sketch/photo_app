#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test parameter_matrix.py z prawdziwym aparatem Canon EOS RP.

Tests:
1. Bulk read z aparatu
2. ParameterCache - load, set, dirty tracking
3. ParameterMatrix - FSM (enable/disable logic)
4. STRICT MODE - sync_to_app_constraints()
5. Bulk write do aparatu
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.parameter_matrix import (
    ParameterMatrix, 
    ParameterCache,
    gphoto2_bulk_read,
    gphoto2_bulk_write,
    PARAM_PATHS
)


def print_separator(title: str):
    """Print section separator"""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)


def test_bulk_read():
    """Test 1: Bulk read from camera"""
    print_separator("TEST 1: BULK READ FROM CAMERA")
    
    paths = list(PARAM_PATHS.values())
    print(f"Reading {len(paths)} parameters in one gphoto2 call...")
    print()
    
    values = gphoto2_bulk_read(paths)
    
    if not values:
        print("❌ FAILED: No values returned")
        return False
    
    print(f"✅ Read {len(values)} parameters:")
    
    # Convert paths back to names
    path_to_name = {v: k for k, v in PARAM_PATHS.items()}
    
    for path, value in values.items():
        name = path_to_name.get(path, path)
        print(f"  {name:25s} = {value}")
    
    return True


def test_cache_load(cache: ParameterCache):
    """Test 2: ParameterCache load from camera"""
    print_separator("TEST 2: PARAMETER CACHE - LOAD FROM CAMERA")
    
    print("Loading all parameters from camera...")
    success = cache.load_from_camera()
    
    if not success:
        print("❌ FAILED: Could not load from camera")
        return False
    
    print("✅ Loaded successfully")
    print()
    print("Current parameters:")
    
    for name in PARAM_PATHS.keys():
        value = cache.get_parameter(name)
        if value is not None:
            print(f"  {name:25s} = {value}")
    
    print()
    print(f"Has changes: {cache.has_changes()}")
    
    return True


def test_matrix_fsm(cache: ParameterCache):
    """Test 3: ParameterMatrix FSM logic"""
    print_separator("TEST 3: PARAMETER MATRIX - FSM LOGIC")
    
    mode = cache.get_parameter('shootingmode')
    fmt = cache.get_parameter('imageformat')
    flash = False  # Default
    
    print(f"Current state:")
    print(f"  Shooting Mode: {mode}")
    print(f"  Image Format:  {fmt}")
    print(f"  Flash:         {flash}")
    print()
    
    matrix = ParameterMatrix(mode, fmt, flash)
    
    print("Parameter availability:")
    print(f"  ISO editable:              {matrix.is_iso_editable()}")
    print(f"  Aperture editable:         {matrix.is_aperture_editable()}")
    print(f"  Shutter editable:          {matrix.is_shutterspeed_editable()}")
    print(f"  EV Compensation editable:  {matrix.is_exposurecompensation_editable()}")
    print(f"  Picture Style editable:    {matrix.is_picturestyle_editable()}")
    print(f"  ALO Mode editable:         {matrix.is_alomode_editable()}")
    
    print()
    print("Constraints:")
    print(f"  ISO choices:               {matrix.get_iso_choices()}")
    print(f"  Shutter choices:           {len(matrix.get_shutterspeed_choices())} values")
    print(f"  Image format choices:      {matrix.get_imageformat_choices()}")
    
    if not matrix.is_aperture_editable():
        print()
        print(f"⚠️  Aperture locked: {matrix.get_tooltip('aperture')}")
    
    if not matrix.is_shutterspeed_editable():
        print()
        print(f"⚠️  Shutter locked: {matrix.get_tooltip('shutterspeed')}")
    
    return matrix


def test_dirty_tracking(cache: ParameterCache):
    """Test 4: Dirty tracking"""
    print_separator("TEST 4: DIRTY TRACKING")
    
    print(f"Initial state - Has changes: {cache.has_changes()}")
    print()
    
    # Make some changes
    print("Making changes:")
    
    old_iso = cache.get_parameter('iso')
    new_iso = '400' if old_iso != '400' else '200'
    cache.set_parameter('iso', new_iso)
    print(f"  ISO: {old_iso} → {new_iso}")
    
    old_wb = cache.get_parameter('whitebalance')
    new_wb = 'Daylight' if old_wb != 'Daylight' else 'Auto'
    cache.set_parameter('whitebalance', new_wb)
    print(f"  WB:  {old_wb} → {new_wb}")
    
    print()
    print(f"After changes - Has changes: {cache.has_changes()}")
    print()
    
    changes = cache.get_bulk_update_dict()
    print(f"Changed parameters ({len(changes)}):")
    for name, value in changes.items():
        print(f"  {name:25s} = {value}")
    
    return True


def test_strict_mode(cache: ParameterCache, matrix: ParameterMatrix):
    """Test 5: STRICT MODE - sync_to_app_constraints()"""
    print_separator("TEST 5: STRICT MODE - SYNC TO APP CONSTRAINTS")
    
    print("Running sync_to_app_constraints()...")
    print()
    
    warnings = cache.sync_to_app_constraints(matrix)
    
    if warnings:
        print(f"Applied {len(warnings)} constraint corrections:")
        for warning in warnings:
            print(f"  {warning}")
    else:
        print("✅ All parameters already within constraints")
    
    print()
    print(f"Has changes after sync: {cache.has_changes()}")
    
    return warnings


def test_rollback(cache: ParameterCache):
    """Test 6: Rollback changes"""
    print_separator("TEST 6: ROLLBACK")
    
    print(f"Before rollback - Has changes: {cache.has_changes()}")
    
    changes_before = cache.get_bulk_update_dict()
    if changes_before:
        print(f"  Changed parameters: {list(changes_before.keys())}")
    
    print()
    print("Rolling back all changes...")
    cache.rollback()
    
    print(f"After rollback - Has changes: {cache.has_changes()}")
    
    return True


def test_bulk_write(cache: ParameterCache):
    """Test 7: Bulk write to camera"""
    print_separator("TEST 7: BULK WRITE TO CAMERA")
    
    changes = cache.get_bulk_update_dict()
    
    if not changes:
        print("No changes to write")
        return True
    
    print(f"Writing {len(changes)} changed parameters to camera...")
    print()
    
    for name, value in changes.items():
        print(f"  {name:25s} → {value}")
    
    print()
    response = input("Commit these changes to camera? (y/n): ").strip().lower()
    
    if response != 'y':
        print("Skipped")
        return False
    
    success = cache.commit_to_camera()
    
    if success:
        print("✅ Written successfully")
        print(f"Has changes after commit: {cache.has_changes()}")
    else:
        print("❌ FAILED to write")
    
    return success


def main():
    """Main test execution"""
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║         PARAMETER MATRIX TEST - Canon EOS RP                     ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    
    # Test 1: Bulk read
    if not test_bulk_read():
        return 1
    
    input("\nPress ENTER to continue...")
    
    # Initialize cache
    cache = ParameterCache()
    
    # Test 2: Cache load
    if not test_cache_load(cache):
        return 1
    
    input("\nPress ENTER to continue...")
    
    # Test 3: Matrix FSM
    matrix = test_matrix_fsm(cache)
    
    input("\nPress ENTER to continue...")
    
    # Test 4: Dirty tracking
    test_dirty_tracking(cache)
    
    input("\nPress ENTER to continue...")
    
    # Test 5: STRICT MODE
    warnings = test_strict_mode(cache, matrix)
    
    input("\nPress ENTER to continue...")
    
    # Test 6: Rollback
    print("\n⚠️  Do you want to test rollback (discard changes)?")
    response = input("Rollback? (y/n): ").strip().lower()
    
    if response == 'y':
        test_rollback(cache)
    else:
        print("Skipped rollback test")
        
        # Test 7: Bulk write
        input("\nPress ENTER to test bulk write...")
        test_bulk_write(cache)
    
    print_separator("ALL TESTS COMPLETED")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
