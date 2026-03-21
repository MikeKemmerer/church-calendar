#!/usr/bin/env python3
"""Download Google Fonts WOFF2 files for local hosting."""
import urllib.request
import os
import sys

FONTS_DIR = os.path.dirname(os.path.abspath(__file__))

FONTS = {
    "cinzel-latin.woff2": "https://fonts.gstatic.com/s/cinzel/v26/8vIJ7ww63mVu7gt79mT7.woff2",
    "cinzel-latin-ext.woff2": "https://fonts.gstatic.com/s/cinzel/v26/8vIJ7ww63mVu7gt7-GT7LEc.woff2",
    "lora-latin.woff2": "https://fonts.gstatic.com/s/lora/v37/0QIvMX1D_JOuMwr7Iw.woff2",
    "lora-latin-ext.woff2": "https://fonts.gstatic.com/s/lora/v37/0QIvMX1D_JOuMwT7I-NP.woff2",
    "lora-italic-latin.woff2": "https://fonts.gstatic.com/s/lora/v37/0QI8MX1D_JOuMw_hLdO6T2wV9KnW-MoFoq92nA.woff2",
    "lora-italic-latin-ext.woff2": "https://fonts.gstatic.com/s/lora/v37/0QI8MX1D_JOuMw_hLdO6T2wV9KnW-MoFoqF2nOeZ.woff2",
}


def main():
    os.chdir(FONTS_DIR)
    for name, url in FONTS.items():
        dest = os.path.join(FONTS_DIR, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"SKIP {name} (already exists, {os.path.getsize(dest)} bytes)")
            continue
        print(f"GET  {name} ...")
        urllib.request.urlretrieve(url, dest)
        print(f"  OK {os.path.getsize(dest)} bytes")
    print("Done.")


if __name__ == "__main__":
    main()
