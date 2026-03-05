#!/usr/bin/env python3
import argparse
import re
import urllib.request
from pathlib import Path


RAW_ICON_PREFIX = "https://raw.githubusercontent.com/mingrammer/diagrams/"


def local_name_from_url(url: str) -> str:
    marker = "/resources/"
    idx = url.find(marker)
    if idx == -1:
        return Path(url).name
    rel = url[idx + len(marker) :]
    return rel.replace("/", "__")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and relink remote diagram icons"
    )
    parser.add_argument("--svg-dir", default="apps/sandboxed-react-agent/docs/diagrams")
    parser.add_argument(
        "--icons-dir", default="apps/sandboxed-react-agent/docs/diagrams/icons"
    )
    args = parser.parse_args()

    svg_dir = Path(args.svg_dir)
    icons_dir = Path(args.icons_dir)
    icons_dir.mkdir(parents=True, exist_ok=True)

    pattern = re.compile(r"xlink:href=\"(https://[^\"]+)\"")
    downloaded: dict[str, str] = {}

    for svg_path in svg_dir.glob("*.svg"):
        text = svg_path.read_text(encoding="utf-8")
        urls = sorted(set(pattern.findall(text)))
        replacements: dict[str, str] = {}

        for url in urls:
            if not url.startswith(RAW_ICON_PREFIX):
                continue
            if url not in downloaded:
                icon_name = local_name_from_url(url)
                out_file = icons_dir / icon_name
                if not out_file.exists():
                    urllib.request.urlretrieve(url, out_file)
                downloaded[url] = f"icons/{icon_name}"
            replacements[url] = downloaded[url]

        for remote, local in replacements.items():
            text = text.replace(f'xlink:href="{remote}"', f'xlink:href="{local}"')

        svg_path.write_text(text, encoding="utf-8")
        print(f"Updated icon links in {svg_path}")

    print(f"Localized {len(downloaded)} icon URLs into {icons_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
