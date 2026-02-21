#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Camera Matrix Collector for Canon EOS RP
Zbiera dostępność i wartości parametrów dla różnych trybów fotografowania.

Workflow:
1. Automatycznie zmienia tryb przez USB
2. Dla każdego trybu sprawdza wszystkie parametry
3. Zapisuje do JSON: camera_matrix.json

Usage:
    python3 collect_camera_matrix.py
"""

import subprocess
import json
import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime


# ═══════════════════════════════════════════════════════════════
# KONFIGURACJA
# ═══════════════════════════════════════════════════════════════

PARAMS = {
    'iso': '/main/imgsettings/iso',
    'aperture': '/main/capturesettings/aperture',
    'shutterspeed': '/main/capturesettings/shutterspeed',
    'whitebalance': '/main/imgsettings/whitebalance',
    'colortemperature': '/main/imgsettings/colortemperature',
    'exposurecompensation': '/main/capturesettings/exposurecompensation',
    'picturestyle': '/main/capturesettings/picturestyle',
    'focusmode': '/main/capturesettings/focusmode',
    'drivemode': '/main/capturesettings/drivemode',
    'imageformat': '/main/imgsettings/imageformat',
}

MODES = ['Manual', 'AV', 'TV', 'P', 'Auto']

MODE_PATH = '/main/capturesettings/autoexposuremode'


# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class ParameterInfo:
    """Informacja o parametrze aparatu"""
    label: str
    readonly: int
    param_type: str
    current: str
    choices: List[str]
    
    def is_locked(self) -> bool:
        """Parametr zablokowany = ma tylko 1 choice równy current"""
        return len(self.choices) == 1 and self.choices[0] == self.current
    
    def is_auto_only(self) -> bool:
        """Parametr w trybie auto-only"""
        return len(self.choices) == 1 and self.choices[0] == "auto"


# ═══════════════════════════════════════════════════════════════
# GPHOTO2 COMMUNICATION
# ═══════════════════════════════════════════════════════════════

def run_gphoto2(args: List[str]) -> str:
    """
    Uruchamia gphoto2 i zwraca output.
    
    Args:
        args: Lista argumentów dla gphoto2
        
    Returns:
        Output z stdout
    """
    cmd = ['gphoto2'] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        print(f"⚠️  Timeout dla komendy: {' '.join(cmd)}")
        return ""
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return ""


def parse_config_output(output: str) -> Optional[ParameterInfo]:
    """
    Parsuje output z --get-config.
    
    Format:
        Label: ISO Speed
        Readonly: 0
        Type: RADIO
        Current: 800
        Choice: 0 Auto
        Choice: 1 100
        ...
        END
    
    Returns:
        ParameterInfo lub None jeśli parsing się nie powiódł
    """
    lines = output.strip().split('\n')
    
    label = None
    readonly = None
    param_type = None
    current = None
    choices = []
    
    for line in lines:
        if line.startswith('Label:'):
            label = line.split(':', 1)[1].strip()
        elif line.startswith('Readonly:'):
            readonly = int(line.split(':', 1)[1].strip())
        elif line.startswith('Type:'):
            param_type = line.split(':', 1)[1].strip()
        elif line.startswith('Current:'):
            current = line.split(':', 1)[1].strip()
        elif line.startswith('Choice:'):
            # Format: "Choice: 0 100" lub "Choice: 0 auto"
            match = re.match(r'Choice:\s+\d+\s+(.+)', line)
            if match:
                choices.append(match.group(1))
    
    if label and readonly is not None and param_type and current is not None:
        return ParameterInfo(
            label=label,
            readonly=readonly,
            param_type=param_type,
            current=current,
            choices=choices
        )
    
    return None


def get_parameter_info(path: str) -> Optional[ParameterInfo]:
    """
    Pobiera informacje o parametrze.
    
    Args:
        path: Ścieżka parametru (np. /main/imgsettings/iso)
        
    Returns:
        ParameterInfo lub None
    """
    output = run_gphoto2(['--get-config', path])
    return parse_config_output(output)


def set_parameter(path: str, value: str) -> bool:
    """
    Ustawia wartość parametru.
    
    Args:
        path: Ścieżka parametru
        value: Wartość do ustawienia
        
    Returns:
        True jeśli sukces
    """
    output = run_gphoto2(['--set-config', f'{path}={value}'])
    return '*** Error ***' not in output


def get_current_mode() -> Optional[str]:
    """Pobiera aktualny tryb fotografowania"""
    info = get_parameter_info(MODE_PATH)
    return info.current if info else None


def set_mode(mode: str) -> bool:
    """Ustawia tryb fotografowania"""
    return set_parameter(MODE_PATH, mode)


# ═══════════════════════════════════════════════════════════════
# MATRIX COLLECTION
# ═══════════════════════════════════════════════════════════════

def collect_mode_data(mode: str) -> Dict[str, dict]:
    """
    Zbiera dane dla jednego trybu.
    
    Args:
        mode: Nazwa trybu (Manual, AV, TV, P, Auto)
        
    Returns:
        Dict z danymi parametrów
    """
    print(f"\n{'='*60}")
    print(f"📸 Collecting data for mode: {mode}")
    print(f"{'='*60}")
    
    # Ustaw tryb
    if not set_mode(mode):
        print(f"❌ Failed to set mode: {mode}")
        return {}
    
    # Sprawdź czy się udało
    current = get_current_mode()
    if current != mode:
        print(f"⚠️  Warning: Expected {mode}, got {current}")
    
    # Zbierz dane dla wszystkich parametrów
    mode_data = {}
    
    for param_name, param_path in PARAMS.items():
        info = get_parameter_info(param_path)
        
        if info:
            mode_data[param_name] = {
                'label': info.label,
                'readonly': info.readonly,
                'type': info.param_type,
                'current': info.current,
                'choices': info.choices,
                'num_choices': len(info.choices),
                'is_locked': info.is_locked(),
                'is_auto_only': info.is_auto_only(),
            }
            
            # Status
            status = "🔒 LOCKED" if info.is_locked() else f"✅ {len(info.choices)} choices"
            print(f"  {param_name:20s} {status:20s} current={info.current}")
        else:
            print(f"  {param_name:20s} ❌ Failed to read")
            mode_data[param_name] = None
    
    return mode_data


def collect_full_matrix() -> Dict[str, dict]:
    """
    Zbiera pełną macierz dla wszystkich trybów.
    
    Returns:
        Dict z danymi dla każdego trybu
    """
    matrix = {}
    
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     Canon EOS RP - Camera Matrix Collector              ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print("🔍 Collecting parameter availability for all shooting modes...")
    
    # Sprawdź połączenie
    current_mode = get_current_mode()
    if not current_mode:
        print("❌ ERROR: Cannot communicate with camera!")
        print("   Check USB connection and try again.")
        return {}
    
    print(f"✅ Camera connected, current mode: {current_mode}")
    
    # Zbierz dane dla każdego trybu
    for mode in MODES:
        mode_data = collect_mode_data(mode)
        matrix[mode] = mode_data
    
    return matrix


# ═══════════════════════════════════════════════════════════════
# ANALYSIS & REPORTING
# ═══════════════════════════════════════════════════════════════

def analyze_matrix(matrix: Dict[str, dict]):
    """Analizuje macierz i wyświetla podsumowanie"""
    print("\n" + "="*60)
    print("📊 MATRIX ANALYSIS")
    print("="*60)
    
    # Dla każdego parametru - pokaż w jakich trybach jest locked
    for param_name in PARAMS.keys():
        print(f"\n{param_name.upper()}:")
        
        locked_in = []
        editable_in = []
        
        for mode in MODES:
            param_data = matrix.get(mode, {}).get(param_name)
            if param_data:
                if param_data['is_locked'] or param_data['is_auto_only']:
                    locked_in.append(mode)
                else:
                    editable_in.append(mode)
        
        if locked_in:
            print(f"  🔒 Locked in: {', '.join(locked_in)}")
        if editable_in:
            print(f"  ✅ Editable in: {', '.join(editable_in)}")


def save_matrix(matrix: Dict[str, dict], filename: str = "camera_matrix.json"):
    """Zapisuje macierz do pliku JSON"""
    output = {
        'camera_model': 'Canon EOS RP',
        'collected_at': datetime.now().isoformat(),
        'modes': MODES,
        'parameters': list(PARAMS.keys()),
        'matrix': matrix
    }
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Matrix saved to: {filename}")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    """Main entry point"""
    # Zbierz macierz
    matrix = collect_full_matrix()
    
    if not matrix:
        print("\n❌ Failed to collect matrix data!")
        return 1
    
    # Analiza
    analyze_matrix(matrix)
    
    # Zapisz
    save_matrix(matrix)
    
    print("\n" + "="*60)
    print("✅ DONE!")
    print("="*60)
    print()
    print("⚠️  IMPORTANT: Disconnect USB first, then turn off camera!")
    print()
    
    return 0


if __name__ == "__main__":
    exit(main())
