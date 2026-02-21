from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QPainter, QLinearGradient, QColor
from ui.widgets.slider_with_scale import SliderWithScale
from ui.widgets.labeled_combo_box import LabeledComboBox
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────── Mapowania kodów aparatu → etykiety UI

FORMAT_MAP = {
    'L':       'Large Fine JPEG',
    'M':       'Medium Fine JPEG',
    'S1':      'Small Fine JPEG',
    'RAW + L': 'RAW + Large Fine JPEG',
    'RAW':     'RAW',
}
FORMAT_ORDER = ['L', 'M', 'S1', 'RAW + L', 'RAW']

# ALO: kolejność na aparacie: x3=Off, x1=Low, Standard=Standard, x2=High
ALO_KNOWN = {
    'x3':  'Off',
    'x1':  'Low',
    'x2':  'High',
}

# WB: Manual = przedostatni, Color Temperature = ostatni (niezależnie od języka)
# Identyfikujemy po pozycji w liście choices, nie po nazwie


class ColorTempGradient(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(10)
        self.setMinimumWidth(200)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0.0, QColor(255, 60, 0))
        gradient.setColorAt(0.2, QColor(255, 190, 110))
        gradient.setColorAt(0.5, QColor(255, 255, 255))
        gradient.setColorAt(0.8, QColor(180, 210, 255))
        gradient.setColorAt(1.0, QColor(80, 150, 255))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, self.width(), self.height())


