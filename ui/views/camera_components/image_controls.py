import os
os.environ.setdefault('LANGUAGE', 'C')

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, QSettings, QTimer, QCoreApplication
from PyQt6.QtGui import QPainter, QLinearGradient, QColor, QIcon
from ui.widgets.slider_with_scale import SliderWithScale
from ui.widgets.labeled_combo_box import LabeledComboBox
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────── Kody aparatu (stałe, niezależne od języka)

FORMAT_ORDER = ['L', 'M', 'S1', 'RAW + L', 'RAW']

# ALO: pozycje w menu aparatu → kody wewnętrzne
ALO_CODE_MAP = {
    'x3':  'off',
    'x1':  'low',
    'x2':  'high',
    # Wszystko inne (długi string z nawiasem) → 'standard'
}

# Mapowanie: kod WB (z aparatu, LANGUAGE=C) → plik ikony
_WB_ICON_DIR = os.path.join('assets', 'icons', 'wb')

WB_ICON_MAP = {
    'Auto':              'wb_awb.png',
    'AWB White':         'wb_awbw.png',
    'Daylight':          'wb_daylight.png',
    'Shadow':            'wb_shadow.png',
    'Cloudy':            'wb_cloudy.png',
    'Tungsten':          'wb_tungsten.png',
    'Fluorescent':       'wb_fluorescent.png',
    'Flash':             'wb_flash.png',
    'Custom':            'wb_custom.png',
    'Color Temperature': 'wb_user_defined.png',
    # Alternatywne nazwy spotykane na różnych firmware
    'Kelvin':            'wb_user_defined.png',
    'PC-1':              'wb_custom.png',
    'PC-2':              'wb_custom.png',
    'PC-3':              'wb_custom.png',
}


def _wb_icon(code: str):
    """Zwraca QIcon dla kodu WB lub None jeśli brak pliku."""
    filename = WB_ICON_MAP.get(code)
    if not filename:
        return None
    path = os.path.join(_WB_ICON_DIR, filename)
    if not os.path.exists(path):
        return None
    return QIcon(path)


class ColorTempGradient(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(10)
        self.setMinimumWidth(200)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        # Gradient pokazuje efekt na zdjęciu (nie kolor źródła światła):
        # 2500K → obraz zimny/niebieski, 10000K → obraz ciepły/pomarańczowy
        gradient.setColorAt(0.0, QColor(80, 150, 255))
        gradient.setColorAt(0.2, QColor(180, 210, 255))
        gradient.setColorAt(0.5, QColor(255, 255, 255))
        gradient.setColorAt(0.8, QColor(255, 190, 110))
        gradient.setColorAt(1.0, QColor(255, 60, 0))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, self.width(), self.height())


