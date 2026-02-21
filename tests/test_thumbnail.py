#!/usr/bin/env python3
"""
Test embedded thumbnail extraction z Canon RP JPEG
"""
from PyQt6.QtGui import QImageReader, QImage
from PyQt6.QtCore import QSize

def test_thumbnail_extraction(path):
    print(f"=== Testing: {path} ===\n")
    
    reader = QImageReader(path)
    
    # Podstawowe info
    print(f"Image count: {reader.imageCount()}")
    print(f"Format: {reader.format().data().decode()}")
    print(f"Supports animation: {reader.supportsAnimation()}")
    
    # Test wszystkich obrazów w pliku
    for i in range(reader.imageCount()):
        reader = QImageReader(path)  # Reset reader
        
        if reader.jumpToImage(i):
            size = reader.size()
            print(f"\nImage {i}:")
            print(f"  Size: {size.width()}x{size.height()}")
            
            # Próba odczytu z auto-transform
            reader.setAutoTransform(True)
            image = reader.read()
            
            if not image.isNull():
                print(f"  Actual size after read: {image.width()}x{image.height()}")
                print(f"  Format: {image.format()}")
                print(f"  ✓ Successfully loaded")
            else:
                print(f"  ✗ Failed to read: {reader.errorString()}")
        else:
            print(f"\nImage {i}: Cannot jump to this image")
    
    # Test z setScaledSize jako fallback
    print("\n=== Fallback test (scaled) ===")
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    reader.setScaledSize(QSize(160, 120))
    image = reader.read()
    
    if not image.isNull():
        print(f"Scaled image: {image.width()}x{image.height()}")
        print("✓ Fallback works")
    else:
        print(f"✗ Fallback failed: {reader.errorString()}")

if __name__ == "__main__":
    # Test z Canon RP JPEG
    test_path = "../assets/pictures/test.jpg"
    test_thumbnail_extraction(test_path)