class ImageControls(QWidget):
    # Parametry gphoto obsługiwane przez ten panel
    PARAMS = ('picturestyle', 'imageformat', 'alomode', 'whitebalance',
              'colortemperature')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.gphoto = None
        self._settings = QSettings("Grzeza", "SessionsAssistant")

        # Wersja mapowań — zmiana wymusza odświeżenie cache
        SETTINGS_VER = 3
        if self._settings.value("image/_version", 0, type=int) != SETTINGS_VER:
            # Czyścimy stary cache (np. polskie nazwy)
            self._settings.remove("image")
            self._settings.setValue("image/_version", SETTINGS_VER)
            print("Image settings cache cleared (version upgrade)")

        # Mapowania kod→display i display→kod (budowane przy sync)
        self._code_map = {}    # {param: {kod: etykieta}}
        self._display_map = {} # {param: {etykieta: kod}}

        # Kody WB zależne od języka aparatu — ustawiane przy sync
        self._ct_code = None      # kod "Color Temperature" (ostatni w liście)
        self._manual_code = None  # kod "Manual" (przedostatni)

        self.temp_presets = {
            2500: "Candlelight", 3200: "Warm White", 4000: "Cool White",
            5200: "Daylight", 6500: "Overcast Sky", 8000: "Blue Sky"
        }

        self._init_ui()
        self._restore_state()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Image Settings")
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        inner = QVBoxLayout(group)
        inner.setSpacing(0)

        self.style_combo = LabeledComboBox("Picture Style", [])
        self.format_combo = LabeledComboBox("Quality", [])
        self.alo_combo = LabeledComboBox("ALO", [])
        self.wb_combo = LabeledComboBox("WB", [])

        self.ct_slider = SliderWithScale(
            "Color Temp (K)",
            [str(x) for x in range(2500, 10100, 100)]
        )
        self.ct_gradient = ColorTempGradient()
        self.ct_hint = QLabel("Info: Custom")
        self.ct_hint.setStyleSheet("color: #aaa; font-style: italic; margin-top: 2px;")

        widgets = [self.style_combo, self.format_combo, self.alo_combo,
                   self.wb_combo, self.ct_slider, self.ct_gradient, self.ct_hint]
        for i, w in enumerate(widgets):
            if i > 0:
                inner.addStretch(1)
            inner.addWidget(w)
        layout.addWidget(group, 1)

        # Sygnały
        self.wb_combo.currentTextChanged.connect(self._on_wb_changed)
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self.ct_slider.valueChanged.connect(self._on_ct_changed)

        # Combo → gphoto
        self.style_combo.currentTextChanged.connect(
            lambda _: self._send_param('picturestyle'))
        self.format_combo.currentTextChanged.connect(
            lambda _: self._send_param('imageformat'))
        self.alo_combo.currentTextChanged.connect(
            lambda _: self._send_param('alomode'))
        self.wb_combo.currentTextChanged.connect(
            lambda _: self._send_param('whitebalance'))

    # ─────────────────────────────── ENABLE/DISABLE

    def setEnabled(self, enabled):
        """Nadpisanie: po włączeniu ponownie nakłada logikę blokad."""
        print(f"ImageControls.setEnabled({enabled})")
        super().setEnabled(enabled)
        if enabled:
            self._apply_locks()

    def _apply_locks(self):
        """Nakłada blokady CT i RAW wg aktualnych wartości."""
        self._on_wb_changed(self.wb_combo.currentText())
        self._on_format_changed(self.format_combo.currentText())

    # ─────────────────────────────── TŁUMACZENIA

    def _translate(self, param, code):
        """Kod aparatu → etykieta UI."""
        if param == 'imageformat':
            return FORMAT_MAP.get(code, code)
        if param == 'alomode':
            # x1/x2/x3 mamy w mapie, reszta = Standard
            return ALO_KNOWN.get(code, 'Standard')
        # WB, PictureStyle — nazwy z aparatu, bez zmian
        return code

    def _build_maps(self, param, codes):
        """Buduje mapowania kod↔display dla danego parametru."""
        c2d = {}
        d2c = {}
        for code in codes:
            display = self._translate(param, code)
            c2d[code] = display
            d2c[display] = code
        self._code_map[param] = c2d
        self._display_map[param] = d2c

    def _to_code(self, param, display_text):
        """Display → kod aparatu."""
        return self._display_map.get(param, {}).get(display_text, display_text)

    def _to_display(self, param, code):
        """Kod → display."""
        return self._code_map.get(param, {}).get(code, code)

    # ─────────────────────────────── LOGIKA BLOKAD

    def _on_wb_changed(self, display_text):
        """Blokuje CT gdy WB ≠ Color Temperature."""
        code = self._to_code('whitebalance', display_text)
        is_ct = (self._ct_code is not None and code == self._ct_code)
        print(f"WB changed: display='{display_text}' code='{code}' ct_code='{self._ct_code}' is_ct={is_ct}")
        self.ct_slider.setLocked(not is_ct)
        self.ct_gradient.setEnabled(is_ct)
        self.ct_hint.setEnabled(is_ct)
        self._save_state()

    def _on_format_changed(self, display_text):
        """RAW-only → wyłącza PictureStyle i ALO."""
        code = self._to_code('imageformat', display_text)
        is_raw_only = code in ('RAW', 'cRAW')
        self.style_combo.setEnabled(not is_raw_only)
        self.alo_combo.setEnabled(not is_raw_only)
        self._save_state()

    def _on_ct_changed(self, value):
        """Aktualizuje hint i wysyła do aparatu."""
        try:
            val = int(value)
            hint = "Custom"
            for t, l in sorted(self.temp_presets.items()):
                if abs(val - t) < 250:
                    hint = l
                    break
            self.ct_hint.setText(f"Info: {hint} ({val}K)")
        except Exception:
            pass
        if self.gphoto:
            self.gphoto.update_camera_param('colortemperature', value)
        self._save_state()

    # ─────────────────────────────── GPHOTO

    def _send_param(self, param):
        """Wysyła aktualną wartość combo do aparatu."""
        if not self.gphoto:
            return
        combo = self._get_combo(param)
        if not combo:
            return
        display_text = combo.currentText()
        code = self._to_code(param, display_text)
        print(f"SEND {param}: display='{display_text}' → code='{code}'")
        self.gphoto.update_camera_param(param, code)
        self._save_state()

    def _get_combo(self, param):
        return {
            'picturestyle': self.style_combo,
            'imageformat': self.format_combo,
            'alomode': self.alo_combo,
            'whitebalance': self.wb_combo,
        }.get(param)

    # ─────────────────────────────── SYNC

    def sync_with_camera(self, settings):
        """Aktualizuje UI z danych aparatu."""
        if not settings:
            return

        for param in ('picturestyle', 'whitebalance', 'alomode', 'imageformat'):
            data = settings.get(param)
            if not data:
                continue

            codes = data.get('choices', [])
            current = data.get('current', '')
            print(f"SYNC {param}: current='{current}', raw_codes={codes[:5]}...")

            # Filtrowanie do dozwolonych wartości
            if param == 'imageformat':
                codes = [c for c in FORMAT_ORDER if c in codes]

            if param == 'whitebalance' and len(codes) >= 2:
                # Ostatni = Color Temperature, przedostatni = Manual
                self._ct_code = codes[-1]
                self._manual_code = codes[-2]
                codes = [c for c in codes if c != self._manual_code]
                print(f"WB: ct_code='{self._ct_code}', manual='{self._manual_code}' (blocked)")

            if not codes:
                logger.warning(f"SYNC {param}: brak kodów po filtrowaniu!")
                continue

            self._build_maps(param, codes)
            display_items = [self._to_display(param, c) for c in codes]
            display_current = self._to_display(param, current)
            print(f"SYNC {param}: display={display_items}, selected='{display_current}'")

            combo = self._get_combo(param)
            if combo:
                combo.update_items(display_items)
                combo.setCurrentText(display_current)

        # Temperatura kolorów
        ct_data = settings.get('colortemperature')
        if ct_data:
            choices = ct_data.get('choices', [])
            if choices:
                self.ct_slider.update_values(choices)
            current = ct_data.get('current', '')
            if current:
                self.ct_slider.set_value(current)

        # Nakłada blokady z aktualnymi wartościami
        self._apply_locks()
        self._save_state()

    # ─────────────────────────────── ZAPIS/ODCZYT STANU

    def _save_state(self):
        for param in ('picturestyle', 'imageformat', 'alomode', 'whitebalance'):
            combo = self._get_combo(param)
            if combo and combo.count() > 0:
                # Zapisujemy kody, nie etykiety — niezależne od języka
                codes = []
                for i in range(combo.count()):
                    text = combo.combo.itemText(i)
                    codes.append(self._to_code(param, text))
                current_code = self._to_code(param, combo.currentText())
                self._settings.setValue(f"image/{param}/codes", codes)
                self._settings.setValue(f"image/{param}/current", current_code)
        # CT
        self._settings.setValue("image/colortemperature/value",
                                self.ct_slider.get_value())
        self._settings.setValue("image/colortemperature/choices",
                                self.ct_slider.values)

    def _restore_state(self):
        """Przywraca ostatni zapisany stan (wyłącznie wizualnie)."""
        for param in ('picturestyle', 'imageformat', 'alomode', 'whitebalance'):
            codes = self._settings.value(f"image/{param}/codes")
            current = self._settings.value(f"image/{param}/current")
            if not codes or len(codes) < 1:
                continue

            if param == 'imageformat':
                codes = [c for c in FORMAT_ORDER if c in codes]

            if param == 'whitebalance' and len(codes) >= 2:
                self._ct_code = codes[-1]
                self._manual_code = codes[-2]
                codes = [c for c in codes if c != self._manual_code]

            self._build_maps(param, codes)
            display_items = [self._to_display(param, c) for c in codes]
            display_current = self._to_display(param, current) if current else ''

            combo = self._get_combo(param)
            if combo:
                combo.update_items(display_items)
                if display_current:
                    combo.setCurrentText(display_current)

        # CT
        ct_choices = self._settings.value("image/colortemperature/choices")
        ct_value = self._settings.value("image/colortemperature/value")
        if ct_choices and len(ct_choices) > 1:
            self.ct_slider.update_values(ct_choices)
        if ct_value:
            self.ct_slider.set_value(ct_value)

        # Nakłada blokady
        self._apply_locks()

    # ─────────────────────────────── API

    def get_settings(self):
        """Zwraca aktualny stan jako dict kodów aparatu."""
        result = {}
        for param in ('picturestyle', 'imageformat', 'alomode', 'whitebalance'):
            combo = self._get_combo(param)
            if combo and combo.count() > 0:
                result[param] = self._to_code(param, combo.currentText())
        ct = self.ct_slider.get_value()
        if ct:
            result['colortemperature'] = ct
        return result
