#!/usr/bin/env python3
"""Generate repo/addons.xml, addons.xml.md5, and copy the addon zip into repo/."""
import hashlib
import os
import shutil
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_DIR = os.path.join(ROOT, "repo")


def _parse(path):
    ET.register_namespace("", "")
    return ET.parse(path).getroot()


def _to_str(elem):
    return ET.tostring(elem, encoding="unicode", xml_declaration=False)


def main():
    plugin = _parse(os.path.join(ROOT, "addon.xml"))
    repo   = _parse(os.path.join(REPO_DIR, "repository.cnvod", "addon.xml"))

    version = plugin.get("version")
    print(f"Building repo for plugin v{version}")

    # Copy addon zip into repo/plugin.video.cnvod/
    src_zip = os.path.join(ROOT, "dist", f"plugin.video.cnvod-{version}.zip")
    if not os.path.exists(src_zip):
        raise FileNotFoundError(f"Addon zip not found: {src_zip}. Run build.ps1 first.")
    dest_dir = os.path.join(REPO_DIR, "plugin.video.cnvod")
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copy2(src_zip, os.path.join(dest_dir, f"plugin.video.cnvod-{version}.zip"))
    print(f"  Copied zip -> repo/plugin.video.cnvod/plugin.video.cnvod-{version}.zip")

    # Build and copy repository.cnvod zip into repo/repository.cnvod/
    repo_version = repo.get("version")
    repo_src = os.path.join(REPO_DIR, "repository.cnvod")
    repo_zip_name = f"repository.cnvod-{repo_version}.zip"
    repo_zip_path = os.path.join(repo_src, repo_zip_name)
    # Always rebuild repo zip so it stays in sync with addon.xml
    import zipfile
    with zipfile.ZipFile(repo_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(repo_src, "addon.xml"), f"repository.cnvod/addon.xml")
    print(f"  Built {repo_zip_name}")

    # Generate addons.xml — use explicit LF endings so MD5 matches what git/raw.githubusercontent.com serves
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', "<addons>"]
    lines.append("    " + _to_str(plugin))
    lines.append("    " + _to_str(repo))
    lines.append("</addons>")
    content = "\n".join(lines) + "\n"

    addons_xml = os.path.join(REPO_DIR, "addons.xml")
    with open(addons_xml, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

    # Compute MD5 of exactly the bytes that will be served (UTF-8, LF)
    md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
    with open(os.path.join(REPO_DIR, "addons.xml.md5"), "w", encoding="ascii", newline="\n") as f:
        f.write(md5)

    print(f"  addons.xml written (md5: {md5})")
    print("Done.")


if __name__ == "__main__":
    main()
