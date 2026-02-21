#!/usr/bin/env python3
"""
Test embedded thumbnail + preview extraction z Canon RP JPEG
"""
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QTransform
import piexif
import sys
import subprocess
import tempfile
import os

def test_preview_exiftool(path):
    """Test ekstrakcji preview przez exiftool"""
    print("=== EXIFTOOL Preview test ===")
    try:
        # Tymczasowy plik dla preview
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name
        
        # Wyciągnij preview przez exiftool
        result = subprocess.run(
            ['exiftool', '-b', '-PreviewImage', path],
            stdout=open(tmp_path, 'wb'),
            stderr=subprocess.PIPE
        )
        
        if result.returncode == 0 and os.path.getsize(tmp_path) > 0:
            # Załaduj preview
            pixmap = QPixmap(tmp_path)
            
            if not pixmap.isNull():
                print(f"✓ Preview loaded: {pixmap.width()}x{pixmap.height()}")
                print(f"✓ Preview size: {os.path.getsize(tmp_path)} bytes")
                
                # Sprawdź czy trzeba obrócić (EXIF orientation)
                exif_dict = piexif.load(path)
                if '0th' in exif_dict and piexif.ImageIFD.Orientation in exif_dict['0th']:
                    orientation = exif_dict['0th'][piexif.ImageIFD.Orientation]
                    print(f"  Orientation: {orientation}")
                    
                    transform = QTransform()
                    if orientation == 3:
                        transform.rotate(180)
                    elif orientation == 6:
                        transform.rotate(90)
                    elif orientation == 8:
                        transform.rotate(-90)
                    
                    if orientation in [3, 6, 8]:
                        pixmap = pixmap.transformed(transform)
                        print(f"  After rotation: {pixmap.width()}x{pixmap.height()}")
                
                print("\n✓✓✓ EXIFTOOL Preview WORKS! ✓✓✓")
                os.unlink(tmp_path)
                return True
            else:
                print("✗ Failed to load preview")
        else:
            print("✗ exiftool failed or no preview")
            
        os.unlink(tmp_path)
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    return False

def test_thumbnail_piexif(path):
    """Test ekstrakcji thumbnail przez piexif"""
    print("\n=== PIEXIF Thumbnail test ===")
    try:
        exif_dict = piexif.load(path)
        
        if 'thumbnail' in exif_dict and exif_dict['thumbnail']:
            pixmap = QPixmap()
            pixmap.loadFromData(exif_dict['thumbnail'])
            
            if not pixmap.isNull():
                print(f"✓ Thumbnail loaded: {pixmap.width()}x{pixmap.height()}")
                print(f"✓ Thumbnail size: {len(exif_dict['thumbnail'])} bytes")
                return True
                
    except Exception as e:
        print(f"✗ Error: {e}")
    
    return False

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    test_path = "../assets/pictures/test.jpg"
    
    print(f"=== Testing: {test_path} ===\n")
    
    preview_ok = test_preview_exiftool(test_path)
    thumbnail_ok = test_thumbnail_piexif(test_path)
    
    print("\n" + "="*50)
    print("SUMMARY:")
    print(f"  Preview (exiftool): {'✓ WORKS' if preview_ok else '✗ FAILED'}")
    print(f"  Thumbnail (piexif): {'✓ WORKS' if thumbnail_ok else '✗ FAILED'}")
    print("="*50)
