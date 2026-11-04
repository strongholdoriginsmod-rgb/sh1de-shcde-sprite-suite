"""Optional authoring QA for the generated handbook (requires PyMuPDF)."""
from pathlib import Path
import sys
try:
    import pymupdf
except ImportError:
    import fitz as pymupdf
ROOT=Path(__file__).resolve().parents[1]
PDF=ROOT/"docs"/"SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf"
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out-dir",type=Path,required=True,
                    help="A NEW, separate QA directory; existing paths are never replaced")
args=parser.parse_args()
QA=args.out_dir.resolve(strict=False)
if QA.exists() or QA.is_symlink():
    raise RuntimeError("QA dir exists; refusing to overwrite")
QA.mkdir(parents=True)
doc=pymupdf.open(PDF)
assert not doc.needs_pass
assert len(doc)==9
total_images=0
total_words=0
bad=[]
for index,page in enumerate(doc):
    images=page.get_images(full=True)
    total_images+=len(images)
    words=page.get_text("words")
    total_words+=len(words)
    for rect in page.search_for("User guide"):
        pass
    for word in words:
        x0,y0,x1,y1,content,*_=word
        if x0 < -0.3 or y0 < -0.3 or x1 > page.rect.width+.3 or y1 > page.rect.height+.3:
            bad.append((index+1,content,tuple(round(x,1) for x in (x0,y0,x1,y1))))
    pix=page.get_pixmap(matrix=pymupdf.Matrix(1,1),alpha=False)
    pix.save(QA/f"page-{index+1:02}.png")
    print(f"PAGE_{index+1}=words:{len(words)},images:{len(images)},size:{page.rect.width:.0f}x{page.rect.height:.0f}")
assert total_images>=5, total_images
assert total_words > 600, total_words
assert not bad, bad[:12]
text="\n".join(page.get_text() for page in doc)
for term in ("Projekt", "Noesis", "Kompatibilität", "Python", "Windows"):
    assert term in text, term
for redaction in ("C:\\Users\\", "E:\\", "D:\\Games\\", "matth"):
    assert redaction not in text, redaction
print("PDF_VALID=1")
print("PAGES="+str(len(doc)))
print("IMAGES="+str(total_images))
print("WORDS="+str(total_words))
print("BAD_WORD_BOUNDS="+str(len(bad)))
