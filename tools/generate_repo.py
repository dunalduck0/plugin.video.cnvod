#!/usr/bin/env python3
"""Generate addons.xml, addons.xml.md5 (at repo root), build addon zip in docs/."""
import hashlib
import os
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")


def _parse(path):
    return ET.parse(path).getroot()


def _inner_xml(elem):
    """Serialize elem without the outer tag — preserves child formatting."""
    return ET.tostring(elem, encoding="unicode", xml_declaration=False)


def main():
    plugin = _parse(os.path.join(ROOT, "addon.xml"))
    repo   = _parse(os.path.join(DOCS, "repository.cnvod", "addon.xml"))

    version = plugin.get("version")
    repo_version = repo.get("version")
    print(f"Building repo for plugin v{version}")

    # ── 1. Build addon zip with plugin.video.cnvod/ folder structure ──────────
    dest_dir = os.path.join(DOCS, "plugin.video.cnvod")
    os.makedirs(dest_dir, exist_ok=True)
    zip_name = f"plugin.video.cnvod-{version}.zip"
    zip_path = os.path.join(dest_dir, zip_name)

    # Remove zips for older versions
    for f in os.listdir(dest_dir):
        if f.endswith(".zip") and f != zip_name:
            os.remove(os.path.join(dest_dir, f))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in ("addon.xml", "default.py"):
            zf.write(os.path.join(ROOT, fname), f"plugin.video.cnvod/{fname}")
        for dirpath, _, filenames in os.walk(os.path.join(ROOT, "resources")):
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, ROOT).replace("\\", "/")
                zf.write(full, f"plugin.video.cnvod/{rel}")
    print(f"  Built {zip_name}")

    # ── 2. Rebuild repository.cnvod zip ───────────────────────────────────────
    repo_dir = os.path.join(DOCS, "repository.cnvod")
    repo_zip_name = f"repository.cnvod-{repo_version}.zip"
    repo_zip_path = os.path.join(repo_dir, repo_zip_name)
    with zipfile.ZipFile(repo_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(repo_dir, "addon.xml"), "repository.cnvod/addon.xml")
    print(f"  Built {repo_zip_name}")

    # ── 3. Generate addons.xml at repo ROOT (matches example repo structure) ──
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', "<addons>"]
    lines.append(_inner_xml(plugin))
    lines.append(_inner_xml(repo))
    lines.append("</addons>")
    content = "\n".join(lines) + "\n"

    addons_xml = os.path.join(ROOT, "addons.xml")
    with open(addons_xml, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

    md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
    with open(os.path.join(ROOT, "addons.xml.md5"), "w", encoding="ascii", newline="\n") as f:
        f.write(md5)

    print(f"  addons.xml at repo root (md5: {md5})")
    print("Done.")


if __name__ == "__main__":
    main()
