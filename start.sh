#!/bin/bash

# Sessions Assistant - Quick Start Script
# Szybkie uruchomienie aplikacji po refaktorze

echo "======================================"
echo "  Sessions Assistant - Quick Start"
echo "======================================"
echo ""

# Sprawdź czy jesteśmy w odpowiednim katalogu
if [ ! -f "main.py" ]; then
    echo "❌ Błąd: Nie znaleziono main.py"
    echo "Uruchom ten skrypt z katalogu sessions_assistant/"
    exit 1
fi

# Sprawdź zależności
echo "🔍 Sprawdzam zależności..."

if ! python3 -c "import PyQt6" 2>/dev/null; then
    echo "❌ PyQt6 nie jest zainstalowane"
    echo "Instaluję zależności..."
    pip install -r requirements.txt
    
    if [ $? -ne 0 ]; then
        echo "❌ Nie udało się zainstalować zależności"
        exit 1
    fi
    echo "✅ Zależności zainstalowane"
else
    echo "✅ PyQt6 jest zainstalowane"
fi

# Sprawdź gphoto2
echo ""
echo "🔍 Sprawdzam gphoto2..."
if ! command -v gphoto2 &> /dev/null; then
    echo "⚠️  gphoto2 nie jest zainstalowane"
    echo "Zainstaluj przez: sudo apt install gphoto2"
    echo ""
    read -p "Kontynuować mimo braku gphoto2? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ gphoto2 jest zainstalowane"
fi

# Menu wyboru
echo ""
echo "======================================"
echo "Wybierz tryb uruchomienia:"
echo "======================================"
echo "1) Normalny (z oknem)"
echo "2) Pełny ekran"
echo "3) Debug mode"
echo ""
read -p "Wybór (1-3): " choice

case $choice in
    1)
        echo ""
        echo "🚀 Uruchamiam w trybie normalnym..."
        python3 main.py
        ;;
    2)
        echo ""
        echo "🚀 Uruchamiam w trybie pełnoekranowym..."
        python3 main.py --fullscreen
        ;;
    3)
        echo ""
        echo "🚀 Uruchamiam w trybie debug..."
        python3 -u main.py 2>&1 | tee debug_output.log
        echo ""
        echo "📄 Logi zapisane w: debug_output.log"
        ;;
    *)
        echo "❌ Nieprawidłowy wybór"
        exit 1
        ;;
esac

# Pożegnanie
echo ""
echo "======================================"
echo "Dziękuję za użycie Sessions Assistant!"
echo "======================================"
