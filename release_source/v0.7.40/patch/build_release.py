"""Build a self-verifying ZIP and, with --download-url, its HTTPS feed file."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from version import VERSION
from updater import APP_ID, https_url, safe_name


def build(source, output, download_url="", manifest_url="", include_fixtures=True):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    payload = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.is_symlink():continue
        relative = path.relative_to(source).as_posix()
        if "__pycache__" in relative or any(p.startswith(".") for p in path.relative_to(source).parts):continue
        if len(path.relative_to(source).parts) > 1 and path.relative_to(source).parts[0] not in {"assets", "fixtures"}:continue
        if not include_fixtures and relative.startswith("fixtures/"):continue
        if path.suffix.lower() not in {".py", ".pyw", ".txt", ".json", ".png", ".ico", ".bat"}:continue
        if relative == "release.json":continue
        safe_name(relative)
        payload[relative] = path.read_bytes()
    if manifest_url:
        https_url(manifest_url)
        payload["update_channel.json"] = json.dumps({"manifest_url": manifest_url}, indent=2).encode()
    meta = {"app_id": APP_ID, "protocol": 1, "version": VERSION,
            "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in payload.items()}}
    payload["release.json"] = json.dumps(meta, ensure_ascii=False, indent=2).encode()
    path = output / ("MumuCollector_v"+VERSION+".zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in payload.items():archive.writestr("MumuCollector_v"+VERSION+"/"+name, raw)
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    (output/(path.name+".sha256.txt")).write_text(checksum+"  "+path.name+"\n", encoding="ascii")
    if download_url:
        https_url(download_url)
        feed = {"app_id": APP_ID, "protocol": 1, "version": VERSION, "url": download_url,
                "sha256": checksum, "size": path.stat().st_size,
                "notes": "길드 전투 화면과 던전 잔여 횟수 인식 개선"}
        (output/"latest.json").write_text(json.dumps(feed,ensure_ascii=False,indent=2),encoding="utf-8")
    return path, checksum


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--download-url",default="")
    parser.add_argument("--manifest-url",default="")
    parser.add_argument("--without-fixtures",action="store_true")
    args=parser.parse_args()
    path,checksum=build(Path(__file__).resolve().parent,args.output,args.download_url,args.manifest_url,not args.without_fixtures)
    print(path);print("SHA256: "+checksum)
