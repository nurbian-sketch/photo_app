#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collect ALL camera parameters for ParameterMatrix implementation.
Comprehensive scan of Canon EOS RP settings.
"""

import subprocess
import json
from datetime import datetime


PARAMS = {
    # === SHOOTING MODE ===
    'autoexposuremode': '/main/capturesettings/autoexposuremode',
    
    # === EXPOSURE TRIANGLE ===
    'iso': '/main/imgsettings/iso',
    'aperture': '/main/capturesettings/aperture',
    'shutterspeed': '/main/capturesettings/shutterspeed',
    'exposurecompensation': '/main/capturesettings/exposurecompensation',
    
    # === WHITE BALANCE ===
    'whitebalance': '/main/imgsettings/whitebalance',
    'colortemperature': '/main/imgsettings/colortemperature',
    
    # === IMAGE SETTINGS ===
    'imageformat': '/main/imgsettings/imageformat',
    'picturestyle': '/main/capturesettings/picturestyle',
    
    # === AUTO FOCUS ===
    'afmethod': '/main/capturesettings/afmethod',
    'continuousaf': '/main/capturesettings/continuousaf',
    
    # === DRIVE & OTHER ===
    'drivemode': '/main/capturesettings/drivemode',
    'alomode': '/main/capturesettings/alomode',  # Auto Lighting Optimizer
}


def run_gphoto2(args):
    """Run gphoto2 command and return output"""
    cmd = ['gphoto2'] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout
    except Exception as e:
        return f"ERROR: {e}"


def parse_config(output):
    """Parse gphoto2 --get-config output"""
    lines = output.strip().split('\n')
    
    data = {
        'label': None,
        'readonly': None,
        'type': None,
        'current': None,
        'choices': []
    }
    
    for line in lines:
        if line.startswith('Label:'):
            data['label'] = line.split(':', 1)[1].strip()
        elif line.startswith('Readonly:'):
            data['readonly'] = int(line.split(':', 1)[1].strip())
        elif line.startswith('Type:'):
            data['type'] = line.split(':', 1)[1].strip()
        elif line.startswith('Current:'):
            data['current'] = line.split(':', 1)[1].strip()
        elif line.startswith('Choice:'):
            # Format: "Choice: 0 value"
            parts = line.split(None, 2)
            if len(parts) >= 3:
                data['choices'].append(parts[2])
    
    return data


def bulk_read_parameters(param_dict):
    """
    Read multiple parameters in one gphoto2 call.
    
    Args:
        param_dict: Dict of {param_name: param_path}
        
    Returns:
        Dict of {param_name: parsed_data}
    """
    # Build args list
    args = []
    for path in param_dict.values():
        args.extend(['--get-config', path])
    
    # Single gphoto2 call
    output = run_gphoto2(args)
    
    # Split by "END\n" - each section is one parameter
    sections = output.split('END\n')
    
    results = {}
    param_names = list(param_dict.keys())
    
    for i, section in enumerate(sections):
        if not section.strip():
            continue
            
        if i >= len(param_names):
            break
            
        # Parse this section
        data = parse_config(section + '\nEND')
        param_name = param_names[i]
        results[param_name] = data
    
    return results


def set_mode(mode):
    """Set shooting mode"""
    output = run_gphoto2(['--set-config', f'/main/capturesettings/autoexposuremode={mode}'])
    return '*** Error ***' not in output


def collect_mode_parameters(mode):
    """Collect all parameters for one shooting mode using BULK READ"""
    import time
    
    print(f"\n{'='*60}")
    print(f"📸 MODE: {mode}")
    print(f"{'='*60}")
    
    # Prepare params dict (without autoexposuremode)
    params_to_read = {k: v for k, v in PARAMS.items() if k != 'autoexposuremode'}
    
    # BULK READ - all parameters in one gphoto2 call!
    print(f"  📦 Bulk reading {len(params_to_read)} parameters...")
    results = bulk_read_parameters(params_to_read)
    
    # Print results
    for param_name in params_to_read.keys():
        data = results.get(param_name)
        
        if not data or data['label'] is None:
            print(f"  {param_name:25s} ❌ FAILED")
            continue
        
        num_choices = len(data['choices'])
        readonly_str = "🔒 RO" if data['readonly'] else "✅ RW"
        
        # Check if locked (1 choice = current value)
        is_locked = num_choices == 1 and data['choices'][0] == data['current']
        lock_str = "🔒 LOCKED" if is_locked else f"{num_choices:3d} choices"
        
        # Add metadata
        data['num_choices'] = num_choices
        data['is_locked'] = is_locked
        
        print(f"  {param_name:25s} {readonly_str} | {lock_str:15s} | current: {data['current']}")
    
    return results


def collect_all_modes():
    """Collect parameters for all shooting modes with BULK READ and delays"""
    import time
    
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     Canon EOS RP - Full Parameter Scan (All Modes)      ║")
    print("║              BULK READ + Stabilization Delays            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    
    # All required modes - with delays should work fine
    MODES = ['Manual', 'AV', 'TV', 'P']
    
    all_results = {}
    
    for mode in MODES:
        # Set mode
        print(f"\n🔄 Setting mode to: {mode}")
        if not set_mode(mode):
            print(f"❌ Failed to set mode: {mode}")
            continue
        
        # STABILIZATION DELAY - let camera settle
        print(f"⏱️  Waiting 2 seconds for camera stabilization...")
        time.sleep(2)
        
        # Collect parameters (BULK READ)
        mode_data = collect_mode_parameters(mode)
        all_results[mode] = mode_data
    
    return all_results


def print_summary(all_results):
    """Print summary comparing all modes"""
    print("\n" + "="*60)
    print("📊 COMPARISON ACROSS MODES")
    print("="*60)
    
    # Get all parameter names
    param_names = set()
    for mode_data in all_results.values():
        param_names.update(mode_data.keys())
    
    param_names = sorted(param_names)
    
    for param in param_names:
        print(f"\n{param.upper()}:")
        
        locked_in = []
        editable_in = []
        
        for mode, mode_data in all_results.items():
            data = mode_data.get(param)
            if data:
                num_choices = len(data['choices'])
                is_locked = num_choices == 1 and data['choices'][0] == data['current']
                
                if is_locked:
                    locked_in.append(mode)
                else:
                    editable_in.append(f"{mode}({num_choices})")
        
        if locked_in:
            print(f"  🔒 Locked in: {', '.join(locked_in)}")
        if editable_in:
            print(f"  ✅ Editable in: {', '.join(editable_in)}")


def save_results(all_results, filename="full_parameters.json"):
    """Save results to JSON file"""
    output = {
        'camera_model': 'Canon EOS RP',
        'collected_at': datetime.now().isoformat(),
        'modes': list(all_results.keys()),
        'matrix': all_results
    }
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Results saved to: {filename}")


def main():
    # Collect all parameters for all modes
    all_results = collect_all_modes()
    
    # Print summary
    print_summary(all_results)
    
    # Save to JSON
    save_results(all_results)
    
    print("\n" + "="*60)
    print("✅ DONE!")
    print("="*60)
    print()
    print("⚠️  IMPORTANT: Disconnect USB first, then turn off camera!")
    print()
    
    return 0


if __name__ == "__main__":
    exit(main())
