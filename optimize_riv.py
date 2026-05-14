#!/usr/bin/env python3
import sys, shutil, struct, io
from pathlib import Path
from PIL import Image

def encode_uleb128(n):
    out = []
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)

def decode_uleb128_at(data, pos):
    result, shift = 0, 0
    while pos < len(data):
        byte = data[pos]; pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    return result, pos

def find_images(data):
    images = []
    i = 0
    while i < len(data):
        # PNG
        if data[i:i+8] == b'\x89PNG\r\n\x1a\n':
            start = i
            end = data.find(b'IEND\xaeB`\x82', start)
            if end != -1:
                end += 8   # type(4) + CRC(4); ULEB128 excludes the 4-byte length field
                images.append(('PNG', start, end))
                i = end
                continue
        # JPEG
        if data[i:i+3] == b'\xff\xd8\xff':
            start = i
            j = start + 2
            while j < len(data) - 1:
                if data[j:j+2] == b'\xff\xd9':
                    end = j + 2
                    images.append(('JPEG', start, end))
                    i = end
                    break
                j += 1
            else:
                i += 1
            continue
        i += 1
    return images

def compress_image(img_data, fmt):
    img = Image.open(io.BytesIO(img_data))
    out = io.BytesIO()
    if fmt == 'PNG':
        if img.mode in ('RGBA', 'LA'):
            q = img.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
        else:
            q = img.quantize(colors=256)
        q.save(out, format='PNG', optimize=True)
    else:
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.save(out, format='JPEG', quality=80, optimize=True)
    return out.getvalue()

def optimize(path):
    src = Path(path)
    bak = src.with_suffix('.riv.bak')
    if not bak.exists():
        shutil.copy2(src, bak)
        print(f'Backup: {bak}')

    data = bytearray(src.read_bytes())
    images = find_images(data)
    print(f'Found {len(images)} image(s)')

    offset = 0
    for fmt, raw_start, raw_end in images:
        s = raw_start + offset
        e = raw_end   + offset
        orig = bytes(data[s:e])
        orig_len = len(orig)

        # Find ULEB128 length field before the image
        uleb_val, _ = decode_uleb128_at(data, 0)  # dummy
        # Walk backwards to find ULEB128 encoding of orig_len
        expected_uleb = encode_uleb128(orig_len)
        uleb_start = s - len(expected_uleb)
        if data[uleb_start:s] != expected_uleb:
            print(f'  {fmt} @{raw_start}: ULEB128 mismatch, skipping')
            continue

        comp = compress_image(orig, fmt)
        comp_len = len(comp)
        new_uleb = encode_uleb128(comp_len)

        before = orig_len + len(expected_uleb)
        after  = comp_len + len(new_uleb)
        pct = (1 - after/before) * 100
        print(f'  {fmt} @{raw_start}: {orig_len//1024}KB → {comp_len//1024}KB ({pct:.1f}% smaller)')

        replacement = new_uleb + comp
        data[uleb_start:e] = replacement
        offset += len(replacement) - (e - uleb_start)

    out_size = len(data)
    src.write_bytes(data)
    orig_size = bak.stat().st_size
    print(f'Done: {orig_size//1024}KB → {out_size//1024}KB ({(1-out_size/orig_size)*100:.1f}% reduction)')

if __name__ == '__main__':
    optimize(sys.argv[1] if len(sys.argv) > 1 else 'primeintro.riv')
