"""
Panel sterowania autofokusem Canon EOS RP.
Parametry: focusmode, afmethod, continuousaf.
Architektura: kody aparatu ↔ etykiety UI (tr()-ready).
"""
import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QSizePolicy
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QIcon
from ui.widgets.labeled_combo_box import LabeledComboBox
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────── Stałe

# focusmode: aparat pokazuje tylko aktualny w choices — hardcode
FOCUSMODE_ALL = ['One Shot', 'AI Servo']

# afmethod: kody aparatu → klucze tłumaczeń
AFMETHOD_KEYS = {
    'LiveFace':                    'face_tracking',
    'LiveSpotAF':                  'spot_af',
    'Live':                        'one_point_af',
    'LiveSingleExpandCross':       'expand_cross',
    'LiveSingleExpandSurround':    'expand_around',
    'LiveZone':                    'zone_af',
}

# ─────────────────────────── Ikony AF

_AF_ICON_DIR = os.path.join('assets', 'icons', 'af')

# Mapowanie: display text (po tr()) → plik ikony
# Dla focusmode i afmethod — używamy display text jako klucza,
# bo tr() może się zmienić → osobne dykty per param po translacji.
# Zamiast tego mapujemy KOD → plik (bezpieczniejsze).
AF_METHOD_ICON_MAP = {
    'LiveFace':                 'af_face_tracking.png',
    'LiveSpotAF':               'af_spot.png',
    'Live':                     'af_1point.png',
    'LiveSingleExpandCross':    'af_expand_cross.png',
    'LiveSingleExpandSurround': 'af_expand_around.png',
    'LiveZone':                 'af_zone.png',
}

FOCUSMODE_ICON_MAP = {
    'One Shot': 'af_one_shot.png',
    'AI Servo': 'af_ai_servo.png',
}


def _af_icon(icon_map: dict, code: str):
    """Zwraca QIcon dla kodu AF lub None jeśli brak pliku."""
    filename = icon_map.get(code)
    if not filename:
        return None
    path = os.path.join(_AF_ICON_DIR, filename)
    if not os.path.exists(path):
        return None
    return QIcon(path)


