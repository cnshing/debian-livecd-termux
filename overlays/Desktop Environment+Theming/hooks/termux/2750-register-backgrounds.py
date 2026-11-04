#!/data/data/com.termux/files/usr/bin/python
"""Register the copied LiveCD wallpaper collection with GNOME Appearance."""
from pathlib import Path
import xml.etree.ElementTree as ET

from desktop import DATA


def register_backgrounds(data=DATA):
    backgrounds = data / 'backgrounds'
    catalog = ET.Element('wallpapers')
    for image in sorted(backgrounds.rglob('*')):
        if not image.is_file() or image.suffix.lower() not in ('.avif', '.jpg', '.jpeg', '.png', '.webp'):
            continue
        item = ET.SubElement(catalog, 'wallpaper', deleted='false')
        ET.SubElement(item, 'name').text = f'{image.parent.name} — {image.stem}'
        ET.SubElement(item, 'filename').text = str(image.resolve())
        ET.SubElement(item, 'options').text = 'zoom'
        ET.SubElement(item, 'shade_type').text = 'solid'
        ET.SubElement(item, 'pcolor').text = '#000000'
        ET.SubElement(item, 'scolor').text = '#000000'
    destination = data / 'gnome-background-properties/livecd.xml'
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(catalog)
    # Only our catalog is replaced; user-added wallpaper catalogs are retained.
    temporary = destination.with_suffix('.xml.tmp')
    ET.ElementTree(catalog).write(temporary, encoding='utf-8', xml_declaration=True)
    temporary.replace(destination)
    print(f'Registered {len(catalog)} LiveCD wallpapers in {destination}')
    return destination


if __name__ == '__main__':
    register_backgrounds()
