"""
Parameter Matrix and Cache for Canon EOS RP camera control.

ParameterMatrix: FSM (Finite State Machine) controlling parameter availability
                 based on shooting mode, image format, and flash state.

ParameterCache: Tracks parameter changes with dirty flag and bulk operations.
"""

import json
import subprocess
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════

# gphoto2 parameter paths
PARAM_PATHS = {
    'shootingmode': '/main/capturesettings/autoexposuremode',
    'iso': '/main/imgsettings/iso',
    'aperture': '/main/capturesettings/aperture',
    'shutterspeed': '/main/capturesettings/shutterspeed',
    'exposurecompensation': '/main/capturesettings/exposurecompensation',
    'whitebalance': '/main/imgsettings/whitebalance',
    'colortemperature': '/main/imgsettings/colortemperature',
    'imageformat': '/main/imgsettings/imageformat',
    'picturestyle': '/main/capturesettings/picturestyle',
    'afmethod': '/main/capturesettings/afmethod',
    'continuousaf': '/main/capturesettings/continuousaf',
    'drivemode': '/main/capturesettings/drivemode',
    'alomode': '/main/capturesettings/alomode',
}

# Application constraints (user requirements)
APP_CONSTRAINTS = {
    'iso': ['100', '200', '400', '800'],  # Max 800
    'shutterspeed_no_flash': [  # 1/10 - 1/1000
        '1/1000', '1/800', '1/640', '1/500', '1/400', '1/320', '1/250',
        '1/200', '1/160', '1/125', '1/100', '1/80', '1/60', '1/50',
        '1/40', '1/30', '1/25', '1/20', '1/15', '1/13', '1/10'
    ],
    'shutterspeed_with_flash': [  # 1/60 - 1/125
        '1/125', '1/100', '1/80', '1/60'
    ],
    'imageformat': ['RAW', 'Large Fine JPEG', 'RAW+Large Fine JPEG'],
    'shootingmode': ['Manual', 'AV', 'TV', 'P'],
}

# Default values for initialization
DEFAULT_VALUES = {
    'shootingmode': 'Manual',
    'iso': '800',
    'aperture': '2.8',
    'shutterspeed': '1/125',
    'exposurecompensation': '0',
    'whitebalance': 'Auto',
    'colortemperature': '5500',
    'imageformat': 'Large Fine JPEG',
    'picturestyle': 'Standard',
    'afmethod': 'LiveFace',
    'continuousaf': 'On',
    'drivemode': 'Timer 2 sec',
    'alomode': 'Standard (disabled in manual exposure)',
}


# ═══════════════════════════════════════════════════════════════
# CAMERA COMMUNICATION
# ═══════════════════════════════════════════════════════════════

