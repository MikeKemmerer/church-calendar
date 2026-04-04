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
    "nunito-latin.woff2": "https://fonts.gstatic.com/s/nunito/v32/XRXV3I6Li01BKofINeaB.woff2",
    "nunito-latin-ext.woff2": "https://fonts.gstatic.com/s/nunito/v32/XRXV3I6Li01BKofIO-aBXso.woff2",
    "nunito-italic-latin.woff2": "https://fonts.gstatic.com/s/nunito/v32/XRXK3I6Li01BKofIMPyPbj8d7IEAGXNirXAHjaba.woff2",
    "nunito-italic-latin-ext.woff2": "https://fonts.gstatic.com/s/nunito/v32/XRXK3I6Li01BKofIMPyPbj8d7IEAGXNirXAHg6babWk.woff2",
    "nunito-sans-latin.woff2": "https://fonts.gstatic.com/s/nunitosans/v19/pe0TMImSLYBIv1o4X1M8ce2xCx3yop4tQpF_MeTm0lfGWVpNn64CL7U8upHZIbMV51Q42ptCp7t1R-s.woff2",
    "nunito-sans-latin-ext.woff2": "https://fonts.gstatic.com/s/nunitosans/v19/pe0TMImSLYBIv1o4X1M8ce2xCx3yop4tQpF_MeTm0lfGWVpNn64CL7U8upHZIbMV51Q42ptCp7t7R-tCKQ.woff2",
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