class ImageControls(QWidget):
    """Panel ustawień obrazu: PictureStyle, Quality, ALO, WB, Color Temperature."""

    # Parametry gphoto obsługiwane przez ten panel
    PARAMS = ('picturestyle', 'imageformat', 'alomode', 'whitebalance',
              'colortemperature')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.gphoto = None
        self._settings = QSettings("Grzeza", "SessionsAssistant")

        # Wersja mapowań — zmiana wymusza odświeżenie cache
        SETTINGS_VER = 5
        if self._settings.value("image/_version", 0, type=int) != SETTINGS_VER:
            self._settings.remove("image")
            self._settings.setValue("image/_version", SETTINGS_VER)
            print("Image settings cache cleared (version upgrade)")

        # Mapowania kod→display i display→kod (budowane przy sync)
        self._code_map = {}    # {param: {kod: etykieta}}
        self._display_map = {} # {param: {etykieta: kod}}

        # Kody WB zależne od języka aparatu — ustawiane przy sync
        self._ct_code = None      # kod "Color Temperature" (ostatni w liście)
        self._manual_code = None  # kod "Manual" (przedostatni)

        # Debounce — wysyła tylko ostatnią wartość po 200ms ciszy
        self._pending = {}  # param → value
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._flush_pending)

        self._init_ui()
        self._restore_state()

    # ─────────────────────────── TŁUMACZENIA UI
    # Wszystkie etykiety widoczne przez użytkownika przechodzą przez tr().
    # Kody aparatu (L, x1, Auto, Color Temperature) NIGDY nie są tłumaczone.

    def _tr_format(self, code):
        """Kod formatu → etykieta UI (tłumaczalna)."""
        return {
            'L':       self.tr('Large Fine JPEG'),
            'M':       self.tr('Medium Fine JPEG'),
            'S1':      self.tr('Small Fine JPEG'),
            'RAW + L': self.tr('RAW + Large Fine JPEG'),
            'RAW':     self.tr('RAW'),
        }.get(code, code)

    def _tr_alo(self, code):
        """Kod ALO → etykieta UI (tłumaczalna)."""
        key = ALO_CODE_MAP.get(code, 'standard')
        return {
            'off':      self.tr('Off'),
            'low':      self.tr('Low'),
            'standard': self.tr('Standard'),
            'high':     self.tr('High'),
        }[key]

    def _tr_ct_hint(self, kelvin):
        """Temperatura → opis (tłumaczalny)."""
        presets = {
            2500: self.tr("Candlelight"),
            3200: self.tr("Warm White"),
            4000: self.tr("Cool White"),
            5200: self.tr("Daylight"),
            6500: self.tr("Overcast Sky"),
            8000: self.tr("Blue Sky"),
        }
        for t, label in sorted(presets.items()):
            if abs(kelvin - t) < 250:
                return label
        return self.tr("Custom")

    # ─────────────────────────── UI

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox(self.tr("Image Settings"))
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        inner = QVBoxLayout(group)
        inner.setSpacing(0)

        self.style_combo = LabeledComboBox(self.tr("Picture Style"), [])
        self.format_combo = LabeledComboBox(self.tr("Quality"), [])
        self.alo_combo = LabeledComboBox(self.tr("ALO"), [])
        self.wb_combo = LabeledComboBox(self.tr("WB"), [])

        self.ct_slider = SliderWithScale(
            self.tr("Color Temp (K)"),
            [str(x) for x in range(2500, 10100, 100)]
        )
        self.ct_gradient = ColorTempGradient()
        self.ct_hint = QLabel("")
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

        # Combo → debounce → gphoto
        self.style_combo.currentTextChanged.connect(
            lambda _: self._queue_param('picturestyle'))
        self.format_combo.currentTextChanged.connect(
            lambda _: self._queue_param('imageformat'))
        self.alo_combo.currentTextChanged.connect(
            lambda _: self._queue_param('alomode'))
        self.wb_combo.currentTextChanged.connect(
            lambda _: self._queue_param('whitebalance'))

    # ─────────────────────────── ENABLE/DISABLE

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

    # ─────────────────────────── TŁUMACZENIA KOD↔DISPLAY

    def _translate(self, param, code):
        """Kod aparatu → etykieta UI."""
        if param == 'imageformat':
            return self._tr_format(code)
        if param == 'alomode':
            return self._tr_alo(code)
        # WB, PictureStyle — pass-through (nazwy z aparatu = angielskie)
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

    # ─────────────────────────── IKONY WB

    def _apply_wb_icons(self, codes: list):
        """Ustawia ikony w wb_combo wg kodów aparatu. Wywołać po update_items()."""
        icon_dict = {}
        for code in codes:
            icon = _wb_icon(code)
            if icon:
                display = self._to_display('whitebalance', code)
                icon_dict[display] = icon
        if icon_dict:
            self.wb_combo.set_item_icons(icon_dict)

    # ─────────────────────────── LOGIKA BLOKAD

    def _on_wb_changed(self, display_text):
        """Blokuje CT gdy WB ≠ Color Temperature."""
        code = self._to_code('whitebalance', display_text)
        is_ct = (self._ct_code is not None and code == self._ct_code)
        print(f"WB changed: display='{display_text}' code='{code}' ct_code='{self._ct_code}' is_ct={is_ct}")
        self.ct_slider.setLocked(not is_ct)
        self.ct_gradient.setEnabled(is_ct)
        self.ct_hint.setEnabled(is_ct)

    def _on_format_changed(self, display_text):
        """RAW-only → wyłącza PictureStyle i ALO."""
        code = self._to_code('imageformat', display_text)
        is_raw_only = code in ('RAW', 'cRAW')
        self.style_combo.setEnabled(not is_raw_only)
        self.alo_combo.setEnabled(not is_raw_only)

    def _on_ct_changed(self, value):
        """Aktualizuje hint (natychmiast) i kolejkuje wysyłkę (debounce)."""
        try:
            val = int(value)
            hint = self._tr_ct_hint(val)
            self.ct_hint.setText(f"{self.tr('Info')}: {hint} ({val}K)")
        except Exception:
            pass
        # Debounce — tylko ostatnia wartość trafi do aparatu
        self._pending['colortemperature'] = value
        self._debounce.start()

    # ─────────────────────────── DEBOUNCE + GPHOTO

    def _queue_param(self, param):
        """Kolejkuje wartość combo do wysłania po debounce."""
        combo = self._get_combo(param)
        if not combo:
            return
        display_text = combo.currentText()
        code = self._to_code(param, display_text)
        print(f"SEND {param}: display='{display_text}' → code='{code}'")
        self._pending[param] = code
        self._debounce.start()

    def _flush_pending(self):
        """Wysyła tylko ostatnią wartość każdego parametru."""
        if not self.gphoto:
            self._pending.clear()
            return
        for param, value in self._pending.items():
            self.gphoto.update_camera_param(param, value)
        self._pending.clear()
        self._save_state()

    def _get_combo(self, param):
        return {
            'picturestyle': self.style_combo,
            'imageformat': self.format_combo,
            'alomode': self.alo_combo,
            'whitebalance': self.wb_combo,
        }.get(param)

    # ─────────────────────────── SYNC

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

            # Filtrowanie
            if param == 'imageformat':
                codes = [c for c in FORMAT_ORDER if c in codes]

            if param == 'whitebalance' and len(codes) >= 2:
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
                combo.blockSignals(True)
                combo.update_items(display_items)
                combo.setCurrentText(display_current)
                combo.blockSignals(False)

            # Ikony WB — po update_items (które czyści combo)
            if param == 'whitebalance':
                self._apply_wb_icons(codes)

        # Temperatura kolorów
        ct_data = settings.get('colortemperature')
        if ct_data:
            choices = ct_data.get('choices', [])
            if choices:
                self.ct_slider.update_values(choices)
            current = ct_data.get('current', '')
            if current:
                self.ct_slider.blockSignals(True)
                self.ct_slider.set_value(current)
                self.ct_slider.blockSignals(False)
                try:
                    val = int(current)
                    hint = self._tr_ct_hint(val)
                    self.ct_hint.setText(f"{self.tr('Info')}: {hint} ({val}K)")
                except:
                    pass

        # Nakłada blokady z aktualnymi wartościami
        self._apply_locks()
        self._save_state()

    # ─────────────────────────── ZAPIS/ODCZYT STANU

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

            # Ikony WB przy przywracaniu stanu
            if param == 'whitebalance':
                self._apply_wb_icons(codes)

        # CT
        ct_choices = self._settings.value("image/colortemperature/choices")
        ct_value = self._settings.value("image/colortemperature/value")
        if ct_choices and len(ct_choices) > 1:
            self.ct_slider.update_values(ct_choices)
        if ct_value:
            self.ct_slider.set_value(ct_value)
            try:
                val = int(ct_value)
                hint = self._tr_ct_hint(val)
                self.ct_hint.setText(f"{self.tr('Info')}: {hint} ({val}K)")
            except:
                pass

        self._apply_locks()

    # ─────────────────────────── API

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