def gphoto2_bulk_read(param_paths: List[str]) -> Dict[str, str]:
    """
    Bulk read multiple parameters from camera.
    
    Args:
        param_paths: List of gphoto2 paths to read
        
    Returns:
        Dict of {path: current_value}
    """
    args = []
    for path in param_paths:
        args.extend(['--get-config', path])
    
    try:
        result = subprocess.run(
            ['gphoto2'] + args,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Parse output - split by "END\n"
        sections = result.stdout.split('END\n')
        values = {}
        
        for i, section in enumerate(sections):
            if not section.strip() or i >= len(param_paths):
                continue
            
            # Extract "Current:" value
            for line in section.split('\n'):
                if line.startswith('Current:'):
                    value = line.split(':', 1)[1].strip()
                    values[param_paths[i]] = value
                    break
        
        return values
        
    except Exception as e:
        print(f"gphoto2_bulk_read error: {e}")
        return {}


def gphoto2_bulk_write(params: Dict[str, str]) -> bool:
    """
    Bulk write multiple parameters to camera.
    
    Args:
        params: Dict of {path: value}
        
    Returns:
        True if successful
    """
    args = []
    for path, value in params.items():
        args.extend(['--set-config', f'{path}={value}'])
    
    try:
        result = subprocess.run(
            ['gphoto2'] + args,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Check for errors
        if '*** Error ***' in result.stdout or '*** Error ***' in result.stderr:
            print(f"gphoto2_bulk_write error: {result.stderr}")
            return False
        
        return True
        
    except Exception as e:
        print(f"gphoto2_bulk_write error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# PARAMETER MATRIX (FSM)
# ═══════════════════════════════════════════════════════════════

class ParameterMatrix:
    """
    Finite State Machine controlling parameter availability.
    
    State depends on:
    - shooting_mode: Manual/AV/TV/P
    - image_format: RAW/JPEG/RAW+JPEG
    - flash_enabled: True/False
    """
    
    def __init__(self, shooting_mode: str, image_format: str, flash_enabled: bool):
        """
        Initialize FSM.
        
        Args:
            shooting_mode: Manual/AV/TV/P
            image_format: RAW/JPEG/RAW+JPEG
            flash_enabled: True/False
        """
        self.shooting_mode = shooting_mode
        self.image_format = image_format
        self.flash_enabled = flash_enabled
    
    # ───────────────────────────────────────────────────────────
    # EDITABILITY CHECKS
    # ───────────────────────────────────────────────────────────
    
    def is_iso_editable(self) -> bool:
        """ISO always editable in all modes"""
        return True
    
    def is_aperture_editable(self) -> bool:
        """Aperture editable in Manual and Av modes only"""
        return self.shooting_mode in ['Manual', 'AV']
    
    def is_shutterspeed_editable(self) -> bool:
        """Shutter speed editable in Manual and Tv modes only"""
        return self.shooting_mode in ['Manual', 'TV']
    
    def is_exposurecompensation_editable(self) -> bool:
        """EV compensation editable in Av/Tv/P (not Manual)"""
        return self.shooting_mode in ['AV', 'TV', 'P']
    
    def is_whitebalance_editable(self) -> bool:
        """White balance always editable"""
        return True
    
    def is_colortemperature_editable(self) -> bool:
        """Color temp always editable"""
        return True
    
    def is_imageformat_editable(self) -> bool:
        """Image format always editable"""
        return True
    
    def is_picturestyle_editable(self) -> bool:
        """
        Picture style editable, but warn if RAW.
        (Picture Style has no effect on RAW files)
        """
        return True  # Editable, but UI should show warning for RAW
    
    def is_afmethod_editable(self) -> bool:
        """AF method always editable"""
        return True
    
    def is_continuousaf_editable(self) -> bool:
        """Continuous AF always editable"""
        return True
    
    def is_alomode_editable(self) -> bool:
        """Auto Lighting Optimizer always editable"""
        return True
    
    # ───────────────────────────────────────────────────────────
    # CHOICES GETTERS (with application constraints)
    # ───────────────────────────────────────────────────────────
    
    def get_iso_choices(self) -> List[str]:
        """ISO limited to max 800"""
        return APP_CONSTRAINTS['iso']
    
    def get_shutterspeed_choices(self) -> List[str]:
        """Shutter speed depends on flash state"""
        if self.flash_enabled:
            return APP_CONSTRAINTS['shutterspeed_with_flash']
        else:
            return APP_CONSTRAINTS['shutterspeed_no_flash']
    
    def get_imageformat_choices(self) -> List[str]:
        """Image format simplified to 3 choices"""
        return APP_CONSTRAINTS['imageformat']
    
    def get_shootingmode_choices(self) -> List[str]:
        """Shooting modes we support"""
        return APP_CONSTRAINTS['shootingmode']
    
    # ───────────────────────────────────────────────────────────
    # STATE QUERIES
    # ───────────────────────────────────────────────────────────
    
    def should_warn_picturestyle_for_raw(self) -> bool:
        """Should we warn user that Picture Style won't affect RAW?"""
        return 'RAW' in self.image_format and 'JPEG' not in self.image_format
    
    def get_tooltip(self, param: str) -> Optional[str]:
        """
        Get tooltip explaining why parameter is locked.
        
        Args:
            param: Parameter name
            
        Returns:
            Tooltip string or None if editable
        """
        if param == 'aperture' and not self.is_aperture_editable():
            return "🔒 Aperture controlled by camera in Tv/P mode"
        
        if param == 'shutterspeed' and not self.is_shutterspeed_editable():
            return "🔒 Shutter speed controlled by camera in Av/P mode"
        
        if param == 'exposurecompensation' and not self.is_exposurecompensation_editable():
            return "🔒 Exposure compensation not available in Manual mode"
        
        if param == 'picturestyle' and self.should_warn_picturestyle_for_raw():
            return "⚠️ Picture Style has no effect on RAW files (saved in EXIF only)"
        
        return None


# ═══════════════════════════════════════════════════════════════
# PARAMETER CACHE (Dirty Tracking)
# ═══════════════════════════════════════════════════════════════

class ParameterCache:
    """
    Tracks camera parameter changes with dirty flag.
    
    Supports:
    - Bulk read from camera
    - Bulk write (only changed parameters)
    - Rollback to original state
    - Commit (make current state the new baseline)
    """
    
    def __init__(self):
        """Initialize empty cache"""
        self._original: Dict[str, str] = {}  # Baseline from camera
        self._current: Dict[str, str] = {}   # Current state (with changes)
        self._dirty = False
    
    # ───────────────────────────────────────────────────────────
    # CAMERA SYNC
    # ───────────────────────────────────────────────────────────
    
    def load_from_camera(self) -> bool:
        """
        Load current values from camera (bulk read).
        
        Returns:
            True if successful
        """
        paths = list(PARAM_PATHS.values())
        values = gphoto2_bulk_read(paths)
        
        if not values:
            return False
        
        # Convert path->value to name->value
        self._original = {}
        for name, path in PARAM_PATHS.items():
            if path in values:
                self._original[name] = values[path]
        
        self._current = deepcopy(self._original)
        self._dirty = False
        
        return True
    
    def load_from_dict(self, values: Dict[str, str]):
        """
        Load values from dictionary (for testing/initialization).
        
        Args:
            values: Dict of {param_name: value}
        """
        self._original = deepcopy(values)
        self._current = deepcopy(values)
        self._dirty = False
    
    def commit_to_camera(self) -> bool:
        """
        Write changed parameters to camera (bulk write).
        
        Returns:
            True if successful
        """
        if not self._dirty:
            return True  # Nothing to do
        
        # Get only changed parameters
        changes = self.get_bulk_update_dict()
        
        if not changes:
            return True
        
        # Convert name->value to path->value
        params_to_write = {}
        for name, value in changes.items():
            if name in PARAM_PATHS:
                params_to_write[PARAM_PATHS[name]] = value
        
        # Bulk write
        success = gphoto2_bulk_write(params_to_write)
        
        if success:
            # Update baseline
            self._original = deepcopy(self._current)
            self._dirty = False
        
        return success
    
    # ───────────────────────────────────────────────────────────
    # PARAMETER ACCESS
    # ───────────────────────────────────────────────────────────
    
    def get_parameter(self, name: str, default: Any = None) -> Any:
        """Get current parameter value"""
        return self._current.get(name, default)
    
    def set_parameter(self, name: str, value: Any) -> bool:
        """
        Set parameter value (marks as dirty if changed).
        
        Args:
            name: Parameter name
            value: New value
            
        Returns:
            True if value changed
        """
        old_value = self._current.get(name)
        
        if old_value == value:
            return False  # No change
        
        self._current[name] = value
        
        # Check if dirty
        self._dirty = any(
            self._original.get(k) != v
            for k, v in self._current.items()
        )
        
        return True
    
    # ───────────────────────────────────────────────────────────
    # STATE QUERIES
    # ───────────────────────────────────────────────────────────
    
    def has_changes(self) -> bool:
        """Check if there are unsaved changes"""
        return self._dirty
    
    def get_bulk_update_dict(self) -> Dict[str, str]:
        """
        Get only changed parameters.
        
        Returns:
            Dict of {param_name: new_value} for changed params only
        """
        changes = {}
        for name, new_value in self._current.items():
            original_value = self._original.get(name)
            if original_value != new_value:
                changes[name] = new_value
        
        return changes
    
    def rollback(self):
        """Discard changes and restore original values"""
        self._current = deepcopy(self._original)
        self._dirty = False
    
    def commit(self):
        """Make current state the new baseline (without writing to camera)"""
        self._original = deepcopy(self._current)
        self._dirty = False
    
    # ───────────────────────────────────────────────────────────
    # STRICT MODE SYNC
    # ───────────────────────────────────────────────────────────
    
    def sync_to_app_constraints(self, matrix: ParameterMatrix) -> List[str]:
        """
        STRICT MODE: Force camera parameters to match app constraints.
        
        Args:
            matrix: Current ParameterMatrix state
            
        Returns:
            List of warning messages about changes made
        """
        warnings = []
        
        # 1. Shooting Mode - must be M/Av/Tv/P
        mode = self.get_parameter('shootingmode')
        if mode not in APP_CONSTRAINTS['shootingmode']:
            self.set_parameter('shootingmode', DEFAULT_VALUES['shootingmode'])
            warnings.append(f"⚠️ Changed shooting mode from '{mode}' to 'Manual' (unsupported mode)")
        
        # 2. ISO - must be <= 800
        iso = self.get_parameter('iso')
        if iso not in APP_CONSTRAINTS['iso']:
            # Find closest valid ISO
            valid_isos = APP_CONSTRAINTS['iso']
            try:
                iso_int = int(iso) if iso != 'Auto' else 800
                closest = min(valid_isos, key=lambda x: abs(int(x) - iso_int))
                self.set_parameter('iso', closest)
                warnings.append(f"⚠️ Changed ISO from {iso} to {closest} (limited to max 800)")
            except:
                self.set_parameter('iso', DEFAULT_VALUES['iso'])
                warnings.append(f"⚠️ Changed ISO from {iso} to {DEFAULT_VALUES['iso']}")
        
        # 3. Shutter Speed - must be in sensible range
        shutter = self.get_parameter('shutterspeed')
        valid_shutters = matrix.get_shutterspeed_choices()
        if shutter not in valid_shutters and shutter != 'auto':
            # Use default
            self.set_parameter('shutterspeed', DEFAULT_VALUES['shutterspeed'])
            warnings.append(f"⚠️ Changed shutter speed from {shutter} to {DEFAULT_VALUES['shutterspeed']}")
        
        # 4. Image Format - must be RAW/JPEG/RAW+JPEG
        fmt = self.get_parameter('imageformat')
        if fmt not in APP_CONSTRAINTS['imageformat']:
            # Default to JPEG
            self.set_parameter('imageformat', DEFAULT_VALUES['imageformat'])
            warnings.append(f"⚠️ Changed image format from '{fmt}' to 'Large Fine JPEG'")
        
        # 5. Drive Mode - must be Timer 2 sec (for remote)
        drive = self.get_parameter('drivemode')
        if drive != 'Timer 2 sec':
            self.set_parameter('drivemode', 'Timer 2 sec')
            warnings.append(f"⚠️ Changed drive mode from '{drive}' to 'Timer 2 sec' (required for remote)")
        
        # 6. Continuous AF - should be On (for 230V power)
        caf = self.get_parameter('continuousaf')
        if caf != 'On':
            self.set_parameter('continuousaf', 'On')
            warnings.append(f"⚠️ Changed Continuous AF to 'On' (recommended for studio use)")
        
        return warnings


# ═══════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def load_camera_matrix_json(json_path: str = "full_parameters.json") -> Dict:
    """
    Load camera matrix data from JSON file.
    
    Args:
        json_path: Path to full_parameters.json
        
    Returns:
        Dict with camera capabilities
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load {json_path}: {e}")
        return {}
