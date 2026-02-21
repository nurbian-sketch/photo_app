#!/bin/bash

usage() {
    echo "Użycie:"
    echo "  $0 disable   - wyłącza automatyczne montowanie aparatów"
    echo "  $0 enable    - przywraca automatyczne montowanie aparatów"
    exit 1
}

if [ $# -ne 1 ]; then
    usage
fi

case "$1" in
    disable)
        echo "== Wyłączanie automatycznego montowania aparatów =="
        echo "Usuwam pakiet gvfs-gphoto2..."
        sudo apt remove -y gvfs-gphoto2
        echo "Gotowe. Aparaty NIE będą już montowane automatycznie."
        ;;
        
    enable)
        echo "== Przywracanie automatycznego montowania aparatów =="
        echo "Instaluję pakiet gvfs-gphoto2..."
        sudo apt install -y gvfs-gphoto2
        echo "Gotowe. Automatyczne montowanie aparatów przywrócone."
        ;;
        
    *)
        usage
        ;;
esac