class AutofocusControls(QWidget):
    """Panel sterowania AF: tryb, metoda, continuous AF."""

    PARAMS = ('focusmode', 'afmethod', 'continuousaf')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.gphoto = None
        self._settings = QSettings("Grzeza", "SessionsAssistant")

        # Mapowania kod↔display (budowane przy sync)
        self._code_map = {}
        self._display_map = {}

        # Debounce
        self._pending = {}
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._flush_pending)

        self._init_ui()
        self._restore_state()

    # ─────────────────────────── TŁUMACZENIA UI

    def _tr_focusmode(self, code):
        return {
            'One Shot': self.tr('One Shot'),
            'AI Servo': self.tr('AI Servo'),
        }.get(code, code)

    def _tr_afmethod(self, code):
        key = AFMETHOD_KEYS.get(code)
        if not key:
            return code
        return {
            'face_tracking':  self.tr('Face + Tracking'),
            'spot_af':        self.tr('Spot AF'),
            'one_point_af':   self.tr('1-Point AF'),
            'expand_cross':   self.tr('Expand AF: Cross'),
            'expand_around':  self.tr('Expand AF: Around'),
            'zone_af':        self.tr('Zone AF'),
        }.get(key, code)

    # ─────────────────────────── UI

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox(self.tr("Focus Settings"))
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        inner = QVBoxLayout(group)
        inner.setSpacing(0)

        self.focus_combo = LabeledComboBox(self.tr("Focus Mode"), [])
        self.af_combo = LabeledComboBox(self.tr("AF Method"), [])
        self.cont_combo = LabeledComboBox(self.tr("Continuous AF"), [])

        inner.addWidget(self.focus_combo)
        inner.addStretch(1)
        inner.addWidget(self.af_combo)
        inner.addStretch(1)
        inner.addWidget(self.cont_combo)
        layout.addWidget(group, 1)

        # Sygnały combo → debounce
        self.focus_combo.currentTextChanged.connect(
            lambda _: self._queue_param('focusmode'))
        self.af_combo.currentTextChanged.connect(
            lambda _: self._queue_param('afmethod'))
        self.cont_combo.currentTextChanged.connect(
            lambda _: self._queue_param('continuousaf'))

    # ─────────────────────────── KOD↔DISPLAY

    def _translate(self, param, code):
        if param == 'focusmode':
            return self._tr_focusmode(code)
        if param == 'afmethod':
            return self._tr_afmethod(code)
        return code

    def _build_maps(self, param, codes):
        c2d = {}
        d2c = {}
        for code in codes:
            display = self._translate(param, code)
            c2d[code] = display
            d2c[display] = code
        self._code_map[param] = c2d
        self._display_map[param] = d2c

    def _to_code(self, param, display_text):
        return self._display_map.get(param, {}).get(display_text, display_text)

    def _to_display(self, param, code):
        return self._code_map.get(param, {}).get(code, code)

    # ─────────────────────────── IKONY AF

    def _apply_af_icons(self, param: str, codes: list):
        """Ustawia ikony w combo wg kodów aparatu. Wywołać po update_items()."""
        if param == 'afmethod':
            icon_map = AF_METHOD_ICON_MAP
        elif param == 'focusmode':
            icon_map = FOCUSMODE_ICON_MAP
        else:
            return

        icon_dict = {}
        for code in codes:
            icon = _af_icon(icon_map, code)
            if icon:
                display = self._to_display(param, code)
                icon_dict[display] = icon

        if icon_dict:
            combo = self._get_combo(param)
            if combo:
                combo.set_item_icons(icon_dict)

    # ─────────────────────────── DEBOUNCE + GPHOTO

    def _queue_param(self, param):
        combo = self._get_combo(param)
        if not combo:
            return
        display_text = combo.currentText()
        code = self._to_code(param, display_text)
        print(f"AF SEND {param}: display='{display_text}' → code='{code}'")
        self._pending[param] = code
        self._debounce.start()

    def _flush_pending(self):
        if not self.gphoto:
            self._pending.clear()
            return
        for param, value in self._pending.items():
            self.gphoto.update_camera_param(param, value)
        self._pending.clear()
        self._save_state()

    def _get_combo(self, param):
        return {
            'focusmode': self.focus_combo,
            'afmethod': self.af_combo,
            'continuousaf': self.cont_combo,
        }.get(param)

    # ─────────────────────────── SYNC

    def sync_with_camera(self, settings):
        if not settings:
            return

        for param in self.PARAMS:
            data = settings.get(param)
            if not data:
                continue

            codes = data.get('choices', [])
            current = data.get('current', '')

            if param == 'focusmode':
                codes = FOCUSMODE_ALL

            print(f"AF SYNC {param}: current='{current}', codes={codes}")

            self._build_maps(param, codes)
            display_items = [self._to_display(param, c) for c in codes]
            display_current = self._to_display(param, current)

            combo = self._get_combo(param)
            if combo:
                combo.blockSignals(True)
                combo.update_items(display_items)
                combo.setCurrentText(display_current)
                combo.blockSignals(False)

            # Ikony AF method i Focus Mode
            if param in ('afmethod', 'focusmode'):
                self._apply_af_icons(param, codes)

        self._save_state()

    # ─────────────────────────── ZAPIS/ODCZYT

    def _save_state(self):
        for param in self.PARAMS:
            combo = self._get_combo(param)
            if combo and combo.count() > 0:
                codes = []
                for i in range(combo.count()):
                    text = combo.combo.itemText(i)
                    codes.append(self._to_code(param, text))
                current_code = self._to_code(param, combo.currentText())
                self._settings.setValue(f"af/{param}/codes", codes)
                self._settings.setValue(f"af/{param}/current", current_code)

    def _restore_state(self):
        for param in self.PARAMS:
            codes = self._settings.value(f"af/{param}/codes")
            current = self._settings.value(f"af/{param}/current")
            if not codes or len(codes) < 1:
                continue

            if param == 'focusmode':
                codes = FOCUSMODE_ALL

            self._build_maps(param, codes)
            display_items = [self._to_display(param, c) for c in codes]
            display_current = self._to_display(param, current) if current else ''

            combo = self._get_combo(param)
            if combo:
                combo.update_items(display_items)
                if display_current:
                    combo.setCurrentText(display_current)

            # Ikony AF method i Focus Mode przy przywracaniu stanu
            if param in ('afmethod', 'focusmode'):
                self._apply_af_icons(param, codes)

    # ─────────────────────────── API

    def get_settings(self):
        result = {}
        for param in self.PARAMS:
            combo = self._get_combo(param)
            if combo and combo.count() > 0:
                result[param] = self._to_code(param, combo.currentText())
        return result
