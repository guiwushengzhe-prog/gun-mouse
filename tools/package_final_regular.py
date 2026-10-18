"""收齐最终制造文件、装配视图和核对记录，并检查交付包内容。"""
import hashlib
import json
import shutil
import zipfile

from final_regular_layout import ROOT, OUT, RELEASE


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (ROOT/"pcb/嘉立创最终版/枪型飞鼠最终版.eprj3").exists():
        raise RuntimeError("主板已切换嘉立创，请用tools/package_jlc_final.py，避免旧制造文件覆盖当前交付。")
    records = RELEASE/"核对记录"
    records.mkdir(parents=True, exist_ok=True)
    for source in (OUT/"模型核对.json", OUT/"pcb/孔位与布线核对.json", OUT/"pcb/规则检查.json"):
        shutil.copy2(source, records/source.name)
    view = RELEASE/"装配查看"
    shutil.copy2(OUT/"最终版截图.html", view/"最终版截图.html")
    shutil.copytree(OUT/"多角度检视", view/"多角度检视", dirs_exist_ok=True)
    source_dir = RELEASE/"工程源文件"
    old_config = source_dir/"模型配置.json"
    if old_config.exists():
        old_config.rename(source_dir/"模型基准配置.json")
    shutil.copy2(OUT/"pcb/孔位与布线核对.json", source_dir/"最终孔位与网络.json")
    # 保持说明与记录的换行一致，版本管理取出后仍能核对交付文本。
    for path in RELEASE.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".txt", ".json", ".html"}:
            path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    report = json.loads((OUT/"模型核对.json").read_text(encoding="utf-8"))
    board = OUT/"pcb/gunmouse-final.kicad_pcb"
    assert report["完整装配"]["pcb_sha256"] == digest(board)
    assert report["完整装配"]["obj_sha256"] == digest(OUT/"第二代完整装配.obj")
    assert digest(board) == digest(RELEASE/"电路板/gunmouse-final.kicad_pcb")
    assert not report["完整装配"]["wire_insulation_pair_overlaps_mm3"]
    assert all(not shape["交叠"] and shape["有效单体"] for shape in report["实体"].values())
    with zipfile.ZipFile(RELEASE/"枪型飞鼠_最终版_上传打印.zip") as z:
        assert set(z.namelist()) == {"主体底座.stl", "摇杆支座.stl"} and z.testzip() is None
        for name in z.namelist():
            assert hashlib.sha256(z.read(name)).hexdigest() == digest(RELEASE/"三维打印"/name)
    with zipfile.ZipFile(RELEASE/"枪型飞鼠_最终版_上传打板.zip") as z:
        assert len(z.namelist()) == 10 and z.testzip() is None
    manifest = {str(path.relative_to(RELEASE)).replace("\\", "/"): {"字节": path.stat().st_size, "SHA256": digest(path)}
                for path in sorted(RELEASE.rglob("*")) if path.is_file() and path.name != "交付文件核对.json"}
    (RELEASE/"交付文件核对.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    archive = ROOT/"release/枪型飞鼠_最终版_完整文件.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(RELEASE.rglob("*")):
            if path.is_file():
                z.write(path, str(path.relative_to(RELEASE)))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None and len(z.namelist()) == len(manifest)+1
    print("最终完整文件包", archive, archive.stat().st_size, "字节", flush=True)


if __name__ == "__main__":
    main()
