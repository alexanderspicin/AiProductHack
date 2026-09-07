"""Read-only OOXML/PDF inspection; source files stay unchanged."""
import argparse
import json
from pathlib import Path, PurePosixPath
import posixpath
import zipfile
from xml.etree import ElementTree as ET
from pypdf import PdfReader

N = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
     "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
     "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--deck",type=Path,required=True)
    parser.add_argument("--criteria",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    result={"deck":args.deck.name,"criteria":args.criteria.name,"slides":[]}
    with zipfile.ZipFile(args.deck) as z:
        def xml(p):return ET.fromstring(z.read(p))
        def relationships(p):
            folder,name=posixpath.split(p);rp=f"{folder}/_rels/{name}.rels"
            if rp not in z.namelist():return {}
            return {r.attrib["Id"]:{"type":r.attrib["Type"].rsplit("/",1)[-1],"target":r.attrib["Target"],
                                    "external":r.attrib.get("TargetMode")=="External"} for r in xml(rp)}
        pres=xml("ppt/presentation.xml");rels=relationships("ppt/presentation.xml")
        result["size"]=pres.find("p:sldSz",N).attrib
        for number,element in enumerate(pres.findall("p:sldIdLst/p:sldId",N),1):
            rel=rels[element.attrib[f'{{{N["r"]}}}id']];file=posixpath.normpath("ppt/"+rel["target"])
            slide=xml(file);sr=relationships(file)
            notes=[]
            for r in sr.values():
                if r["type"]=="notesSlide":
                    note=xml(posixpath.normpath(posixpath.dirname(file)+"/"+r["target"]))
                    notes=[t.text or "" for t in note.findall(".//a:t",N)]
            shapes=[]
            for sp in slide.findall(".//p:sp",N):
                paragraphs=["".join(t.text or "" for t in p.findall(".//a:t",N)) for p in sp.findall(".//a:p",N)]
                if not any(paragraphs):continue
                name=sp.find("p:nvSpPr/p:cNvPr",N)
                sizes=[int(r.attrib["sz"])/100 for r in sp.findall(".//a:rPr",N) if "sz" in r.attrib]
                shapes.append({"name":name.attrib.get("name","") if name is not None else "","text":"\n".join(paragraphs),"font_sizes":sorted(set(sizes))})
            result["slides"].append({"slide":number,"hidden":slide.attrib.get("show")=="0",
                "paragraphs":["".join(t.text or "" for t in p.findall(".//a:t",N)) for p in slide.findall(".//a:p",N)],
                "notes":notes,"shapes":shapes,"relationships":list(sr.values())})
        result["media"]=[{"file":f.filename,"bytes":f.file_size} for f in z.infolist() if f.filename.startswith("ppt/media/")]
    result["criteria_pages"]=[p.extract_text() for p in PdfReader(args.criteria).pages]
    (args.out/"sources.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    sections=[f'### Слайд {s["slide"]}\n'+"\n".join(s["paragraphs"])+"\nЗаметки: "+" | ".join(s["notes"]) for s in result["slides"]]
    (args.out/"slides.txt").write_text("\n\n".join(sections))
    (args.out/"criteria.txt").write_text("\n\n".join(f"Страница {i+1}\n{text}" for i,text in enumerate(result["criteria_pages"])))
    print(json.dumps({"slides":len(result["slides"]),"criteria_pages":len(result["criteria_pages"]),"media":result["media"]},ensure_ascii=False))


if __name__=="__main__":main()
